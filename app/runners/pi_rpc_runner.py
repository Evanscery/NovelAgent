from __future__ import annotations

import asyncio
import os
from asyncio.subprocess import PIPE

from app.runners.base import AgentRunner, Step


class PiRpcRunner(AgentRunner):
    """通过 Pi 的无头模式获取文本结果。

    第一版只把 Pi 当作文本生成运行器：Python 负责读文件、组装上下文和写文件，
    Pi 不直接修改项目文件。
    """

    def __init__(self, command: str | None = None, timeout_seconds: int = 600):
        self.command = command or os.environ.get("PI_COMMAND", "pi")
        self.timeout_seconds = timeout_seconds

    async def run(self, step: Step, context: str) -> str:
        prompt = (
            "你是小说多 Agent MVP 中的一个受控执行单元。\n"
            "请只返回本步骤需要写入目标文件的正文内容，不要调用工具，不要修改文件。\n\n"
            f"步骤：{step.id}\nAgent：{step.agent}\n场景：{step.scene_id}\n输出文件：{step.output_path}\n\n"
            f"{context}"
        )
        process = await asyncio.create_subprocess_exec(
            self.command,
            "--mode",
            "json",
            prompt,
            stdout=PIPE,
            stderr=PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise TimeoutError(f"Pi 执行超时：{step.id}") from exc

        if process.returncode != 0:
            error_text = stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"Pi 执行失败：{step.id}\n{error_text}")

        text = stdout.decode("utf-8", errors="replace").strip()
        if not text:
            raise RuntimeError(f"Pi 没有返回内容：{step.id}")
        return text
