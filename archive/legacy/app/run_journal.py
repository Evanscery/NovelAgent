from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.file_io import ProjectFileIO


@dataclass(frozen=True)
class StepRecord:
    step_id: str
    agent: str
    status: str
    output_path: str | None = None
    degraded: bool = False
    cached: bool = False
    error: str | None = None


class RunJournal:
    def __init__(self, file_io: ProjectFileIO, journal_dir: str, checkpoint_dir: str):
        self.file_io = file_io
        self.journal_dir = journal_dir
        self.checkpoint_dir = checkpoint_dir

    def load(self, scene_id: str) -> dict[str, Any]:
        path = self._journal_path(scene_id)
        if not path.exists():
            return {"scene_id": scene_id, "status": "new", "steps": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def mark_scene_status(self, scene_id: str, status: str) -> None:
        data = self.load(scene_id)
        data["scene_id"] = scene_id
        data["status"] = status
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(self._journal_path(scene_id), data)
        self._write_json(self._journal_dir_path() / "latest.json", data)

    def record_step(self, scene_id: str, record: StepRecord) -> None:
        data = self.load(scene_id)
        steps = [step for step in data.get("steps", []) if step.get("step_id") != record.step_id]
        steps.append(
            {
                "step_id": record.step_id,
                "agent": record.agent,
                "status": record.status,
                "output_path": record.output_path,
                "degraded": record.degraded,
                "cached": record.cached,
                "error": record.error,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        data["steps"] = steps
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(self._journal_path(scene_id), data)
        self._write_json(self._journal_dir_path() / "latest.json", data)

    def completed_step_ids(self, scene_id: str) -> set[str]:
        data = self.load(scene_id)
        result = set()
        for step in data.get("steps", []):
            if step.get("status") == "completed":
                result.add(step.get("step_id", ""))
        return result

    def write_checkpoint(self, scene_id: str, payload: dict[str, Any]) -> Path:
        path = self._checkpoint_path(scene_id)
        snapshot = {
            "scene_id": scene_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        self._write_json(path, snapshot)
        return path

    def load_checkpoint(self, scene_id: str) -> dict[str, Any]:
        path = self._checkpoint_path(scene_id)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _journal_path(self, scene_id: str) -> Path:
        return self._journal_dir_path() / f"{scene_id}.json"

    def _checkpoint_path(self, scene_id: str) -> Path:
        return self.file_io.resolve(self.checkpoint_dir) / f"{scene_id}.json"

    def _journal_dir_path(self) -> Path:
        return self.file_io.resolve(self.journal_dir)

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
