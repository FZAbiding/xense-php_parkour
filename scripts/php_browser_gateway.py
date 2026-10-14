#!/usr/bin/env python3
"""Serve local noVNC and relay its WebSocket to a local x11vnc server."""

from __future__ import annotations

import argparse
import asyncio
import functools
import http.server
import threading
from pathlib import Path

from websockets.asyncio.server import serve


async def relay(websocket, vnc_port: int) -> None:
    reader, writer = await asyncio.open_connection("127.0.0.1", vnc_port)

    async def client_to_vnc() -> None:
        async for data in websocket:
            if isinstance(data, str):
                raise ValueError("VNC requires binary WebSocket messages")
            writer.write(data)
            await writer.drain()

    async def vnc_to_client() -> None:
        while data := await reader.read(65536):
            await websocket.send(data)

    tasks = [asyncio.create_task(client_to_vnc()), asyncio.create_task(vnc_to_client())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
    finally:
        writer.close()
        await writer.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--novnc", type=Path,
                        default=Path("/tmp/php-interactive/usr/share/novnc"))
    parser.add_argument("--http-port", type=int, default=6081)
    parser.add_argument("--ws-port", type=int, default=6080)
    parser.add_argument("--vnc-port", type=int, default=5900)
    args = parser.parse_args()
    if not (args.novnc / "vnc.html").is_file():
        parser.error("noVNC files are missing; see DEMO_VIDEO_WORKFLOW.md")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(args.novnc))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.http_port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    async def run() -> None:
        async with serve(lambda ws: relay(ws, args.vnc_port),
                         "127.0.0.1", args.ws_port, max_size=None):
            print(f"http://127.0.0.1:{args.http_port}/vnc.html"
                  f"?host=127.0.0.1&port={args.ws_port}&path=websockify"
                  "&encrypt=0&autoconnect=true", flush=True)
            await asyncio.Future()

    try:
        asyncio.run(run())
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
