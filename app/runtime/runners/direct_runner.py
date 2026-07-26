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

from app.runtime._coerce import as_float as _as_float
from app.runtime._coerce import as_int as _as_int
from app.runtime.prompt_builder import RequestSpec
from app.runtime.providers.openai_chat import OpenAIChatEncoder

from .base import AgentResponse, AgentRunner, RunnerAgent


class TransientError(Exception):
    """An error that may succeed on retry (5xx, 429, timeout, network)."""


class NonTransientError(Exception):
    """An error that will not succeed on retry (4xx except 429)."""


def _is_transient_status(status_code: int) -> bool:
    """Return True for status codes that warrant a retry."""
    if status_code == 429:  # rate limit — retry with backoff
        return True
    return status_code >= 500


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
        tier_models: Mapping of config tier name (e.g. ``"premium"``) to
            the real model name resolved from that tier's ``model_env``
            (``None`` when the env var is unset). An agent's ``model``
            attribute names a tier; it is resolved through this mapping
            before being sent to the endpoint. A value that is not a known
            tier is passed through as a literal model name.
    """

    def __init__(
        self,
        model_config: dict[str, object],
        runtime_policy: dict[str, object],
        tier_models: dict[str, str | None] | None = None,
    ) -> None:
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
        self._encoder = OpenAIChatEncoder()
        self._tier_models = dict(tier_models) if tier_models else {}

    def _resolve_model(self, requested: str | None) -> str:
        """Resolve the request's model (a tier name or literal) to a model name.

        Tier names come from the agent's ``model`` attribute; they resolve
        through ``tier_models``. A known tier whose env var is unset raises
        instead of sending the tier name to the endpoint (which would 400).
        Unknown values pass through as literal model names.
        """
        if not requested:
            return self._model_name
        if requested in self._tier_models:
            resolved = self._tier_models[requested]
            if not resolved:
                msg = (
                    f"DirectRunner: model tier {requested!r} has no model name — "
                    "set the tier's model_env variable (see config/models.yaml)"
                )
                raise RuntimeError(msg)
            return resolved
        return requested

    async def run(self, agent: RunnerAgent, request: RequestSpec) -> AgentResponse:
        """Send the request to the configured OpenAI-compatible endpoint."""
        api_key = _resolve_env(self._api_key_env)
        base_url = _resolve_env(self._base_url_env).rstrip("/")

        request_body = self._encoder.encode(request)
        # The request's model (the agent's per-agent tier or literal
        # override) takes precedence over the runner-level default; tier
        # names resolve through the tier_models mapping.
        request_body["model"] = self._resolve_model(request.model)
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
            return self._encoder.decode(resp.json())

        if _is_transient_status(resp.status_code):
            raise TransientError(
                f"DirectRunner: transient HTTP {resp.status_code}: {resp.text[:200]}"
            )
        raise NonTransientError(
            f"DirectRunner: HTTP {resp.status_code}: {resp.text[:200]}"
        )
