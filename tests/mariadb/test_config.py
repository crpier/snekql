"""MariaDB runtime configuration contracts."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from ssl import CERT_REQUIRED, TLSVersion
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_raises, test

from snekql import mariadb
from snekql.mariadb import Database, DatabaseRuntimeError
from snekql.testing.mariadb import temporary_mariadb_server


@test(mark="fast")
def tls_config_builds_a_hostname_checking_verified_context() -> None:
    """The TLS path cannot silently disable certificate verification."""

    context = mariadb.TLSConfig()._create_ssl_context()

    assert_eq(context.check_hostname, True)
    assert_eq(context.verify_mode, CERT_REQUIRED)
    assert_eq(context.minimum_version, TLSVersion.TLSv1_2)


@test(mark="fast")
def tls_config_requires_complete_client_credentials() -> None:
    """A client certificate and private key are one indivisible setting."""

    with assert_raises(DatabaseRuntimeError):
        _ = mariadb.TLSConfig(cert_file=Path("client.crt"))
    with assert_raises(DatabaseRuntimeError):
        _ = mariadb.TLSConfig(key_file=Path("client.key"))


@test(mark="fast")
def tls_config_rejects_unix_socket_transport() -> None:
    """Verified hostname TLS is a TCP transport policy."""

    with assert_raises(DatabaseRuntimeError):
        _ = mariadb.Config(
            database="app",
            user="snekql",
            unix_socket=Path("mariadb.sock"),
            tls=mariadb.TLSConfig(),
        )


def _create_self_signed_server_certificate(directory: Path) -> tuple[Path, Path]:
    certificate = directory / "server.crt"
    private_key = directory / "server.key"
    result = subprocess.run(
        (
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert_eq(result.returncode, 0, msg=result.stderr)
    return certificate, private_key


@test(mark="medium")
async def tls_config_connects_to_a_certificate_required_server() -> None:
    """The driver pool completes a verified TLS handshake end to end."""

    with TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        certificate, private_key = _create_self_signed_server_certificate(directory)
        async with temporary_mariadb_server(
            auth="password",
            data_directory=directory / "data",
            server_args=(
                f"--ssl-ca={certificate}",
                f"--ssl-cert={certificate}",
                f"--ssl-key={private_key}",
                "--require-secure-transport=ON",
            ),
            transports={"tcp"},
        ) as server:
            config = replace(
                server.config(transport="tcp"),
                tls=mariadb.TLSConfig(ca_file=certificate),
            )
            database = await Database.initialize(config)
            await database.close()


@test(mark="fast")
def runtime_policies_are_safe_by_default_and_validate() -> None:
    """Queries default to bounded operations and redacted telemetry."""

    config = mariadb.Config(database="app", user="snekql")

    assert_eq(config.operation_timeout, 30.0)
    assert_eq(config.parameter_visibility, "redacted")
    with assert_raises(DatabaseRuntimeError):
        _ = mariadb.Config(
            database="app",
            user="snekql",
            operation_timeout=-1.0,
        )
    with assert_raises(DatabaseRuntimeError):
        _ = mariadb.Config(
            database="app",
            user="snekql",
            parameter_visibility="unknown",  # ty: ignore[invalid-argument-type]
        )
