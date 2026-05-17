from anthropic import Anthropic, AsyncAnthropic
from deepeval.models.base_model import DeepEvalBaseLLM
from getpass import getpass
from typing import Tuple
import os
import sys


MODEL_NAME = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")


def get_anthropic_api_key():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return api_key

    if not sys.stdin.isatty():
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY='your-api-key'"
        )

    api_key = getpass("Enter your Anthropic API key: ").strip()
    if not api_key:
        raise SystemExit("No Anthropic API key provided.")
    return api_key


class AnthropicModel(DeepEvalBaseLLM):
    def __init__(self, model: str = MODEL_NAME, api_key: str = None):
        self._model_name = model
        self._api_key = api_key or get_anthropic_api_key()
        super().__init__(model_name=model)

    def load_model(self):
        return Anthropic(api_key=self._api_key)

    def generate(self, prompt: str) -> Tuple[str, float]:
        client = self.load_model()
        response = client.messages.create(
            model=self._model_name,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        return text, 0.0

    async def a_generate(self, prompt: str) -> Tuple[str, float]:
        client = AsyncAnthropic(api_key=self._api_key)
        response = await client.messages.create(
            model=self._model_name,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        return text, 0.0

    def get_model_name(self) -> str:
        return self._model_name


def llm(input, tools):
    client = Anthropic(api_key=get_anthropic_api_key())
    tool_names = ", ".join(tool.name for tool in tools) or "none"

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=512,
        system="You are a concise assistant. Answer the user request.",
        messages=[
            {
                "role": "user",
                "content": f"Input: {input}\nAvailable tool calls: {tool_names}",
            },
        ],
    )
    return "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
