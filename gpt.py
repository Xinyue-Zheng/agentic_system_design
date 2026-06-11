import httpx
from typing import Any, Iterator, List, Optional

from openai import OpenAI
from pydantic import PrivateAttr

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


def _to_openai_messages(messages: List[BaseMessage]) -> List[dict]:
    role_map = {"human": "user", "ai": "assistant",
                "system": "system", "tool": "tool", "function": "function"}
    out = []
    for m in messages:
        msg = {"role": role_map.get(m.type, m.type), "content": m.content}
        tcid = getattr(m, "tool_call_id", None)
        if tcid:
            msg["tool_call_id"] = tcid
        out.append(msg)
    return out


class OpenAIClientChatModel(BaseChatModel):
    """用原生 openai client 封装，发出去的参数和你手写的 kwargs 完全一致。"""

    model: str
    base_url: str
    api_key: str
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 2048

    _client: OpenAI = PrivateAttr(default=None)

    def __init__(self, http_client: Optional[httpx.Client] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            http_client=http_client,
        )

    @property
    def _llm_type(self) -> str:
        return "openai-client-chat-model"

    def _kwargs(self, messages, stream, stop=None, **extra):
        kw = {
            "model": self.model,
            "messages": _to_openai_messages(messages),
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stream": stream,
            **extra,
        }
        if stop:
            kw["stop"] = stop
        return kw

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        resp = self._client.chat.completions.create(
            **self._kwargs(messages, stream=False, stop=stop, **kwargs)
        )
        choice = resp.choices[0]
        msg = AIMessage(
            content=choice.message.content or "",
            response_metadata={"finish_reason": choice.finish_reason, "model": resp.model},
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for chunk in self._client.chat.completions.create(
            **self._kwargs(messages, stream=True, stop=stop, **kwargs)
        ):
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content or ""
            if content:
                gen = ChatGenerationChunk(message=AIMessageChunk(content=content))
                if run_manager:
                    run_manager.on_llm_new_token(content, chunk=gen)
                yield gen