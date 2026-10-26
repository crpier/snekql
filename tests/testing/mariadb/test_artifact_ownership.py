"""Callers can own temporary server artifacts without changing their retention."""

from pathlib import Path
from tempfile import TemporaryDirectory

from anyio import Path as AsyncPath
from snektest import assert_eq, assert_in, assert_raises, assert_true, test

from snekql.testing.mariadb import TemporaryMariaDBServerError, temporary_mariadb_server


@test(mark="slow")
async def runtime_base_contains_retained_server_artifacts() -> None:
    """Data, logs, and sockets stay inside an explicit owner until it cleans up."""

    with TemporaryDirectory(prefix="sq-") as directory:
        base = Path(directory)
        async with temporary_mariadb_server(runtime_base_directory=base) as server:
            assert_eq((await server.run_sql("SELECT 1")).returncode, 0)
            assert_true(server.data_directory.is_relative_to(base))
            assert_true(server.error_log_path.is_relative_to(base))
            assert_true(server.pid_path.is_relative_to(base))
            assert server.socket_path is not None
            assert_true(server.socket_path.is_relative_to(base))
        assert_true(await AsyncPath(server.data_directory).is_dir())
        assert_true(await AsyncPath(server.error_log_path).is_file())
    assert_true(not await AsyncPath(base).exists())


@test(mark="medium")
async def nonexistent_runtime_base_reports_a_domain_error() -> None:
    """An unusable parent is rejected without silently allocating elsewhere."""

    with TemporaryDirectory(prefix="sq-") as directory:
        base = Path(directory) / "missing"
        with assert_raises(TemporaryMariaDBServerError) as error:
            async with temporary_mariadb_server(runtime_base_directory=base):
                assert_true(False, msg="a missing runtime base must prevent startup")
        assert_in("runtime directory", str(error.exception))
        assert_eq([path async for path in AsyncPath(directory).iterdir()], [])


@test(mark="slow")
async def servers_sharing_a_runtime_base_have_independent_artifacts() -> None:
    """A shared parent does not alias databases or overwrite another server's logs."""

    with TemporaryDirectory(prefix="sq-") as directory:
        base = Path(directory)
        async with (
            temporary_mariadb_server(runtime_base_directory=base) as first,
            temporary_mariadb_server(runtime_base_directory=base) as second,
        ):
            await first.run_sql("CREATE TABLE only_first (id INT)")
            assert_eq(
                (await second.run_sql("SHOW TABLES LIKE 'only_first'")).stdout, ""
            )
            assert_true(first.error_log_path.parent != second.error_log_path.parent)
            assert_eq(
                (await AsyncPath(first.error_log_path.parent).stat()).st_mode & 0o777,
                0o700,
            )
        assert_true(await AsyncPath(first.data_directory).is_dir())
        assert_true(await AsyncPath(second.data_directory).is_dir())


@test(mark="slow")
async def runtime_owner_does_not_take_ownership_of_explicit_data() -> None:
    """Deleting a runtime base leaves explicit external data available for reuse."""

    with TemporaryDirectory(prefix="sq-") as data_parent:
        data = Path(data_parent) / "data"
        with TemporaryDirectory(prefix="sq-") as directory:
            async with temporary_mariadb_server(
                runtime_base_directory=Path(directory), data_directory=data
            ) as server:
                await server.run_sql("CREATE TABLE retained (id INT)")
        assert_true(await AsyncPath(data).is_dir())
        with TemporaryDirectory(prefix="sq-") as directory:
            async with temporary_mariadb_server(
                runtime_base_directory=Path(directory), data_directory=data
            ) as server:
                assert_in("retained", (await server.run_sql("SHOW TABLES")).stdout)


@test(mark="slow")
async def startup_failure_remains_within_the_runtime_owner() -> None:
    """An installer failure before yield leaves inspectable files only under the owner."""

    with TemporaryDirectory(prefix="sq-") as directory:
        base = Path(directory)
        installer = base / "installer"
        await AsyncPath(installer).write_text(
            '#!/bin/sh\necho "controlled installer failure" >&2\nexit 7\n'
        )
        await AsyncPath(installer).chmod(0o700)
        with assert_raises(TemporaryMariaDBServerError) as error:
            async with temporary_mariadb_server(
                runtime_base_directory=base, install_db=installer
            ):
                assert_true(
                    False, msg="controlled installer failure must prevent yield"
                )
        assert_in("controlled installer failure", str(error.exception))
        retained = [path async for path in AsyncPath(base).glob("snekql-mariadb-*")]
        assert_eq(len(retained), 1)
        assert_true(await (retained[0] / "data").is_dir())
    assert_true(not await AsyncPath(base).exists())


@test(mark="medium")
async def cleaning_data_cannot_delete_the_runtime_base() -> None:
    """A destructive data reset must not invalidate its own runtime paths."""

    with TemporaryDirectory(prefix="sq-") as directory:
        data = Path(directory)
        with assert_raises(TemporaryMariaDBServerError) as error:
            _ = temporary_mariadb_server(
                data_directory=data,
                runtime_base_directory=data / "runtime",
                clean_before_start=True,
            )
        assert_in("runtime_base_directory", str(error.exception))
        assert_true(await AsyncPath(data).is_dir())
