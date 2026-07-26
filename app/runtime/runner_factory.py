"""Build the AgentRunner for a round from user configuration.

The runner choice (mock vs direct) and its endpoint parameters are user
configuration (``config/models.yaml`` + ``config/runtime.yaml``); this
factory is the runtime's implementation of that choice. Configuration
problems raise :class:`ValueError` loudly — the factory never silently
falls back to the mock runner.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from app.runtime.runners.base import AgentRunner
from app.runtime.runners.direct_runner import DirectRunner
from app.runtime.runners.mock_runner import MockRunner

if TYPE_CHECKING:
    from app.config_loader import ModelsConfig, RuntimeConfig


def build_runner(models: ModelsConfig, runtime: RuntimeConfig) -> AgentRunner:
    """Build the configured :class:`AgentRunner`.

    Args:
        models: The merged models config (``runner`` / ``default_tier`` /
            ``tiers``).
        runtime: The merged runtime config; its ``runner`` section supplies
            the execution policy (timeout / retries / backoff) for the
            direct runner.

    Returns:
        A :class:`MockRunner` for ``runner: mock``, or a fully-configured
        :class:`DirectRunner` for ``runner: direct``.

    Raises:
        ValueError: On an unknown ``runner`` value, a missing
            ``default_tier`` entry, or an unset model-name env var.
    """
    if models.runner == "mock":
        return MockRunner()

    if models.runner == "direct":
        tier = models.tiers.get(models.default_tier)
        if tier is None:
            available = ", ".join(sorted(models.tiers)) or "<none>"
            msg = (
                f"build_runner: default_tier {models.default_tier!r} not in "
                f"models.tiers (available: {available})"
            )
            raise ValueError(msg)
        model_name = os.environ.get(tier.model_env, "")
        if not model_name:
            msg = (
                f"build_runner: env var {tier.model_env!r} (tier "
                f"{models.default_tier!r} model_env) is not set"
            )
            raise ValueError(msg)
        return DirectRunner(
            model_config={
                "provider": tier.provider,
                "model": model_name,
                "api_key_env": tier.api_key_env,
                "base_url_env": tier.base_url_env,
            },
            runtime_policy=dict(runtime.runner),
        )

    msg = f"build_runner: unknown runner {models.runner!r} (expected 'mock' or 'direct')"
    raise ValueError(msg)


__all__ = ["build_runner"]
