# vllm_proxy.py
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

import requests

LISTEN_HOST = os.environ.get("VLLM_PROXY_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("VLLM_PROXY_LISTEN_PORT", "8013"))

UPSTREAM = os.environ.get("UPSTREAM", "http://host.docker.internal:8012")
LOGDIR = Path(os.environ.get("LOGDIR", "vllm_proxy_logs"))
LOGDIR.mkdir(parents=True, exist_ok=True)

FORCE_STREAM_FALSE = os.environ.get("VLLM_PROXY_FORCE_STREAM_FALSE", "1").lower() not in ("0", "false", "no", "off")
UPSTREAM_TIMEOUT_SEC = int(os.environ.get("VLLM_PROXY_TIMEOUT_SEC", "300"))

def _now_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}_{os.getpid()}_{int(time.time()*1000)}"

def _safe_json_load(b: bytes) -> Optional[Any]:
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        return None

def _redact_headers(h: Dict[str, str]) -> Dict[str, str]:
    out = dict(h)
    for k in list(out.keys()):
        if k.lower() == "authorization":
            out[k] = "Bearer ***REDACTED***"
    return out

def _rewrite_model(payload: Any) -> Any:
    # OpenHands/LiteLLM often uses "openai/<model>".
    # vLLM expects the raw model id, e.g. "Qwen3-Coder-30B-A3B-Instruct".
    if isinstance(payload, dict):
        m = payload.get("model")
        if isinstance(m, str) and m.startswith("openai/"):
            payload["model"] = m[len("openai/"):]
    return payload

class Handler(BaseHTTPRequestHandler):
    def _forward(self, method: str) -> None:
        rid = _now_id()
        upstream_url = f"{UPSTREAM}{self.path}"

        # Forward all headers except Host
        headers = {k: v for k, v in self.headers.items() if k.lower() != "host"}

        body = b""
        if method in ("POST", "PUT", "PATCH"):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b""

        json_payload = _safe_json_load(body) if body else None
        if isinstance(json_payload, dict):
            if FORCE_STREAM_FALSE:
                json_payload["stream"] = False
            json_payload = _rewrite_model(json_payload)

        (LOGDIR / f"{rid}_req.json").write_text(
            json.dumps(
                {
                    "id": rid,
                    "method": method,
                    "path": self.path,
                    "upstream_url": upstream_url,
                    "headers": _redact_headers(headers),
                    "json": json_payload,
                    "raw_len": len(body),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        try:
            r = requests.request(
                method=method,
                url=upstream_url,
                headers=headers,
                json=json_payload if json_payload is not None else None,
                data=None if json_payload is not None else (body if body else None),
                timeout=UPSTREAM_TIMEOUT_SEC,
            )
        except Exception as e:
            err = {"error": "proxy_upstream_connection_failed", "detail": str(e), "upstream_url": upstream_url}
            (LOGDIR / f"{rid}_resp.json").write_text(json.dumps(err, indent=2), encoding="utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(err).encode("utf-8"))
            return

        try:
            resp_obj = r.json()
        except Exception:
            resp_obj = {"_raw_text": r.text}

        (LOGDIR / f"{rid}_resp.json").write_text(
            json.dumps({"status_code": r.status_code, "body": resp_obj}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        self.send_response(r.status_code)
        for k, v in r.headers.items():
            if k.lower() in ("content-length", "transfer-encoding", "connection", "content-encoding"):
                continue
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(r.content)

    def do_GET(self): self._forward("GET")
    def do_POST(self): self._forward("POST")
    def do_PUT(self): self._forward("PUT")
    def do_PATCH(self): self._forward("PATCH")
    def do_DELETE(self): self._forward("DELETE")

    def log_message(self, fmt, *args):
        return

if __name__ == "__main__":
    print(f"Proxy listening on http://{LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM}")
    HTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()