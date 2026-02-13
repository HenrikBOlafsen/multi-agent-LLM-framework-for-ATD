#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

DEFAULT_REPLY = (
    "You are a refactoring assistant.\n"
    "For this smoke test: do NOT modify any files.\n"
    "Reply with a short confirmation that you made no changes.\n"
)

FINISH_MESSAGE = "No changes made (smoke test)."


def _read_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    n = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(n) if n > 0 else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _write_json(handler: BaseHTTPRequestHandler, code: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _is_openhands(req: Dict[str, Any]) -> bool:
    # 1) Standard tool payload
    tools = req.get("tools")
    if isinstance(tools, list) and tools:
        return True

    # 2) Some clients use legacy "functions"
    funcs = req.get("functions")
    if isinstance(funcs, list) and funcs:
        return True

    # 3) Heuristic: OpenHands system prompt text is present in messages
    msgs = req.get("messages")
    if isinstance(msgs, list):
        for m in msgs:
            if not isinstance(m, dict):
                continue
            c = m.get("content")
            if isinstance(c, str) and ("You are OpenHands agent" in c or "OpenHands agent" in c):
                return True

    return False



def _build_finish_tool_call() -> Dict[str, Any]:
    # OpenAI tool-calling style
    return {
        "id": "call_finish_1",
        "type": "function",
        "function": {
            "name": "finish",
            "arguments": json.dumps({"message": FINISH_MESSAGE}, ensure_ascii=False),
        },
    }


def _write_sse(handler: BaseHTTPRequestHandler, obj: Dict[str, Any]) -> None:
    # SSE event format
    line = f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")
    handler.wfile.write(line)
    handler.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-llm/0.3"

    def log_message(self, fmt: str, *args: Any) -> None:
        # keep logs short but useful
        print("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            _write_json(
                self,
                200,
                {"object": "list", "data": [{"id": "dummy", "object": "model"}]},
            )
            return
        _write_json(self, 404, {"error": {"message": f"not found: {self.path}"}})

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        if not (path.endswith("/v1/chat/completions") or path.endswith("/chat/completions")):
            _write_json(self, 404, {"error": {"message": f"not found: {self.path}"}})
            return

        req = _read_json(self)
        stream = bool(req.get("stream", False))
        model = req.get("model", "dummy")

        # If the client supports tools (OpenHands), return a finish tool call so it exits cleanly.
        if _is_openhands(req):
            if stream:
                # Best-effort streaming tool call. (Some clients only accept tool calls non-streaming,
                # but OpenHands usually works fine either way.)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

                # One chunk with the tool_call, then finish_reason=tool_calls, then [DONE]
                _write_sse(
                    self,
                    {
                        "id": "chatcmpl_fake",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call_finish_1",
                                            "type": "function",
                                            "function": {
                                                "name": "finish",
                                                "arguments": json.dumps({"message": FINISH_MESSAGE}, ensure_ascii=False),
                                            },
                                        }
                                    ],
                                },
                                "finish_reason": None,
                            }
                        ],
                    },
                )
                _write_sse(
                    self,
                    {
                        "id": "chatcmpl_fake",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                    },
                )
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                return

            _write_json(
                self,
                200,
                {
                    "id": "chatcmpl_fake",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [_build_finish_tool_call()],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
            return

        # Default behavior for non-tool clients (e.g., explain_AS).
        content = DEFAULT_REPLY

        if not stream:
            _write_json(
                self,
                200,
                {
                    "id": "chatcmpl_fake",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
            return

        # Minimal SSE streaming response for non-tool clients
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        _write_sse(
            self,
            {
                "id": "chatcmpl_fake",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}
                ],
            },
        )
        _write_sse(
            self,
            {
                "id": "chatcmpl_fake",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        )
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8012)
    args = ap.parse_args()

    httpd = HTTPServer((args.host, args.port), Handler)
    print(f"Fake LLM listening on http://{args.host}:{args.port} (OpenAI-ish /v1)")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
