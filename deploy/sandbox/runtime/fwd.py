#!/usr/bin/env python3
"""Bridge the sandbox's private loopback to the two host Unix sockets.

llm:  127.0.0.1:<llm_port> inside  ->  host DeepSeek-only proxy socket
web:  host front proxy  ->  web socket  ->  127.0.0.1:<web_port> inside (DSH)
"""
import asyncio
import os
import sys


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def bridge(open_upstream):
    async def handle(reader, writer):
        try:
            up_reader, up_writer = await open_upstream()
        except OSError:
            writer.close()
            return
        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))
    return handle


async def main():
    llm_sock, web_sock = sys.argv[1], sys.argv[2]
    llm_port, web_port = int(sys.argv[3]), int(sys.argv[4])
    llm = await asyncio.start_server(
        bridge(lambda: asyncio.open_unix_connection(llm_sock)), "127.0.0.1", llm_port)
    if os.path.exists(web_sock):
        os.unlink(web_sock)
    web = await asyncio.start_unix_server(
        bridge(lambda: asyncio.open_connection("127.0.0.1", web_port)), web_sock)
    os.chmod(web_sock, 0o660)
    async with llm, web:
        await asyncio.gather(llm.serve_forever(), web.serve_forever())


asyncio.run(main())
