from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import SETTINGS
from .models import ArtifactEntry, TaskCreateRequest, TaskState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ensure_roots()

    def _ensure_roots(self) -> None:
        for path in (
            SETTINGS.data_root,
            SETTINGS.materials_root,
            SETTINGS.materials_docs_root,
            SETTINGS.materials_images_root,
            SETTINGS.uploads_root,
            SETTINGS.jobs_root,
            SETTINGS.examples_downloads_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def create_task(self, request_data: TaskCreateRequest, upstream_user_id: Optional[str] = None) -> TaskState:
        task_id = uuid.uuid4().hex
        job_dir = self.job_dir(task_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "downloads").mkdir(exist_ok=True)
        request_payload = request_data.model_dump()
        state = TaskState(
            task_id=task_id,
            status="queued",
            stage="queued",
            created_at=utcnow(),
            updated_at=utcnow(),
            request=request_payload,
            upstream_user_id=upstream_user_id,
            log_path=str(self.log_path(task_id)),
        )
        self.save_state(state)
        self.write_json(
            job_dir / "request.json",
            {
                "request": request_payload,
                "upstream_user_id": upstream_user_id,
            },
        )
        self.append_log(task_id, f"Task registered via API (upstream_user_id={upstream_user_id or '-'})")
        return state

    def save_state(self, state: TaskState) -> TaskState:
        with self._lock:
            state.updated_at = utcnow()
            state_path = self.state_path(state.task_id)
            state_path.write_text(
                json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return state

    def load_state(self, task_id: str) -> TaskState:
        path = self.state_path(task_id)
        if not path.exists():
            raise FileNotFoundError(task_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        return TaskState.model_validate(data)

    def update_state(self, task_id: str, **changes: Any) -> TaskState:
        state = self.load_state(task_id)
        for key, value in changes.items():
            setattr(state, key, value)
        return self.save_state(state)

    def write_stage_metadata(self, task_id: str, stage: str, payload: Any) -> Path:
        path = self.job_dir(task_id) / f"{stage}.json"
        self.write_json(path, payload)
        return path

    def write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_log(self, task_id: str, message: str) -> None:
        timestamp = utcnow().isoformat(timespec="seconds")
        line = f"[{timestamp}] {message}"
        with self.log_path(task_id).open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
        print(line, flush=True)

    def set_artifacts(self, task_id: str, artifacts: list[ArtifactEntry]) -> TaskState:
        return self.update_state(task_id, artifacts=artifacts)

    def request_cancel(self, task_id: str) -> TaskState:
        return self.update_state(task_id, cancel_requested=True)

    def is_cancel_requested(self, task_id: str) -> bool:
        return self.load_state(task_id).cancel_requested

    def job_dir(self, task_id: str) -> Path:
        return SETTINGS.jobs_root / task_id

    def uploads_dir(self, task_id: str) -> Path:
        return SETTINGS.uploads_root / task_id

    def state_path(self, task_id: str) -> Path:
        return self.job_dir(task_id) / "state.json"

    def log_path(self, task_id: str) -> Path:
        return self.job_dir(task_id) / "run.log"

    def build_artifact_index(self, task_id: str, project_path: Optional[Path]) -> list[ArtifactEntry]:
        artifacts: list[ArtifactEntry] = []
        job_dir = self.job_dir(task_id)
        log_path = self.log_path(task_id)
        if log_path.exists():
            artifacts.append(
                ArtifactEntry(
                    name="run_log",
                    kind="log",
                    relative_path=str(log_path.relative_to(job_dir)),
                    size_bytes=log_path.stat().st_size,
                )
            )

        for metadata_path in sorted(job_dir.glob("*.json")):
            if metadata_path.name == "state.json":
                continue
            artifact_name = f"job_{metadata_path.stem}"
            artifacts.append(
                ArtifactEntry(
                    name=artifact_name,
                    kind="file",
                    relative_path=str(metadata_path.relative_to(job_dir)),
                    size_bytes=metadata_path.stat().st_size,
                )
            )

        if not project_path or not project_path.exists():
            return artifacts

        candidates: list[tuple[str, Path, str]] = [
            ("design_spec", project_path / "design_spec.md", "file"),
            ("strategy_json", project_path / "strategy.json", "file"),
            ("notes_total", project_path / "notes" / "total.md", "file"),
            ("svg_output", project_path / "svg_output", "directory"),
            ("svg_final", project_path / "svg_final", "directory"),
            ("notes", project_path / "notes", "directory"),
            ("sources", project_path / "sources", "directory"),
            ("images", project_path / "images", "directory"),
        ]

        for pptx_path in sorted(project_path.glob("*.pptx")):
            if pptx_path.name.endswith("_svg.pptx"):
                candidates.append(("svg_pptx", pptx_path, "file"))
            else:
                candidates.append(("native_pptx", pptx_path, "file"))

        for name, path, kind in candidates:
            if not path.exists():
                continue
            size = None
            if path.is_file():
                size = path.stat().st_size
            artifacts.append(
                ArtifactEntry(
                    name=name,
                    kind=kind,  # type: ignore[arg-type]
                    relative_path=str(path),
                    size_bytes=size,
                )
            )
        return artifacts

    def create_download_bundle(self, task_id: str, artifact: ArtifactEntry) -> Path:
        source = Path(artifact.relative_path)
        downloads_dir = self.job_dir(task_id) / "downloads"
        downloads_dir.mkdir(exist_ok=True)
        if source.is_file():
            return source

        archive_base = downloads_dir / artifact.name
        archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=source))
        return archive_path


STORE = TaskStore()
