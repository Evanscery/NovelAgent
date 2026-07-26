"""Unit tests for :mod:`app.runtime.runner_factory`."""

from __future__ import annotations

import pytest

from app.config_loader import ModelsConfig, RuntimeConfig, TierConfig
from app.runtime.runner_factory import build_runner
from app.runtime.runners.direct_runner import DirectRunner
from app.runtime.runners.mock_runner import MockRunner


def _models(**overrides: object) -> ModelsConfig:
    base: dict[str, object] = {
        "runner": "mock",
        "default_tier": "standard",
        "tiers": {
            "standard": TierConfig(
                provider="openai_compatible",
                model_env="TEST_MODEL_ENV",
                api_key_env="TEST_API_KEY",
                base_url_env="TEST_BASE_URL",
            )
        },
    }
    base.update(overrides)
    return ModelsConfig.model_validate(base)


def _runtime() -> RuntimeConfig:
    return RuntimeConfig(runner={"timeout_seconds": 5, "max_retries": 0})


class TestBuildRunner:
    def test_mock_runner(self) -> None:
        assert isinstance(build_runner(_models(runner="mock"), _runtime()), MockRunner)

    def test_direct_runner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_MODEL_ENV", "some-model")
        runner = build_runner(_models(runner="direct"), _runtime())
        assert isinstance(runner, DirectRunner)

    def test_direct_runner_missing_model_env_fails_loud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TEST_MODEL_ENV", raising=False)
        with pytest.raises(ValueError, match="TEST_MODEL_ENV"):
            build_runner(_models(runner="direct"), _runtime())

    def test_direct_runner_missing_tier_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="default_tier"):
            build_runner(_models(runner="direct", default_tier="nope"), _runtime())

    def test_unknown_runner_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="unknown runner"):
            build_runner(_models(runner="quantum"), _runtime())
