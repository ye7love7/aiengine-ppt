from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .config import SETTINGS
from .models import ArtifactEntry


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg"}


def list_examples() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted(SETTINGS.examples_root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir():
            continue
        results.append(_build_example_metadata(path))
    return results


def get_example_detail(name: str) -> dict[str, Any]:
    example_dir = resolve_example_dir(name)
    return {
        "example": _build_example_metadata(example_dir),
        "artifacts": [artifact.model_dump() for artifact in build_example_artifacts(example_dir)],
        "preview": {
            "readme_excerpt": _read_excerpt(example_dir / "README.md", 2400),
            "design_spec_excerpt": _read_excerpt(example_dir / "design_spec.md", 6000),
        },
    }


def validate_example_reference(name: str | None) -> str | None:
    if not name:
        return None
    resolve_example_dir(name)
    return name


def load_example_prompt_context(name: str) -> dict[str, Any]:
    example_dir = resolve_example_dir(name)
    metadata = _build_example_metadata(example_dir)
    return {
        "name": metadata["name"],
        "suggested_style": metadata["suggested_style"],
        "summary": metadata["summary"],
        "readme_excerpt": _read_excerpt(example_dir / "README.md", 2400),
        "design_spec_excerpt": _read_excerpt(example_dir / "design_spec.md", 8000),
    }


def build_example_artifacts(example_dir: Path) -> list[ArtifactEntry]:
    artifacts: list[ArtifactEntry] = []
    candidates: list[tuple[str, Path, str]] = [
        ("readme", example_dir / "README.md", "file"),
        ("design_spec", example_dir / "design_spec.md", "file"),
        ("svg_output", example_dir / "svg_output", "directory"),
        ("svg_final", example_dir / "svg_final", "directory"),
        ("images", example_dir / "images", "directory"),
    ]
    for pptx_path in sorted(example_dir.glob("*.pptx")):
        if pptx_path.name.endswith("_svg.pptx"):
            candidates.append(("svg_pptx", pptx_path, "file"))
        else:
            candidates.append(("native_pptx", pptx_path, "file"))

    for name, path, kind in candidates:
        if not path.exists():
            continue
        artifacts.append(
            ArtifactEntry(
                name=name,
                kind=kind,  # type: ignore[arg-type]
                relative_path=str(path),
                size_bytes=path.stat().st_size if path.is_file() else None,
            )
        )
    return artifacts


def create_example_download_bundle(name: str, artifact_name: str) -> Path:
    example_dir = resolve_example_dir(name)
    artifact = next((item for item in build_example_artifacts(example_dir) if item.name == artifact_name), None)
    if artifact is None:
        raise FileNotFoundError(artifact_name)

    source = Path(artifact.relative_path)
    if source.is_file():
        return source

    SETTINGS.examples_downloads_root.mkdir(parents=True, exist_ok=True)
    archive_base = SETTINGS.examples_downloads_root / f"{name}_{artifact_name}"
    archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=source))
    return archive_path


def resolve_example_dir(name: str) -> Path:
    candidate = (SETTINGS.examples_root / name).resolve()
    root = SETTINGS.examples_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FileNotFoundError(name) from exc
    if not candidate.exists() or not candidate.is_dir():
        raise FileNotFoundError(name)
    return candidate


def _build_example_metadata(example_dir: Path) -> dict[str, Any]:
    svg_dir = example_dir / "svg_final"
    if not svg_dir.exists():
        svg_dir = example_dir / "svg_output"
    page_count = len([path for path in svg_dir.glob("*.svg") if path.is_file()]) if svg_dir.exists() else 0
    image_count = len([path for path in (example_dir / "images").glob("*") if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES]) if (example_dir / "images").exists() else 0
    has_native_pptx = any(path.is_file() and not path.name.endswith("_svg.pptx") for path in example_dir.glob("*.pptx"))
    has_svg_pptx = any(path.is_file() and path.name.endswith("_svg.pptx") for path in example_dir.glob("*.pptx"))
    return {
        "name": example_dir.name,
        "title": example_dir.name,
        "relative_path": str(example_dir.relative_to(SETTINGS.repo_root)),
        "page_count": page_count,
        "image_count": image_count,
        "has_design_spec": (example_dir / "design_spec.md").exists(),
        "has_readme": (example_dir / "README.md").exists(),
        "has_native_pptx": has_native_pptx,
        "has_svg_pptx": has_svg_pptx,
        "suggested_style": _infer_style(example_dir.name),
        "summary": _extract_summary(example_dir),
    }


def _extract_summary(example_dir: Path) -> str:
    for path in (example_dir / "README.md", example_dir / "design_spec.md"):
        text = _read_excerpt(path, 800)
        for raw_line in text.splitlines():
            line = raw_line.strip().lstrip("#>").strip()
            if len(line) >= 12:
                return line[:220]
    return ""


def _read_excerpt(path: Path, limit: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def _infer_style(name: str) -> str:
    lowered = name.lower()
    if "顶级咨询" in name or "mbb" in lowered:
        return "consulting_top"
    if "高端咨询" in name or "麦肯锡" in name or "google" in lowered or "谷歌" in name:
        return "consulting"
    if "咨询" in name:
        return "consulting"
    return "general"
