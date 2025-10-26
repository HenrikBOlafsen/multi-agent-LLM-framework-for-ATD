import os
import requests
from dataclasses import dataclass, field
from typing import Dict, List
from agent_util import clip

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

# Tunables via env (all printing is optional/tweakable)
PRINT_WITH_COLORS = os.getenv("PRINT_WITH_COLORS", "1") == "1"
AGENT_REPLY_MAX_CHARS = int(os.getenv("AGENT_REPLY_MAX_CHARS", "200000"))  # usually don't truncate replies
USER_PREVIEW_MAX_CHARS = int(os.getenv("USER_PREVIEW_MAX_CHARS", "300"))   # show tiny preview only
SHOW_USER_PREVIEW = os.getenv("SHOW_USER_PREVIEW", "1") == "1"             # set 0 to hide even previews

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
    if PRINT_WITH_COLORS:
        print(color(text, code))
    else:
        print(text)

# ---------- LLM client ----------
class LLMClient:
    def __init__(self, url: str, api_key: str, model: str, temperature: float = 0.2, max_tokens: int = 16384):
        self.url = url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        r = requests.post(self.url, headers=headers, json=payload, timeout=260)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return content
    

# -------------------------
# Agent base
# -------------------------

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
        if not USE_SYSTEM_PROMPT and self.system_prompt:
            # Emulate a system prompt by inlining it at the top of the user message
            user_text = f"{self.system_prompt}\n\n---------\n\n{user_text}"
        # Avoid dumping file contents: only show a tiny preview.
        if SHOW_USER_PREVIEW:
            preview = truncate_for_console(user_text.strip(), USER_PREVIEW_MAX_CHARS)
            log_line(f"▶ {self.name} sending prompt (chars={len(user_text)}):", Ansi.CYAN if PRINT_WITH_COLORS else None)
            log_line(preview, Ansi.DIM if PRINT_WITH_COLORS else None)
        else:
            log_line(f"▶ {self.name} sending prompt (chars={len(user_text)})", Ansi.CYAN if PRINT_WITH_COLORS else None)

        self.history.append({"role": "user", "content": user_text})
        reply = self.client.chat(self.history).strip()
        reply = clip(reply, 15000)
        self.history.append({"role": "assistant", "content": reply})

        log_line(f"◀ {self.name} reply:", Ansi.GREEN if PRINT_WITH_COLORS else None)
        log_line(truncate_for_console(reply, AGENT_REPLY_MAX_CHARS), Ansi.GREEN if PRINT_WITH_COLORS else None)
        return reply
