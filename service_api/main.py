from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime
from io import SEEK_END
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import FormData, UploadFile

from .config import SETTINGS
from .examples import create_example_download_bundle, get_example_detail, list_examples, validate_example_reference
from .models import ArtifactEntry, TaskCreateRequest, TaskCreateResponse
from .pipeline import IMAGE_SUFFIXES, TEXT_SUFFIXES, DOC_SUFFIXES, run_task
from .storage import STORE


app = FastAPI(title="Offline PPT Master Service", version="0.1.0")
_RUNNING_TASKS: dict[str, asyncio.Task[Any]] = {}
_UPSTREAM_USER_ID_HEADERS = (
    "x-request-user-id",
    "x-user-id",
    "x-forwarded-user-id",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    STORE._ensure_roots()


@app.post("/api/v1/tasks", response_model=TaskCreateResponse)
async def create_task(request: Request) -> TaskCreateResponse:
    form: FormData | None = None
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        task_request = await _parse_json_task_request(request)
    elif content_type.startswith("multipart/form-data"):
        form = await request.form()
        task_request = _parse_multipart_task_request(form)
    else:
        raise HTTPException(status_code=415, detail="Unsupported content type")

    upstream_user_id = _extract_upstream_user_id(request)
    state = STORE.create_task(task_request, upstream_user_id=upstream_user_id)
    if task_request.source_mode == "upload":
        assert form is not None
        _persist_uploads(form, state.task_id)
    task = asyncio.create_task(asyncio.to_thread(run_task, state.task_id))
    _RUNNING_TASKS[state.task_id] = task
    task.add_done_callback(lambda _: _RUNNING_TASKS.pop(state.task_id, None))
    return TaskCreateResponse(task_id=state.task_id, status=state.status, stage=state.stage)


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str) -> JSONResponse:
    try:
        state = STORE.load_state(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return JSONResponse(state.model_dump(mode="json"))


@app.get("/api/v1/tasks/{task_id}/artifacts")
async def get_task_artifacts(task_id: str) -> JSONResponse:
    try:
        state = STORE.load_state(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return JSONResponse({"task_id": task_id, "artifacts": [artifact.model_dump() for artifact in state.artifacts]})


@app.get("/api/v1/tasks/{task_id}/download/{artifact_name}")
async def download_artifact(task_id: str, artifact_name: str) -> FileResponse:
    try:
        state = STORE.load_state(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc

    artifact = next((item for item in state.artifacts if item.name == artifact_name), None)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    archive_path = STORE.create_download_bundle(task_id, artifact)
    return FileResponse(path=archive_path, filename=archive_path.name)


@app.get("/api/v1/materials")
async def list_materials() -> JSONResponse:
    return JSONResponse(
        {
            "docs": _list_material_group(SETTINGS.materials_docs_root),
            "images": _list_material_group(SETTINGS.materials_images_root),
        }
    )


@app.get("/api/v1/examples")
async def get_examples() -> JSONResponse:
    return JSONResponse({"examples": list_examples()})


@app.get("/api/v1/templates")
async def get_templates() -> JSONResponse:
    return JSONResponse({"templates": _list_templates()})


@app.get("/api/v1/examples/{example_name}")
async def get_example(example_name: str) -> JSONResponse:
    try:
        payload = get_example_detail(example_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Example not found") from exc
    return JSONResponse(payload)


@app.get("/api/v1/examples/{example_name}/download/{artifact_name}")
async def download_example_artifact(example_name: str, artifact_name: str) -> FileResponse:
    try:
        archive_path = create_example_download_bundle(example_name, artifact_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Example artifact not found") from exc
    return FileResponse(path=archive_path, filename=archive_path.name)


@app.post("/api/v1/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> JSONResponse:
    try:
        state = STORE.request_cancel(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return JSONResponse({"task_id": task_id, "status": state.status, "cancel_requested": True})


async def _parse_json_task_request(request: Request) -> TaskCreateRequest:
    body = await request.json()
    body["project_name"] = _ensure_project_name(body.get("project_name"))
    body["style_source"] = _ensure_style_source(body.get("style_source"), body.get("example_reference"))
    model = TaskCreateRequest.model_validate(body)
    if model.source_mode != "path":
        raise HTTPException(status_code=400, detail="JSON requests only support source_mode=path")
    _validate_example_reference_or_400(model.example_reference)
    return model


def _parse_multipart_task_request(form: FormData) -> TaskCreateRequest:
    example_reference = form.get("example_reference") or None
    payload = {
        "source_mode": form.get("source_mode", "upload"),
        "project_name": _ensure_project_name(form.get("project_name", "")),
        "canvas_format": form.get("canvas_format", "ppt169"),
        "template_name": form.get("template_name") or None,
        "example_reference": example_reference,
        "style_source": _ensure_style_source(form.get("style_source"), example_reference),
        "audience": form.get("audience") or None,
        "use_case": form.get("use_case") or None,
        "core_message": form.get("core_message") or None,
        "prefer_style": form.get("prefer_style", "auto"),
        "notes_style": form.get("notes_style", "formal"),
        "output_formats": _coerce_list_field(form.get("output_formats")) or ["native_pptx", "svg_pptx"],
        "source_files": [],
        "image_files": [],
    }
    model = TaskCreateRequest.model_validate(payload)
    if model.source_mode != "upload":
        raise HTTPException(status_code=400, detail="Multipart requests only support source_mode=upload")
    _validate_example_reference_or_400(model.example_reference)
    return model


def _persist_uploads(form: FormData, task_id: str) -> None:
    uploads_dir = STORE.uploads_dir(task_id)
    source_dir = uploads_dir / "source_files"
    image_dir = uploads_dir / "image_files"
    source_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    field_names: list[str] = []
    source_filenames: list[str] = []
    image_filenames: list[str] = []
    valid_source_count = 0
    valid_image_count = 0

    for key, value in form.multi_items():
        field_names.append(key)
        if not _is_upload_file(value) or not value.filename:
            continue
        suffix = Path(value.filename).suffix.lower()
        if key == "source_files":
            _validate_upload_suffix(suffix, TEXT_SUFFIXES | DOC_SUFFIXES)
            destination = source_dir / Path(value.filename).name
            source_filenames.append(value.filename)
        elif key == "image_files":
            _validate_upload_suffix(suffix, IMAGE_SUFFIXES)
            destination = image_dir / Path(value.filename).name
            image_filenames.append(value.filename)
        else:
            continue
        file_size = _get_upload_size(value)
        if file_size <= 0:
            continue
        with destination.open("wb") as handle:
            shutil.copyfileobj(value.file, handle)
        value.file.seek(0)
        if key == "source_files":
            valid_source_count += 1
        else:
            valid_image_count += 1

    STORE.append_log(
        task_id,
        f"Multipart fields={field_names}; source_files={source_filenames}; image_files={image_filenames}; "
        f"valid_source_files={valid_source_count}; valid_image_files={valid_image_count}",
    )

    if valid_source_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No valid uploaded source files were received; multipart source_files may be missing or 0 B",
        )


def _validate_upload_suffix(suffix: str, allowed: set[str]) -> None:
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported uploaded file type: {suffix}")


def _is_upload_file(value: Any) -> bool:
    return isinstance(value, UploadFile) or (
        hasattr(value, "filename") and hasattr(value, "file") and callable(getattr(value.file, "read", None))
    )


def _get_upload_size(upload: UploadFile) -> int:
    current = upload.file.tell()
    upload.file.seek(0, SEEK_END)
    size = upload.file.tell()
    upload.file.seek(current)
    return size


def _coerce_list_field(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    text = str(value).strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
        if isinstance(loaded, list):
            return [str(item) for item in loaded]
    except json.JSONDecodeError:
        pass
    return [item.strip() for item in text.split(",") if item.strip()]


def _ensure_project_name(value: Any) -> str:
    text = str(value or "").strip()
    if text:
        return text[:120]
    return f"ppt_task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _ensure_style_source(value: Any, example_reference: Any) -> str:
    text = str(value or "").strip()
    if text in {"prompt_reference", "example_strong"}:
        return text
    if str(example_reference or "").strip():
        return "example_strong"
    return "prompt_reference"


def _list_material_group(root: Path) -> list[dict[str, Any]]:
    results = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == ".gitkeep":
            continue
        results.append(
            {
                "path": str(path.relative_to(root)),
                "size_bytes": path.stat().st_size,
            }
        )
    return results


def _list_templates() -> list[dict[str, Any]]:
    layouts_root = SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts"
    results: list[dict[str, Any]] = []
    if not layouts_root.exists():
        return results
    for path in sorted(layouts_root.iterdir()):
        if not path.is_dir():
            continue
        results.append(
            {
                "name": path.name,
                "path": str(path.relative_to(layouts_root)),
            }
        )
    return results


def _extract_upstream_user_id(request: Request) -> str | None:
    for header_name in _UPSTREAM_USER_ID_HEADERS:
        value = (request.headers.get(header_name) or "").strip()
        if value:
            return value[:256]
    return None


def _validate_example_reference_or_400(value: str | None) -> None:
    try:
        validate_example_reference(value)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"Example not found: {value}") from exc
