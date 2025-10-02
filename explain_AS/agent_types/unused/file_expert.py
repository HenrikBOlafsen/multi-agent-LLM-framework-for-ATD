from agent_setup import AgentBase
from agent_util import clip

FILE_EXPERT_SYSTEM = """You are a File_Expert for a single source file.
Your job:
Read the file content you are given and summarize: purpose, key responsibilities/APIs. Then answer follow-up questions about this file.
Rules:
- Stay factual. if unsure, say so.
- Your output should be human-readable and well explained, not JSON.
"""

class FileExpert(AgentBase):
    def __init__(self, name: str, client):
        super().__init__(name, client, FILE_EXPERT_SYSTEM)

    def summarize(self, file_path: str, file_text: str) -> str:
        self.reset()
        user = f"""File: {file_path}

Please summarize this file for later use by other agents.

=== BEGIN FILE ===
{clip(file_text)}
=== END FILE ===

"""
        return self.ask(user)

    def answer_question(self, file_path: str, file_text: str, question: str) -> str:
        # For follow-ups, include the file again (24B context). Keep it light; model should quote minimally.
        self.reset()
        user = f"""File: {file_path}

Question: {question}

Answer with minimal code quotes and line numbers + one-sentence context per quote.

=== BEGIN FILE ===
{clip(file_text)}
=== END FILE ===
"""
        return self.ask(user)