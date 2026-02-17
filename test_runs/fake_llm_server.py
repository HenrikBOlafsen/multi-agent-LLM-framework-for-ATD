### test_runs/fake_llm_server.py
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse


def _now_unix() -> int:
    return int(time.time())


def _read_json_body(handler: BaseHTTPRequestHandler) -> Any:
    n = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(n) if n > 0 else b""
    if not raw:
        return None
    return json.loads(raw.decode("utf-8", errors="replace"))


def _send_json(handler: BaseHTTPRequestHandler, code: int, obj: Any) -> None:
    payload = json.dumps(obj).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _hard_exit() -> None:
    # Simulate tunnel/port disappearing immediately.
    os._exit(0)


def _is_openhands_request(handler: BaseHTTPRequestHandler, body: Any) -> bool:
    # Prefer header signals (OpenHands uses OpenAI client / LiteLLM)
    ua = (handler.headers.get("User-Agent") or "").lower()
    if "litellm" in ua or "openai" in ua or "openhands" in ua:
        return True

    # Fallback: OpenHands messages often include your instruction block.
    try:
        if isinstance(body, dict) and isinstance(body.get("messages"), list):
            joined = "\n".join(
                str(m.get("content", "")) for m in body["messages"] if isinstance(m, dict)
            )
            if "Please refactor to break this dependency cycle" in joined:
                return True
    except Exception:
        pass

    return False


def _chat_completion(
    *,
    content: str,
    model: str = "dummy",
    finish_reason: str = "stop",
    tool_calls: Optional[list] = None,
) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls

    return {
        "id": "chatcmpl_fake",
        "object": "chat.completion",
        "created": _now_unix(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        },
    }


def _tool_call_execute_bash(command: str, tool_call_id: str = "call_bash_1") -> Dict[str, Any]:
    # OpenHands "execute_bash" tool signature includes command + security_risk in JSON arguments.
    args = {"command": command, "security_risk": "LOW"}
    return {
        "id": tool_call_id,
        "type": "function",
        "function": {
            "name": "execute_bash",
            "arguments": json.dumps(args),
        },
    }


def _tool_call_finish(final_thought: str, tool_call_id: str = "call_finish_1") -> Dict[str, Any]:
    # OpenHands exposes a "finish" tool.
    args = {"final_thought": final_thought, "outputs": {}}
    return {
        "id": tool_call_id,
        "type": "function",
        "function": {
            "name": "finish",
            "arguments": json.dumps(args),
        },
    }


@dataclass
class ServerState:
    # exit-after counters (-1 means disabled)
    exit_after_any_chat: int
    exit_after_explain_chat: int
    exit_after_openhands_chat: int

    # OpenHands behavior:
    # - if True: each OpenHands response includes a finish tool call (1 LLM call per repo)
    # - if False: OpenHands response does NOT include finish, so OpenHands will call LLM again
    openhands_finish_tool: bool

    # counts of SERVED chat responses
    served_any_chat: int = 0
    served_explain_chat: int = 0
    served_openhands_chat: int = 0

    def maybe_exit_before_serving(self, kind: str) -> None:
        """
        Exit BEFORE serving the next request once the served_* count
        has reached the configured threshold.

        Semantics:
          - N == 0 => exit on the first relevant chat request (before serving any)
          - N == 1 => allow 1 successful response, then exit on the next request
          - N < 0  => disabled
        """
        if self.exit_after_any_chat >= 0 and self.served_any_chat >= self.exit_after_any_chat:
            _hard_exit()

        if kind == "explain":
            if (
                self.exit_after_explain_chat >= 0
                and self.served_explain_chat >= self.exit_after_explain_chat
            ):
                _hard_exit()

        if kind == "openhands":
            if (
                self.exit_after_openhands_chat >= 0
                and self.served_openhands_chat >= self.exit_after_openhands_chat
            ):
                _hard_exit()

    def mark_served(self, kind: str) -> None:
        self.served_any_chat += 1
        if kind == "explain":
            self.served_explain_chat += 1
        elif kind == "openhands":
            self.served_openhands_chat += 1


STATE: Optional[ServerState] = None


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-llm/1.0"

    def log_message(self, fmt: str, *args) -> None:
        # Keep logs readable in CI
        sys.stderr.write(
            "%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args)
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/v1/models":
            _send_json(
                self,
                200,
                {
                    "_fake_llm": True,
                    "object": "list",
                    "data": [{"id": "dummy", "object": "model"}],
                },
            )
            return

        _send_json(self, 404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        global STATE
        assert STATE is not None

        parsed = urlparse(self.path)
        if parsed.path != "/v1/chat/completions":
            _send_json(self, 404, {"error": {"message": "not found"}})
            return

        body = _read_json_body(self)
        is_oh = _is_openhands_request(self, body)
        kind = "openhands" if is_oh else "explain"

        # Simulate tunnel drop / port disappearance
        STATE.maybe_exit_before_serving(kind)

        model = "dummy"
        if isinstance(body, dict) and isinstance(body.get("model"), str):
            model = body["model"] or "dummy"

        if kind == "openhands":
            # Always emit the marker-writing tool call on *every* OpenHands request.
            # This avoids "global once-per-process" state that breaks multi-repo runs.
            cmd = (
                "mkdir -p /workspace && "
                "printf '%s\\n' 'ATD smoke test: touched by fake_llm_server.py to force a commit.' "
                ">> '/workspace/ATD_SMOKE_EDIT.txt' && "
                "mkdir -p /workspace && "
                "printf '%s\\n' 'midrun-edit-ok' > '/workspace/_smoke_midrun_edit_marker.txt' && "
                "echo wrote-marker:/workspace/ATD_SMOKE_EDIT.txt wrote-out-marker:/workspace/_smoke_midrun_edit_marker.txt"
            )

            tool_calls = [_tool_call_execute_bash(cmd, tool_call_id="call_bash_1")]

            # If enabled, finish the OpenHands interaction in the same LLM response.
            # This prevents OpenHands from going into its "continue" loop.
            if STATE.openhands_finish_tool:
                tool_calls.append(
                    _tool_call_finish(
                        "Marker written (commit-smoke-test); no refactor performed.",
                        tool_call_id="call_finish_1",
                    )
                )

            resp = _chat_completion(
                content="",
                model=model,
                finish_reason="tool_calls",
                tool_calls=tool_calls,
            )
        else:
            # Explain: short deterministic reply
            resp = _chat_completion(content="(fake-llm) ok", model=model, finish_reason="stop")

        _send_json(self, 200, resp)
        STATE.mark_served(kind)


def main() -> None:
    global STATE

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8012)

    # Exit-after controls (simulate tunnel drop)
    ap.add_argument("--exit_after_any_chat", type=int, default=-1)
    ap.add_argument("--exit_after_explain_chat", type=int, default=-1)
    ap.add_argument("--exit_after_openhands_chat", type=int, default=-1)

    # OpenHands behavior control
    ap.add_argument(
        "--openhands_finish_tool",
        type=int,
        default=1,
        help="If 1, each OpenHands response includes a finish tool call (1 LLM call per repo). "
        "If 0, it does not (OpenHands will call LLM again).",
    )

    args = ap.parse_args()

    STATE = ServerState(
        exit_after_any_chat=int(args.exit_after_any_chat),
        exit_after_explain_chat=int(args.exit_after_explain_chat),
        exit_after_openhands_chat=int(args.exit_after_openhands_chat),
        openhands_finish_tool=bool(int(args.openhands_finish_tool)),
    )

    httpd = ThreadingHTTPServer((args.host, int(args.port)), Handler)
    print(f"[fake_llm] listening on http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
