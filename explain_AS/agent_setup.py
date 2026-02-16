import os
import json
import time
import math
import requests
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from agent_util import clip_middle, clip

# When false, the system prompt is merged with the user prompt and just given to the LLM as a user prompt
USE_SYSTEM_PROMPT = False


# ---------- Console helpers ----------
class Ansi:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    GRAY    = "\033[90m"

def color(text: str, code: str) -> str:
    return f"{code}{text}{Ansi.RESET}"

def truncate_for_console(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n{color('... [snip for console] ...', Ansi.GRAY)}\n{tail}"

PRINT_WITH_COLORS = os.getenv("PRINT_WITH_COLORS", "1") == "1"
AGENT_REPLY_MAX_CHARS = int(os.getenv("AGENT_REPLY_MAX_CHARS", "200000"))
USER_PREVIEW_MAX_CHARS = int(os.getenv("USER_PREVIEW_MAX_CHARS", "300"))
SHOW_USER_PREVIEW = os.getenv("SHOW_USER_PREVIEW", "1") == "1"

def _trace_path() -> str:
    # IMPORTANT: read dynamically (env may be set after import)
    return (os.getenv("ATD_TRACE_PATH", "") or "").strip()

def _append_trace_event(event: Dict) -> None:
    path = _trace_path()
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        # Tracing should never break experiments
        pass

def _utc_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def log_section(title: str, tone: str = "blue"):
    tone_map = {
        "blue": Ansi.BLUE, "green": Ansi.GREEN, "yellow": Ansi.YELLOW,
        "red": Ansi.RED, "magenta": Ansi.MAGENTA, "cyan": Ansi.CYAN
    }
    code = tone_map.get(tone, Ansi.BLUE)
    if PRINT_WITH_COLORS:
        print(color(f"\n=== {title} ===", code))
    else:
        print(f"\n=== {title} ===")

def log_line(text: str, code: str = Ansi.GRAY):
    if PRINT_WITH_COLORS and code is not None:
        print(color(text, code))
    else:
        print(text)


# ---------- Context budget helpers ----------
def _estimate_tokens_from_chars(n_chars: int) -> int:
    # Conservative-ish rule of thumb: ~3 chars per token in English/code mixes.
    return int(math.ceil(n_chars / 3.0))

def _estimate_message_tokens(messages: List[Dict[str, str]]) -> int:
    # Rough estimate: sum content tokens + small overhead per message.
    overhead_per_msg = 8
    total_chars = 0
    for m in messages:
        total_chars += len(str(m.get("role", ""))) + len(str(m.get("content", "")))
    return _estimate_tokens_from_chars(total_chars) + overhead_per_msg * len(messages)

def _trim_user_text_to_fit(
    *,
    system_prompt: str,
    user_text: str,
    use_system_prompt: bool,
    context_length: int,
    max_completion_tokens: int,
    safety_tokens: int = 512,
) -> str:
    """
    Ensure prompt fits: estimated_prompt_tokens + max_completion_tokens + safety <= context_length.
    If not, clip the user_text in the middle.
    """
    if context_length <= 0:
        raise SystemExit("LLM_CONTEXT_LENGTH must be a positive integer.")

    # Build messages as they will be sent
    if use_system_prompt and system_prompt:
        msgs = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
    else:
        # system prompt is merged into user text by AgentBase.ask
        msgs = [{"role": "user", "content": user_text}]

    need_budget = max_completion_tokens + safety_tokens
    prompt_tokens = _estimate_message_tokens(msgs)

    if prompt_tokens + need_budget <= context_length:
        return user_text

    # How many prompt tokens may we spend?
    allowed_prompt_tokens = max(1, context_length - need_budget)

    # Convert allowed tokens -> allowed chars (inverse of estimate)
    allowed_prompt_chars = allowed_prompt_tokens * 4

    # Estimate how many chars are "non-user-content overhead" inside prompt
    # We’ll just clip user_text to fit inside allowed_prompt_chars total content.
    # (Simple and effective; we already re-estimate after clip below.)
    clipped = clip_middle(user_text, max_chars=max(1, allowed_prompt_chars))

    # Final sanity: if still too big, clip harder.
    for _ in range(3):
        if use_system_prompt and system_prompt:
            msgs2 = [{"role": "system", "content": system_prompt}, {"role": "user", "content": clipped}]
        else:
            msgs2 = [{"role": "user", "content": clipped}]
        if _estimate_message_tokens(msgs2) + need_budget <= context_length:
            return clipped
        clipped = clip_middle(clipped, max_chars=max(1, int(len(clipped) * 0.8)))

    return clipped


# ---------- LLM client ----------
class LLMClient:
    def __init__(
        self,
        url: str,
        api_key: str,
        model: str,
        *,
        context_length: int,
        temperature: float = 0.2,
        max_tokens: int = 16384,
    ):
        self.url = url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.context_length = int(context_length)

        self._acc_prompt_tokens: int = 0
        self._acc_completion_tokens: int = 0
        self._acc_total_tokens: int = 0
        self._last_usage: Optional[Dict[str, int]] = None

    def get_accumulated_usage(self) -> Dict[str, int]:
        return {
            "prompt_tokens": int(self._acc_prompt_tokens),
            "completion_tokens": int(self._acc_completion_tokens),
            "total_tokens": int(self._acc_total_tokens),
        }

    def get_last_usage(self) -> Optional[Dict[str, int]]:
        return self._last_usage

    def chat(self, messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": int(self.max_tokens),
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        r = requests.post(self.url, headers=headers, json=payload, timeout=300)
        r.raise_for_status()
        data = r.json()

        usage = data.get("usage") if isinstance(data, dict) else None
        if isinstance(usage, dict):
            p = usage.get("prompt_tokens")
            c = usage.get("completion_tokens")
            t = usage.get("total_tokens")
            if isinstance(p, int) and isinstance(c, int):
                if not isinstance(t, int):
                    t = p + c
                self._acc_prompt_tokens += p
                self._acc_completion_tokens += c
                self._acc_total_tokens += t
                self._last_usage = {"prompt_tokens": p, "completion_tokens": c, "total_tokens": t}

        content = data["choices"][0]["message"]["content"]
        return content


@dataclass
class AgentBase:
    name: str
    client: LLMClient
    system_prompt: str
    history: List[Dict[str, str]] = field(default_factory=list)

    def reset(self):
        if USE_SYSTEM_PROMPT and self.system_prompt:
            self.history = [{"role": "system", "content": self.system_prompt}]
        else:
            self.history = []

    def ask(self, user_text: str) -> str:
        original_user_text = user_text

        if not USE_SYSTEM_PROMPT and self.system_prompt:
            user_text = f"{self.system_prompt}\n\n---------\n\n{user_text}"

        # Enforce context budget BEFORE sending
        user_text = _trim_user_text_to_fit(
            system_prompt=self.system_prompt,
            user_text=user_text,
            use_system_prompt=bool(USE_SYSTEM_PROMPT),
            context_length=int(self.client.context_length),
            max_completion_tokens=int(self.client.max_tokens),
            safety_tokens=512,
        )

        if SHOW_USER_PREVIEW:
            preview = truncate_for_console(user_text.strip(), USER_PREVIEW_MAX_CHARS)
            log_line(f"▶ {self.name} sending prompt (chars={len(user_text)}):", Ansi.CYAN if PRINT_WITH_COLORS else None)
            log_line(preview, Ansi.DIM if PRINT_WITH_COLORS else None)
        else:
            log_line(f"▶ {self.name} sending prompt (chars={len(user_text)})", Ansi.CYAN if PRINT_WITH_COLORS else None)

        _append_trace_event({
            "ts_utc": _utc_ts(),
            "agent": self.name,
            "event": "prompt",
            "use_system_prompt": bool(USE_SYSTEM_PROMPT),
            "prompt": user_text,
            "prompt_original": original_user_text if original_user_text != user_text else None,
        })

        self.history.append({"role": "user", "content": user_text})
        reply = self.client.chat(self.history).strip()
        reply = clip(reply, 15000)
        self.history.append({"role": "assistant", "content": reply})

        _append_trace_event({
            "ts_utc": _utc_ts(),
            "agent": self.name,
            "event": "reply",
            "reply": reply,
        })

        log_line(f"◀ {self.name} reply:", Ansi.GREEN if PRINT_WITH_COLORS else None)
        log_line(truncate_for_console(reply, AGENT_REPLY_MAX_CHARS), Ansi.GREEN if PRINT_WITH_COLORS else None)
        return reply
