from agent_setup import AgentBase
DUMMY_AGENT_SYSTEM = ""

class DummyAgent(AgentBase):
    def __init__(self, name: str, client):
        super().__init__(name, client, DUMMY_AGENT_SYSTEM)

    def ask_direct(self, prompt: str) -> str:
        self.reset()
        return self.ask(prompt)
