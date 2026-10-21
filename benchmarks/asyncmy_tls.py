"""TLS capability and initialization probes; does not enable prototype TLS.

Reuse the project's owned password-authenticated TLS server and byte-forwarding
peer. Generated certificates and credentials stay local; reports contain only
negotiation outcomes, never authentication packets or diagnostic text.
"""

import argparse
import asyncio
import json
import ssl
from importlib import import_module
from importlib.metadata import version
from typing import Any

from snekql import mariadb
from tests.mariadb.test_required_tls import _GreetingProxy, tls_peer


def _options(config: mariadb.Config, context: ssl.SSLContext) -> dict[str, Any]:
    return {
        "host": config.host,
        "port": config.port,
        "user": config.user,
        "password": config.password,
        "db": config.database,
        "charset": "utf8mb4",
        "autocommit": True,
        "ssl": context,
        "connect_timeout": 5,
    }


async def _connect(driver: Any, options: dict[str, Any]) -> dict[str, Any]:
    connection = None
    try:
        async with asyncio.timeout(10):
            connection = await driver.connect(**options)
            async with connection.cursor() as cursor:
                await cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
                cipher = (await cursor.fetchone())[1]
                await cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_version'")
                tls_version = (await cursor.fetchone())[1]
                await cursor.execute("SELECT 42")
                answer = (await cursor.fetchone())[0]
            return {
                "connected": True,
                "cipher_present": bool(cipher),
                "tls_version": tls_version,
                "answer": answer,
            }
    except Exception as error:
        cause: BaseException | None = error
        certificate_failure = False
        while cause is not None:
            certificate_failure |= isinstance(cause, ssl.SSLCertVerificationError)
            cause = cause.__context__
        return {
            "connected": False,
            "certificate_failure": certificate_failure,
            "error_type": type(error).__name__,
        }
    finally:
        if connection is not None:
            connection.close()


async def _cancel_initialization(
    driver: Any, options: dict[str, Any], peer: _GreetingProxy
) -> dict[str, Any]:
    peer.pause_greeting = True
    peer.greeting_paused.clear()
    pending = asyncio.ensure_future(driver.create_pool(minsize=1, maxsize=2, **options))
    error_type = None
    response_bytes = None
    peer_closed = False
    try:
        async with asyncio.timeout(10):
            await peer.greeting_paused.wait()
            if pending.done():
                message = "initialization finished before cancellation barrier"
                raise RuntimeError(message)
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError as error:
                error_type = type(error).__name__
            try:
                async with asyncio.timeout(2):
                    await peer.response_observed.wait()
                response_bytes = peer.denied_bytes[-1]
                peer_closed = response_bytes == 0
            except TimeoutError:
                pass
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        if not pending.cancelled() and pending.exception() is None:
            created = pending.result()
            created.close()
            await created.wait_closed()
        peer.pause_greeting = False
    # The above EOF observation occurs before forced disconnect/fixture cleanup or explicit GC.
    async with asyncio.timeout(10):
        pool = await driver.create_pool(minsize=1, maxsize=2, **options)
        try:
            async with pool.acquire() as connection, connection.cursor() as cursor:
                await cursor.execute("SELECT 42")
                answer = (await cursor.fetchone())[0]
                await cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
                cipher = (await cursor.fetchone())[1]
        finally:
            pool.close()
            await pool.wait_closed()
    return {
        "error_type": error_type,
        "peer_closed_before_cleanup": peer_closed,
        "pre_cleanup_response_bytes": response_bytes,
        "recovery_answer": answer,
        "recovery_cipher_present": bool(cipher),
        "shutdown_completed": True,
    }


async def _cancel_growth(
    driver: Any, options: dict[str, Any], peer: _GreetingProxy
) -> dict[str, Any]:
    async with asyncio.timeout(20):
        pool = await driver.create_pool(minsize=1, maxsize=2, **options)
        first = None
        pending = None
        error_type = None
        response_bytes = None
        peer_closed = False
        try:
            first = await pool.acquire()
            async with first.cursor() as cursor:
                await cursor.execute("SELECT CONNECTION_ID()")
                first_id = (await cursor.fetchone())[0]
            peer.pause_greeting = True
            peer.greeting_paused.clear()
            pending = asyncio.ensure_future(pool.acquire())
            await peer.greeting_paused.wait()
            if pending.done():
                message = "growth finished before cancellation barrier"
                raise RuntimeError(message)
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError as error:
                error_type = type(error).__name__
            try:
                async with asyncio.timeout(2):
                    await peer.response_observed.wait()
                response_bytes = peer.denied_bytes[-1]
                peer_closed = response_bytes == 0
            except TimeoutError:
                pass
            peer.pause_greeting = False
            async with pool.acquire() as connection, connection.cursor() as cursor:
                await cursor.execute("SELECT 42, CONNECTION_ID()")
                answer, second_id = await cursor.fetchone()
                await cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
                cipher = (await cursor.fetchone())[1]
            size, free = pool.size, pool.freesize
        finally:
            peer.pause_greeting = False
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
                if not pending.cancelled() and pending.exception() is None:
                    pool.release(pending.result())
            if first is not None:
                pool.release(first)
            pool.close()
            await pool.wait_closed()
    return {
        "error_type": error_type,
        "peer_closed_before_cleanup": peer_closed,
        "pre_cleanup_response_bytes": response_bytes,
        "recovery_answer": answer,
        "recovery_cipher_present": bool(cipher),
        "different_connection": first_id != second_id,
        "size_with_first_held": size,
        "free_with_first_held": free,
        "shutdown_completed": True,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=(
            "verified",
            "untrusted",
            "wrong-host",
            "stripped",
            "cancel-initialization",
            "cancel-growth",
        ),
        required=True,
    )
    args = parser.parse_args()
    results = []
    async with tls_peer() as peer:
        assert peer.config.tls is not None  # noqa: S101 - fixture provides TLS
        peer.deny_tls = args.scenario == "stripped"
        names = (
            ("aiomysql", "asyncmy", "snekql-aiomysql")
            if peer.deny_tls
            else ("aiomysql", "asyncmy")
        )
        for name in names:
            peer.response_observed.clear()
            result: dict[str, Any]
            context = ssl.create_default_context(
                cafile=None
                if args.scenario == "untrusted"
                else str(peer.config.tls.ca_file)
            )
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            options = _options(peer.config, context)
            if args.scenario == "wrong-host":
                options["host"] = "localhost"
            if args.scenario == "cancel-initialization":
                result = await _cancel_initialization(
                    import_module(name), options, peer
                )
            elif args.scenario == "cancel-growth":
                result = await _cancel_growth(import_module(name), options, peer)
            elif name == "snekql-aiomysql":
                try:
                    async with (
                        asyncio.timeout(10),
                        await mariadb.Database.initialize(peer.config),
                    ):
                        result = {"connected": True}
                except mariadb.DatabaseRuntimeError as error:
                    result = {"connected": False, "error_type": type(error).__name__}
            else:
                result = await _connect(import_module(name), options)
            if peer.deny_tls:
                async with asyncio.timeout(5):
                    await peer.response_observed.wait()
                result.update(
                    response_kind=peer.denied_packet_types[-1],
                    response_bytes=peer.denied_bytes[-1],
                )
            results.append(
                {
                    "driver": name,
                    "version": version(
                        "aiomysql" if name == "snekql-aiomysql" else name
                    ),
                    **result,
                }
            )
            await peer.disconnect()
    print(
        json.dumps({"schema_version": 1, "scenario": args.scenario, "results": results})
    )


if __name__ == "__main__":
    asyncio.run(main())
