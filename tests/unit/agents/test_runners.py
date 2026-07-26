"""Tests for MockRunner and DirectRunner."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from app.runtime.prompt_builder import Message, RequestSpec
from app.runtime.runners.base import AgentResponse, ToolCall
from app.runtime.runners.direct_runner import (
    DirectRunner,
    NonTransientError,
    TransientError,
)
from app.runtime.runners.mock_runner import MockRunner

# ── StubAgent satisfying the RunnerAgent protocol ──────────────────────────


@dataclass
class StubAgent:
    id: str
    model: str | None = None


def _spec(text: str, model: str | None = None) -> RequestSpec:
    """Wrap a plain prompt string as a single-user-message RequestSpec."""
    return RequestSpec(system="", messages=[Message(role="user", content=text)], model=model)


# ── MockRunner ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_runner_returns_deterministic_response() -> None:
    runner = MockRunner()
    agent = StubAgent(id="test-agent")
    r1 = await runner.run(agent, _spec("hello world"))
    r2 = await runner.run(agent, _spec("hello world"))
    assert r1 == r2
    assert r1.text.startswith("[mock:test-agent] Response for prompt ")
    assert r1.tool_calls == []
    assert r1.usage.prompt_tokens == len("hello world") // 4
    assert r1.usage.completion_tokens == 100


@pytest.mark.asyncio
async def test_mock_runner_different_input_different_output() -> None:
    runner = MockRunner()
    agent = StubAgent(id="test-agent")
    r1 = await runner.run(agent, _spec("prompt A"))
    r2 = await runner.run(agent, _spec("prompt B"))
    assert r1.text != r2.text


@pytest.mark.asyncio
async def test_mock_runner_different_agent_different_output() -> None:
    runner = MockRunner()
    r1 = await runner.run(StubAgent(id="agent-1"), _spec("same prompt"))
    r2 = await runner.run(StubAgent(id="agent-2"), _spec("same prompt"))
    assert r1.text != r2.text
    assert "[mock:agent-1]" in r1.text
    assert "[mock:agent-2]" in r2.text


def test_mock_runner_does_not_import_httpx() -> None:
    """MockRunner must not pull in httpx — it makes no network calls."""
    # Importing the module should not transitively import httpx.
    import app.runtime.runners.mock_runner as mod

    assert not hasattr(mod, "httpx")
    # And the runner class source has no httpx references.
    src = inspect.getsource(mod.MockRunner)
    assert "httpx" not in src


@pytest.mark.asyncio
async def test_mock_runner_is_agent_agnostic_protocol() -> None:
    """MockRunner accepts any object with `id` and `model` (RunnerAgent protocol)."""

    class CustomAgent:
        def __init__(self, id: str) -> None:
            self.id = id
            self.model: str | None = None

    runner = MockRunner()
    r = await runner.run(CustomAgent("custom"), _spec("p"))
    assert isinstance(r, AgentResponse)
    assert "[mock:custom]" in r.text


# ── DirectRunner: request format ─────────────────────────────────────────────


def _make_handler(payload: dict[str, Any], status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def _openai_response(
    content: str = "hi",
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 5,
    completion_tokens: int = 3,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-x",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


@pytest.mark.asyncio
async def test_direct_runner_builds_valid_openai_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "sk-secret")
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_openai_response("Hello!"))

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "gpt-test",
            "api_key_env": "TEST_API_KEY",
            "base_url_env": "TEST_BASE_URL",
        },
        runtime_policy={"timeout_seconds": 10, "max_retries": 0},
    )

    # Monkeypatch the _post_once to use a MockTransport client.
    original_post = runner._post_once

    async def patched_post(url: str, headers: dict[str, str], body: dict[str, object]) -> AgentResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 200:
            return runner._encoder.decode(resp.json())
        raise RuntimeError(f"unexpected status {resp.status_code}")

    runner._post_once = patched_post  # type: ignore[method-assign]
    try:
        result = await runner.run(StubAgent(id="a1", model=None), _spec("Hello"))
    finally:
        runner._post_once = original_post  # type: ignore[method-assign]

    # Request was well-formed OpenAI chat completions format.
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer sk-secret"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["body"]["model"] == "gpt-test"
    assert captured["body"]["messages"] == [{"role": "user", "content": "Hello"}]

    # Response parsed correctly.
    assert result.text == "Hello!"
    assert result.usage.prompt_tokens == 5
    assert result.usage.completion_tokens == 3
    assert result.tool_calls == []


@pytest.mark.asyncio
async def test_direct_runner_agent_model_overrides_runner_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "sk-secret")
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_openai_response("ok"))

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "default-model",
            "api_key_env": "TEST_API_KEY",
            "base_url_env": "TEST_BASE_URL",
        },
        runtime_policy={"timeout_seconds": 10, "max_retries": 0},
    )

    async def patched_post(url: str, headers: dict[str, str], body: dict[str, object]) -> AgentResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10) as client:
            resp = await client.post(url, json=body, headers=headers)
        return runner._encoder.decode(resp.json())

    runner._post_once = patched_post  # type: ignore[method-assign]
    await runner.run(StubAgent(id="a1"), _spec("p", model="agent-specific-model"))

    assert captured["body"]["model"] == "agent-specific-model"


@pytest.mark.asyncio
async def test_direct_runner_parses_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "sk-secret")
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")

    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "read",
                "arguments": '{"resource": "state"}',
            },
        }
    ]
    payload = _openai_response(content="", tool_calls=tool_calls)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "m",
            "api_key_env": "TEST_API_KEY",
            "base_url_env": "TEST_BASE_URL",
        },
        runtime_policy={"timeout_seconds": 10, "max_retries": 0},
    )

    async def patched_post(url: str, headers: dict[str, str], body: dict[str, object]) -> AgentResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10) as client:
            resp = await client.post(url, json=body, headers=headers)
        return runner._encoder.decode(resp.json())

    runner._post_once = patched_post  # type: ignore[method-assign]
    result = await runner.run(StubAgent(id="a1"), _spec("p"))

    assert len(result.tool_calls) == 1
    assert isinstance(result.tool_calls[0], ToolCall)
    assert result.tool_calls[0].name == "read"
    # Arguments arrive as a JSON string → parsed into a dict; id carried.
    assert result.tool_calls[0].args == {"resource": "state"}
    assert result.tool_calls[0].id == "call_1"


# ── DirectRunner: missing env var ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_direct_runner_missing_api_key_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_KEY", raising=False)
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "m",
            "api_key_env": "MISSING_KEY",
            "base_url_env": "TEST_BASE_URL",
        },
        runtime_policy={"timeout_seconds": 10, "max_retries": 0},
    )

    with pytest.raises(RuntimeError, match="MISSING_KEY"):
        await runner.run(StubAgent(id="a1"), _spec("p"))


@pytest.mark.asyncio
async def test_direct_runner_empty_api_key_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMPTY_KEY", "")
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "m",
            "api_key_env": "EMPTY_KEY",
            "base_url_env": "TEST_BASE_URL",
        },
        runtime_policy={"timeout_seconds": 10, "max_retries": 0},
    )

    with pytest.raises(RuntimeError, match="EMPTY_KEY"):
        await runner.run(StubAgent(id="a1"), _spec("p"))


@pytest.mark.asyncio
async def test_direct_runner_missing_base_url_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "sk-secret")
    monkeypatch.delenv("MISSING_URL", raising=False)

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "m",
            "api_key_env": "TEST_API_KEY",
            "base_url_env": "MISSING_URL",
        },
        runtime_policy={"timeout_seconds": 10, "max_retries": 0},
    )

    with pytest.raises(RuntimeError, match="MISSING_URL"):
        await runner.run(StubAgent(id="a1"), _spec("p"))


# ── DirectRunner: retry on 500, raise on 400 ────────────────────────────────


@pytest.mark.asyncio
async def test_direct_runner_retries_on_500_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "sk-secret")
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")

    statuses: list[int] = [500, 500, 200]
    payload = _openai_response("recovered")
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        status = statuses[min(call_count, len(statuses) - 1)]
        call_count += 1
        if status == 200:
            return httpx.Response(200, json=payload)
        return httpx.Response(status, text="server error")

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "m",
            "api_key_env": "TEST_API_KEY",
            "base_url_env": "TEST_BASE_URL",
        },
        runtime_policy={
            "timeout_seconds": 10,
            "max_retries": 3,
            "backoff_seconds": [0.0, 0.0, 0.0],
        },
    )

    async def patched_post(url: str, headers: dict[str, str], body: dict[str, object]) -> AgentResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 200:
            return runner._encoder.decode(resp.json())
        from app.runtime.runners.direct_runner import _is_transient_status

        if _is_transient_status(resp.status_code):
            raise TransientError(f"HTTP {resp.status_code}")
        raise NonTransientError(f"HTTP {resp.status_code}")

    runner._post_once = patched_post  # type: ignore[method-assign]
    result = await runner.run(StubAgent(id="a1"), _spec("p"))

    assert result.text == "recovered"
    assert call_count == 3


@pytest.mark.asyncio
async def test_direct_runner_raises_on_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "sk-secret")
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, text="bad request")

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "m",
            "api_key_env": "TEST_API_KEY",
            "base_url_env": "TEST_BASE_URL",
        },
        runtime_policy={
            "timeout_seconds": 10,
            "max_retries": 3,
            "backoff_seconds": [0.0, 0.0, 0.0],
        },
    )

    async def patched_post(url: str, headers: dict[str, str], body: dict[str, object]) -> AgentResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10) as client:
            resp = await client.post(url, json=body, headers=headers)
        from app.runtime.runners.direct_runner import _is_transient_status

        if _is_transient_status(resp.status_code):
            raise TransientError(f"HTTP {resp.status_code}")
        raise NonTransientError(f"HTTP {resp.status_code}")

    runner._post_once = patched_post  # type: ignore[method-assign]
    with pytest.raises(NonTransientError, match="400"):
        await runner.run(StubAgent(id="a1"), _spec("p"))

    # 400 is non-transient → no retry.
    assert call_count == 1


@pytest.mark.asyncio
async def test_direct_runner_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "sk-secret")
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")

    statuses: list[int] = [429, 200]
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        status = statuses[min(call_count, len(statuses) - 1)]
        call_count += 1
        if status == 200:
            return httpx.Response(200, json=_openai_response("ok"))
        return httpx.Response(429, text="rate limited")

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "m",
            "api_key_env": "TEST_API_KEY",
            "base_url_env": "TEST_BASE_URL",
        },
        runtime_policy={
            "timeout_seconds": 10,
            "max_retries": 2,
            "backoff_seconds": [0.0, 0.0],
        },
    )

    async def patched_post(url: str, headers: dict[str, str], body: dict[str, object]) -> AgentResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 200:
            return runner._encoder.decode(resp.json())
        from app.runtime.runners.direct_runner import _is_transient_status

        if _is_transient_status(resp.status_code):
            raise TransientError(f"HTTP {resp.status_code}")
        raise NonTransientError(f"HTTP {resp.status_code}")

    runner._post_once = patched_post  # type: ignore[method-assign]
    result = await runner.run(StubAgent(id="a1"), _spec("p"))
    assert result.text == "ok"
    assert call_count == 2


class _TimeoutFirstTransport(httpx.AsyncBaseTransport):
    """Async transport that raises a timeout on the first call, then succeeds."""

    def __init__(self) -> None:
        self.call_count = 0
        self._success_payload = _openai_response("recovered")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        if self.call_count == 1:
            raise httpx.TimeoutException("simulated timeout")
        return httpx.Response(200, json=self._success_payload)


@pytest.mark.asyncio
async def test_direct_runner_retries_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "sk-secret")
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")

    transport = _TimeoutFirstTransport()

    runner = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": "m",
            "api_key_env": "TEST_API_KEY",
            "base_url_env": "TEST_BASE_URL",
        },
        runtime_policy={
            "timeout_seconds": 10,
            "max_retries": 2,
            "backoff_seconds": [0.0, 0.0],
        },
    )

    async def patched_post(url: str, headers: dict[str, str], body: dict[str, object]) -> AgentResponse:
        try:
            async with httpx.AsyncClient(transport=transport, timeout=10) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise TransientError(f"simulated timeout: {exc}") from exc
        if resp.status_code == 200:
            return runner._encoder.decode(resp.json())
        raise RuntimeError(f"unexpected status {resp.status_code}")

    runner._post_once = patched_post  # type: ignore[method-assign]
    result = await runner.run(StubAgent(id="a1"), _spec("p"))
    assert result.text == "recovered"
    assert transport.call_count == 2


# ── DirectRunner: construction validation ────────────────────────────────────


def test_direct_runner_unsupported_provider_raises() -> None:
    with pytest.raises(ValueError, match="unsupported provider"):
        DirectRunner(
            model_config={"provider": "anthropic", "model": "m", "api_key_env": "K", "base_url_env": "U"},
            runtime_policy={},
        )


def test_direct_runner_missing_model_raises() -> None:
    with pytest.raises(ValueError, match="missing a 'model'"):
        DirectRunner(
            model_config={"provider": "openai_compatible", "api_key_env": "K", "base_url_env": "U"},
            runtime_policy={},
        )


def test_direct_runner_missing_api_key_env_name_raises() -> None:
    with pytest.raises(ValueError, match="api_key_env"):
        DirectRunner(
            model_config={"provider": "openai_compatible", "model": "m", "base_url_env": "U"},
            runtime_policy={},
        )


def test_direct_runner_missing_base_url_env_name_raises() -> None:
    with pytest.raises(ValueError, match="base_url_env"):
        DirectRunner(
            model_config={"provider": "openai_compatible", "model": "m", "api_key_env": "K"},
            runtime_policy={},
        )
