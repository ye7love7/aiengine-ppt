from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _normalize_base_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return "http://41.218.128.102:3001/v1"
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw.rstrip("/")


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    data_root: Path
    materials_root: Path
    uploads_root: Path
    jobs_root: Path
    examples_downloads_root: Path
    service_token: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: int
    llm_max_retries: int
    llm_temperature: float
    max_source_chars: int

    @property
    def materials_docs_root(self) -> Path:
        return self.materials_root / "docs"

    @property
    def materials_images_root(self) -> Path:
        return self.materials_root / "images"

    @property
    def examples_root(self) -> Path:
        return self.repo_root / "examples"


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parent.parent
    data_root = repo_root / "service_data"
    materials_root = data_root / "materials"
    uploads_root = data_root / "uploads"
    jobs_root = data_root / "jobs"
    examples_downloads_root = data_root / "examples_downloads"

    return Settings(
        repo_root=repo_root,
        data_root=data_root,
        materials_root=materials_root,
        uploads_root=uploads_root,
        jobs_root=jobs_root,
        examples_downloads_root=examples_downloads_root,
        service_token=os.environ.get("PPT_SERVICE_TOKEN", "sk-123123"),
        llm_base_url=_normalize_base_url(os.environ.get("LLM_BASE_URL", "https://api-inference.modelscope.cn/v1")),
        llm_api_key=os.environ.get("LLM_API_KEY", "ms-2888fabb-e8e8-4113-86a3-257b3b4b5a4b"),
        llm_model=os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-397B-A17B"),
        llm_timeout_seconds=int(os.environ.get("LLM_TIMEOUT_SECONDS", "180")),
        llm_max_retries=int(os.environ.get("LLM_MAX_RETRIES", "2")),
        llm_temperature=float(os.environ.get("LLM_TEMPERATURE", "0.3")),
        max_source_chars=int(os.environ.get("MAX_SOURCE_CHARS", "24000")),
    )


SETTINGS = load_settings()
