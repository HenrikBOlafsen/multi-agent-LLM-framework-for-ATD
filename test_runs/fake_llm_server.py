#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

DEFAULT_REPLY = (
    "You are a refactoring assistant.\n"
    "For this smoke test: do NOT modify any files.\n"
    "Reply with a short confirmation that you made no changes.\n"
)

# IMPORTANT: In smoke-test mode we *do* write a marker file so the pipeline sees a commit.
FINISH_MESSAGE = "Marker written (commit-smoke-test); no refactor performed."

# Marker edit for commit-smoke-test
COMMIT_SMOKE_FILE_PATH = "/workspace/ATD_SMOKE_EDIT.txt"
COMMIT_SMOKE_LINE = "ATD smoke test: touched by fake_llm_server.py to force a commit."

# In-memory per-task state:
# key -> number of OpenHands tool-call responses we have served so far
_OPENHANDS_STEP_BY_KEY: Dict[str, int] = {}


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
    tools = req.get("tools")
    if isinstance(tools, list) and tools:
        return True

    funcs = req.get("functions")
    if isinstance(funcs, list) and funcs:
        return True

    msgs = req.get("messages")
    if isinstance(msgs, list):
        for m in msgs:
            if not isinstance(m, dict):
                continue
            c = m.get("content")
            if isinstance(c, str) and ("You are OpenHands agent" in c or "OpenHands agent" in c):
                return True

    return False


def _first_user_message_text(req: Dict[str, Any]) -> str:
    msgs = req.get("messages")
    if not isinstance(msgs, list):
        return ""
    for m in msgs:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            try:
                return json.dumps(c, ensure_ascii=False)
            except Exception:
                return ""
    return ""


def _openhands_session_key(req: Dict[str, Any]) -> str:
    txt = _first_user_message_text(req).strip()
    if not txt:
        try:
            txt = json.dumps(req, sort_keys=True, ensure_ascii=False)
        except Exception:
            txt = str(time.time())
    h = hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]
    return f"oh_{h}"


def _build_finish_tool_call() -> Dict[str, Any]:
    return {
        "id": "call_finish_1",
        "type": "function",
        "function": {
            "name": "finish",
            "arguments": json.dumps({"message": FINISH_MESSAGE}, ensure_ascii=False),
        },
    }


def _build_execute_bash_append_marker_tool_call() -> Dict[str, Any]:
    """
    Smoke-test marker write.

    IMPORTANT: Keep quoting simple and robust:
    - No nested sh -lc "..."
    - Use single-quoted literal message
    - Chain with && so failures propagate
    """
    # Note: message has no single quotes; if you ever add them, you'll need escaping.
    cmd = (
        "mkdir -p /workspace && "
        f"printf '%s\\n' '{COMMIT_SMOKE_LINE}' >> '{COMMIT_SMOKE_FILE_PATH}' && "
        f"echo wrote-marker:{COMMIT_SMOKE_FILE_PATH}"
    )
    args = {"command": cmd, "security_risk": "LOW"}
    return {
        "id": "call_bash_1",
        "type": "function",
        "function": {"name": "execute_bash", "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _write_sse(handler: BaseHTTPRequestHandler, obj: Dict[str, Any]) -> None:
    line = f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")
    handler.wfile.write(line)
    handler.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-llm/0.7"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            _write_json(self, 200, {"object": "list", "data": [{"id": "dummy", "object": "model"}]})
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

        if _is_openhands(req):
            key = _openhands_session_key(req)
            step = int(_OPENHANDS_STEP_BY_KEY.get(key, 0))

            if step <= 0:
                tool_call = _build_execute_bash_append_marker_tool_call()
                _OPENHANDS_STEP_BY_KEY[key] = 1
            else:
                tool_call = _build_finish_tool_call()
                _OPENHANDS_STEP_BY_KEY[key] = step + 1

            if stream:
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
                            {
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": tool_call["id"],
                                            "type": "function",
                                            "function": {
                                                "name": tool_call["function"]["name"],
                                                "arguments": tool_call["function"]["arguments"],
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
                            "message": {"role": "assistant", "content": "", "tool_calls": [tool_call]},
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
            return

        # Non-tool clients
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
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
            return

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
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}],
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
