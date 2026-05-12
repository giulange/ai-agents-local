"""
Smoke test: agente Agno con qwen2.5:7b via Ollama locale.
Verifica che l'intera catena (agno -> ollama container -> modello) funzioni.

Esecuzione:
    source agno/scripts/activate.sh
    python agno/tests/test_smoke.py
"""

from agno.agent import Agent
from agno.models.ollama import Ollama

OLLAMA_HOST = "http://localhost:11434"
MODEL_ID = "qwen2.5:7b"
PROMPT = "Dimmi ciao"


def test_smoke():
    agent = Agent(
        model=Ollama(id=MODEL_ID, host=OLLAMA_HOST),
        markdown=False,
    )

    print(f"Modello : {MODEL_ID}")
    print(f"Prompt  : {PROMPT}")
    print("-" * 40)

    response = agent.run(PROMPT)
    content = response.content

    print(f"Risposta: {content}")
    print("-" * 40)

    assert isinstance(content, str) and len(content) > 0, "Risposta vuota o non stringa"
    print("SMOKE TEST PASSATO")


if __name__ == "__main__":
    test_smoke()
