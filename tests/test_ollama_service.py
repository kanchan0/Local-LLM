from types import SimpleNamespace

import pytest

from app.ollama_service import OllamaService


@pytest.mark.asyncio
async def test_chat_stream_keeps_optional_thinking_enabled(monkeypatch):
    calls = []

    class FakeClient:
        async def chat(self, **kwargs):
            calls.append(kwargs)

            async def responses():
                yield SimpleNamespace(message=SimpleNamespace(content="MODEL_OK"))

            return responses()

    monkeypatch.setattr("app.ollama_service.AsyncClient", lambda host: FakeClient())
    service = OllamaService("http://127.0.0.1:11434", "test-model", True, 8192)
    output = [chunk async for chunk in service.stream_chat([{"role": "user", "content": "hello"}])]

    assert output[0].content == "MODEL_OK"
    assert calls[0]["think"] is True
    assert calls[0]["options"] == {"num_ctx": 8192}


@pytest.mark.asyncio
async def test_chat_stream_discovers_model_context_window(monkeypatch):
    calls = []

    class FakeClient:
        async def show(self, model):
            return SimpleNamespace(modelinfo={"qwen35.context_length": 262144})

        async def chat(self, **kwargs):
            calls.append(kwargs)

            async def responses():
                yield SimpleNamespace(message=SimpleNamespace(content="MODEL_OK"))

            return responses()

    monkeypatch.setattr("app.ollama_service.AsyncClient", lambda host: FakeClient())
    service = OllamaService("http://127.0.0.1:11434", "test-model", True)
    output = [chunk async for chunk in service.stream_chat([{"role": "user", "content": "hello"}])]

    assert output[0].content == "MODEL_OK"
    assert calls[0]["options"] == {"num_ctx": 262144}
