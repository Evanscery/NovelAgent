"""Direct runner — calls an OpenAI-compatible chat completions endpoint.

This is the "real LLM" runner. It reads model configuration (provider,
model name, API key, base URL) and a runtime policy (timeout, retries,
backoff) from dicts supplied at construction time, then issues an async
HTTP POST to ``{base_url}/chat/completions`` via :mod:`httpx`.

Only the ``openai_compatible`` provider is supported for now; the runner
is structured so additional providers can be added without changing the
public interface.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import httpx

from .base import AgentResponse, AgentRunner, RunnerAgent, TokenUsage, ToolCall


class TransientError(Exception):
    """An error that may succeed on retry (5xx, 429, timeout, network)."""


class NonTransientError(Exception):
    """An error that will not succeed on retry (4xx except 429)."""


def _is_transient_status(status_code: int) -> bool:
    """Return True for status codes that warrant a retry."""
    if status_code == 429:  # rate limit — retry with backoff
        return True
    return status_code >= 500


def _as_float(value: object, default: float) -> float:
    """Coerce a policy value to float, falling back to ``default``."""
    if isinstance(value, bool | None):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _as_int(value: object, default: int) -> int:
    """Coerce a policy value to int, falling back to ``default``."""
    if isinstance(value, bool | None):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _resolve_env(name: str) -> str:
    """Read an environment variable, raising a clear error if unset/empty."""
    value = os.environ.get(name)
    if not value:
        msg = (
            f"DirectRunner: required environment variable '{name}' is not set or empty. "
            f"Set it in your environment or .env before using the direct runner."
        )
        raise RuntimeError(msg)
    return value


def _parse_tool_calls(raw_tool_calls: list[object]) -> list[ToolCall]:
    """Extract ToolCall objects from an OpenAI-format tool_calls array."""
    parsed: list[ToolCall] = []
    for entry in raw_tool_calls:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        args = function.get("arguments")
        if not isinstance(name, str):
            continue
        if isinstance(args, dict):
            arg_dict: dict[str, object] = dict(args)
        elif isinstance(args, str):
            # OpenAI sends arguments as a JSON string; we keep it as a single
            # field rather than parsing JSON here so the tool dispatcher can
            # decide how to interpret it.
            arg_dict = {"_raw": args}
        else:
            arg_dict = {}
        parsed.append(ToolCall(name=name, args=arg_dict))
    return parsed


def _parse_usage(raw_usage: object) -> TokenUsage:
    """Extract TokenUsage from an OpenAI-format usage object."""
    if not isinstance(raw_usage, dict):
        return TokenUsage(0, 0)
    return TokenUsage(
        prompt_tokens=_as_int(raw_usage.get("prompt_tokens"), 0),
        completion_tokens=_as_int(raw_usage.get("completion_tokens"), 0),
    )


class DirectRunner(AgentRunner):
    """Runner that talks to an OpenAI-compatible chat completions endpoint.

    Args:
        model_config:   Provider config. Recognized keys:
            - ``provider``      : currently only ``"openai_compatible"``.
            - ``model``         : the model name to send in the request.
            - ``api_key_env``   : name of the env var holding the API key.
            - ``base_url_env``  : name of the env var holding the base URL.
        runtime_policy: Execution policy. Recognized keys:
            - ``timeout_seconds``  : per-request timeout.
            - ``max_retries``      : max retry attempts on transient errors.
            - ``backoff_seconds``  : list of wait seconds between retries
              (one per retry attempt; extra entries are ignored).
    """

    def __init__(self, model_config: dict[str, object], runtime_policy: dict[str, object]) -> None:
        provider = model_config.get("provider", "openai_compatible")
        if provider != "openai_compatible":
            msg = f"DirectRunner: unsupported provider '{provider}' (only 'openai_compatible' supported)"
            raise ValueError(msg)

        self._model_name = str(model_config.get("model", ""))
        if not self._model_name:
            msg = "DirectRunner: model_config is missing a 'model' value"
            raise ValueError(msg)

        api_key_env = model_config.get("api_key_env")
        if not isinstance(api_key_env, str) or not api_key_env:
            msg = "DirectRunner: model_config is missing 'api_key_env' (env var name for the API key)"
            raise ValueError(msg)
        self._api_key_env = api_key_env

        base_url_env = model_config.get("base_url_env")
        if not isinstance(base_url_env, str) or not base_url_env:
            msg = "DirectRunner: model_config is missing 'base_url_env' (env var name for the base URL)"
            raise ValueError(msg)
        self._base_url_env = base_url_env

        self._timeout = _as_float(runtime_policy.get("timeout_seconds"), 600.0)
        self._max_retries = _as_int(runtime_policy.get("max_retries"), 0)
        backoff = runtime_policy.get("backoff_seconds", [])
        if isinstance(backoff, Sequence):
            self._backoff: list[float] = [_as_float(x, 0.0) for x in backoff]
        else:
            self._backoff = []

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        """Send the prompt to the configured OpenAI-compatible endpoint."""
        api_key = _resolve_env(self._api_key_env)
        base_url = _resolve_env(self._base_url_env).rstrip("/")

        # The agent's per-agent model override takes precedence over the
        # runner-level default when present.
        model = agent.model if agent.model else self._model_name

        request_body: dict[str, object] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = f"{base_url}/chat/completions"

        last_exc: BaseException | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._post_once(url, headers, request_body)
            except TransientError as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    break
                wait = self._backoff[min(attempt, len(self._backoff) - 1)] if self._backoff else 0.0
                if wait > 0:
                    import asyncio

                    await asyncio.sleep(wait)
            except NonTransientError:
                raise

        msg = f"DirectRunner: exhausted {self._max_retries} retries for agent '{agent.id}'"
        raise RuntimeError(msg) from last_exc

    async def _post_once(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> AgentResponse:
        """Issue a single HTTP POST and translate the result."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise TransientError(f"DirectRunner: request timed out after {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise TransientError(f"DirectRunner: network error: {exc}") from exc

        if resp.status_code == 200:
            return self._parse_response(resp.json())

        if _is_transient_status(resp.status_code):
            raise TransientError(
                f"DirectRunner: transient HTTP {resp.status_code}: {resp.text[:200]}"
            )
        raise NonTransientError(
            f"DirectRunner: HTTP {resp.status_code}: {resp.text[:200]}"
        )

    @staticmethod
    def _parse_response(payload: object) -> AgentResponse:
        """Turn an OpenAI-format chat completion JSON into an AgentResponse."""
        if not isinstance(payload, dict):
            msg = "DirectRunner: response payload is not a JSON object"
            raise RuntimeError(msg)

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            msg = "DirectRunner: response has no 'choices' array"
            raise RuntimeError(msg)

        first = choices[0]
        if not isinstance(first, dict):
            msg = "DirectRunner: first choice is not an object"
            raise RuntimeError(msg)

        message = first.get("message")
        if not isinstance(message, dict):
            msg = "DirectRunner: first choice has no 'message' object"
            raise RuntimeError(msg)

        text = message.get("content")
        text_str = text if isinstance(text, str) else ""

        raw_tool_calls = message.get("tool_calls")
        tool_calls = _parse_tool_calls(raw_tool_calls) if isinstance(raw_tool_calls, list) else []

        usage = _parse_usage(payload.get("usage"))

        return AgentResponse(
            text=text_str,
            tool_calls=tool_calls,
            usage=usage,
            raw=payload,
        )
