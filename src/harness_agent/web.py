from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .copilot_runner import run_jev, run_traditional
from .models import DEFAULT_ORDER


WEB_ROOT = Path(__file__).with_name("web")


async def compare_harnesses(request: str, language: str = "zh-TW") -> dict[str, Any]:
    settings = Settings.from_env()
    results = await asyncio.gather(
        run_jev(request, settings, language=language),
        run_traditional(request, settings, language=language),
        return_exceptions=True,
    )
    payload: dict[str, Any] = {"request": request}
    for name, result in zip(("jev", "traditional"), results, strict=True):
        if isinstance(result, BaseException):
            payload[name] = {
                "error": f"{type(result).__name__}: {result}",
                "engine": name,
            }
        else:
            payload[name] = asdict(result)
    return payload


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "HarnessDashboard/0.1"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json({"status": "ok"})
            return
        if path == "/":
            self._file(WEB_ROOT / "index.html")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/compare-stream":
            self._compare_stream()
            return
        if path != "/api/compare":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            request = str(body.get("request", "")).strip() or DEFAULT_ORDER
            language = str(body.get("language", "zh-TW"))
            result = asyncio.run(compare_harnesses(request, language))
            self._json(result)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as error:
            self._json(
                {"error": f"{type(error).__name__}: {error}"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _compare_stream(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            request = str(body.get("request", "")).strip() or DEFAULT_ORDER
            language = str(body.get("language", "zh-TW"))
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            asyncio.run(self._stream_comparison(request, language))
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as error:
            try:
                self._write_line({"type": "fatal", "error": f"{type(error).__name__}: {error}"})
            except (BrokenPipeError, ConnectionResetError):
                return

    async def _stream_comparison(self, request: str, language: str) -> None:
        settings = Settings.from_env()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def progress(payload: dict[str, object]) -> None:
            queue.put_nowait({"type": "progress", **payload})

        async def execute(name: str) -> None:
            runner = run_jev if name == "jev" else run_traditional
            try:
                result = await runner(
                    request,
                    settings,
                    on_progress=progress,
                    language=language,
                )
                await queue.put({"type": "result", "engine": name, "result": asdict(result)})
            except Exception as error:
                await queue.put(
                    {
                        "type": "result",
                        "engine": name,
                        "result": {"engine": name, "error": f"{type(error).__name__}: {error}"},
                    }
                )

        tasks = [
            asyncio.create_task(execute("jev")),
            asyncio.create_task(execute("traditional")),
        ]
        completed = 0
        while completed < len(tasks):
            event = await queue.get()
            self._write_line(event)
            if event.get("type") == "result":
                completed += 1
        await asyncio.gather(*tasks)

    def _write_line(self, payload: object) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def log_message(self, format: str, *args: object) -> None:
        print(f"[dashboard] {self.address_string()} - {format % args}")

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the Harness Agent comparison dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Harness dashboard: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
