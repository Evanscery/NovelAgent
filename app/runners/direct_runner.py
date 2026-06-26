from __future__ import annotations

import asyncio
import json
from urllib import error, request

from app.rate_limit import SimpleRateLimiter
from app.runtime_config import RecoveryPolicy, RunnerPolicy, RuntimeConfig, resolve_model_for_tier
from app.runners.base import AgentRunner, Step


class DirectRunner(AgentRunner):
    """通过 OpenAI 兼容接口直接调用真实模型。"""

    _limiters: dict[str, SimpleRateLimiter] = {}

    def __init__(
        self,
        runtime: RuntimeConfig,
        models_config: dict,
        runner_policy: RunnerPolicy | None = None,
        recovery_policy: RecoveryPolicy | None = None,
    ):
        self.runtime = runtime
        self.models_config = models_config
        self.runner_policy = runner_policy or RunnerPolicy()
        self.recovery_policy = recovery_policy or RecoveryPolicy()

    async def run(self, step: Step, context: str) -> str:
        tier_name, rpm = self._tier_for_agent(step.agent)
        limiter = self._limiters.setdefault(tier_name, SimpleRateLimiter(rpm=rpm))
        await limiter.wait()

        primary_tier = tier_name
        try:
            return await self._run_with_tier(step, context, primary_tier)
        except RuntimeError as exc:
            if not self._should_fallback(step, primary_tier):
                raise
            fallback_tier = self.recovery_policy.fallback_tier
            fallback_result = await self._run_with_tier(step, context, fallback_tier)
            return f"<!-- DEGRADED: fallback={fallback_tier}; reason={str(exc).splitlines()[0]} -->\n{fallback_result}"

    async def _run_with_tier(self, step: Step, context: str, tier_name: str) -> str:
        model = resolve_model_for_tier(self.runtime, tier_name)
        prompt = (
            "你是小说多 Agent 工作流中的受控执行单元。"
            "只返回当前步骤目标 artifact 需要写入的正文内容。"
            "不要解释，不要道歉，不要输出代码块围栏，不要输出多余说明。\n\n"
            f"步骤：{step.id}\nAgent：{step.agent}\n场景：{step.scene_id}\n输出文件：{step.output_path}\n模型层级：{tier_name}\n\n"
            f"{context}"
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是高质量中文小说工作流中的一个受控执行单元。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        url = self.runtime.base_url + "/v1/chat/completions"
        req = request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.runtime.api_key}",
            },
            method="POST",
        )

        max_retries = max(1, self.runner_policy.max_retries)
        schedule = list(self.runner_policy.backoff_seconds) or [4]
        last_error: Exception | None = None
        body = ""
        for attempt in range(1, max_retries + 1):
            try:
                with request.urlopen(req, timeout=self.runner_policy.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                break
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in {524, 502, 503, 504, 520} and attempt < max_retries:
                    last_error = RuntimeError(f"模型请求失败：HTTP {exc.code}\n{detail}")
                    await asyncio.sleep(schedule[min(attempt - 1, len(schedule) - 1)])
                    continue
                raise RuntimeError(f"模型请求失败：HTTP {exc.code}\n{detail}") from exc
            except error.URLError as exc:
                if attempt < max_retries:
                    last_error = RuntimeError(f"模型请求失败：{exc}")
                    await asyncio.sleep(schedule[min(attempt - 1, len(schedule) - 1)])
                    continue
                raise RuntimeError(f"模型请求失败：{exc}") from exc
        else:
            raise last_error or RuntimeError("模型请求失败：未知错误")

        data = json.loads(body)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"模型没有返回 choices：{body}")
        message = (choices[0].get("message") or {}).get("content", "")
        text = message.strip()
        if not text:
            raise RuntimeError(f"模型返回空内容：{body}")
        return text

    def _should_fallback(self, step: Step, primary_tier: str) -> bool:
        if primary_tier == self.recovery_policy.fallback_tier:
            return False
        if step.agent.endswith("_guard"):
            return self.recovery_policy.allow_guard_degrade
        return self.recovery_policy.allow_writer_fallback

    def _tier_for_agent(self, agent_name: str) -> tuple[str, int]:
        agent_map = self.models_config.get("agents", {})
        tiers = self.models_config.get("tiers", {})
        if agent_name == "chapter_expander":
            tier_name = "standard"
        else:
            tier_name = agent_map.get(agent_name, "standard")
        tier_config = tiers.get(tier_name, {})
        rpm = int(tier_config.get("rpm", 10))
        return tier_name, rpm
