from agent_setup import LLMClient, log_section
from agent_types.dummy_agent import DummyAgent


prompt_file_path = "../test_set/test.txt"

if __name__ == "__main__":
    # Adjust these to your environment
    #LLM_URL = "http://localhost:1234/v1/chat/completions"
    #LLM_URL = "http://host.docker.internal:1234/v1/chat/completions" # LM studio (when running in docker)
    LLM_URL = "http://host.docker.internal:8000/v1/chat/completions" # UiO fox cluster (when running in docker)

    #API_KEY = "lm-studio"  # LM Studio default
    API_KEY = "token"  # LM Studio default
    MODEL = "Qwen/Qwen3-Coder-30B-A3B-Instruct" # "mistralai/Devstral-Small-2507" # "mistralai/magistral-small-2509" # "meta-llama/Llama-3.1-70B-Instruct"  # "google/gemma-3-12b" / your 24B devstral id

    
    client = LLMClient(LLM_URL, API_KEY, MODEL, temperature=0.1, max_tokens=16384)
    
    agent = DummyAgent("Dummy_Agent", client)

    file_content = "test"

    try:
        with open(prompt_file_path, 'r', encoding='utf-8') as file:
            file_content = file.read()
    except FileNotFoundError:
        print(f"Error: The file '{prompt_file_path}' was not found.")
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")

    agent.ask_direct(file_content)