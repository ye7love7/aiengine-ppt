from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional
from PIL import Image

from .config import SETTINGS
from .examples import load_example_prompt_context
from .llm import LLM
from .prompts import EXECUTOR_SYSTEM_PROMPT, STRATEGIST_SYSTEM_PROMPT
from .rendering import notes_to_total_md, render_slide_svg, slugify, strategy_to_design_spec
from .storage import STORE

SCRIPTS_DIR = SETTINGS.repo_root / "skills" / "ppt-master" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from project_manager import ProjectManager  # type: ignore  # noqa: E402


TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
DOC_SUFFIXES = {
    ".pdf", ".docx", ".doc", ".odt", ".rtf", ".epub", ".html", ".htm", ".tex",
    ".latex", ".rst", ".org", ".ipynb", ".typ",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
TEMPLATE_BY_STYLE = {
    "general": "smart_red",
    "consulting": "mckinsey",
    "consulting_top": "exhibit",
}


def run_task(task_id: str) -> None:
    state = STORE.load_state(task_id)
    request_data = state.request
    manager = ProjectManager()
    project_path: Optional[Path] = None
    try:
        STORE.update_state(task_id, status="running", stage="ingest")
        STORE.append_log(task_id, f"Task started (upstream_user_id={state.upstream_user_id or '-'})")
        source_paths, image_paths = _resolve_inputs(task_id, request_data)
        _check_cancel(task_id)

        project_name = f"{request_data['project_name']}_{task_id[:8]}"
        project_path = Path(manager.init_project(project_name, request_data["canvas_format"], base_dir="projects"))
        STORE.append_log(task_id, f"Project created at {project_path}")
        STORE.update_state(task_id, project_path=str(project_path))

        summary = manager.import_sources(str(project_path), [str(path) for path in source_paths], move=False)
        STORE.write_stage_metadata(task_id, "ingest", summary)
        _copy_images(project_path, image_paths)
        STORE.append_log(task_id, f"Imported {len(source_paths)} source files and {len(image_paths)} images")
        _check_cancel(task_id)

        STORE.update_state(task_id, stage="strategist")
        strategy = _run_strategist(task_id, project_path, request_data)
        _check_cancel(task_id)

        STORE.update_state(task_id, stage="executor_svg")
        slides = _run_executor(task_id, project_path, strategy)
        _check_cancel(task_id)

        STORE.update_state(task_id, stage="executor_notes")
        notes_path = project_path / "notes" / "total.md"
        notes_path.write_text(notes_to_total_md(slides, strategy["language"]), encoding="utf-8")
        STORE.append_log(task_id, f"Wrote speaker notes: {notes_path}")
        _check_cancel(task_id)

        STORE.update_state(task_id, stage="postprocess")
        _run_script(task_id, [sys.executable, str(SCRIPTS_DIR / "total_md_split.py"), str(project_path)])
        _run_script(task_id, [sys.executable, str(SCRIPTS_DIR / "finalize_svg.py"), str(project_path)])
        _check_cancel(task_id)

        STORE.update_state(task_id, stage="export")
        export_cmd = [sys.executable, str(SCRIPTS_DIR / "svg_to_pptx.py"), str(project_path), "-s", "final"]
        output_formats = set(request_data.get("output_formats") or [])
        if output_formats == {"native_pptx"}:
            export_cmd.extend(["--only", "native"])
        elif output_formats == {"svg_pptx"}:
            export_cmd.extend(["--only", "legacy"])
        _run_script(task_id, export_cmd)

        artifacts = STORE.build_artifact_index(task_id, project_path)
        STORE.set_artifacts(task_id, artifacts)
        STORE.update_state(task_id, status="succeeded", stage="completed")
        STORE.append_log(task_id, "Task completed successfully")
    except CancelledError:
        artifacts = STORE.build_artifact_index(task_id, project_path)
        STORE.set_artifacts(task_id, artifacts)
        STORE.update_state(task_id, status="cancelled", stage="cancelled", error="Task cancelled by user")
        STORE.append_log(task_id, "Task cancelled")
    except Exception as exc:
        artifacts = STORE.build_artifact_index(task_id, project_path)
        STORE.set_artifacts(task_id, artifacts)
        STORE.update_state(task_id, status="failed", stage="failed", error=str(exc))
        STORE.append_log(task_id, f"Task failed: {exc}")


class CancelledError(RuntimeError):
    pass


def _check_cancel(task_id: str) -> None:
    if STORE.is_cancel_requested(task_id):
        raise CancelledError()


def _resolve_inputs(task_id: str, request_data: dict[str, Any]) -> tuple[list[Path], list[Path]]:
    source_mode = request_data["source_mode"]
    if source_mode == "path":
        source_paths = [_validate_material_relpath(path, SETTINGS.materials_docs_root, TEXT_SUFFIXES | DOC_SUFFIXES) for path in request_data.get("source_files", [])]
        image_paths = [_validate_material_relpath(path, SETTINGS.materials_images_root, IMAGE_SUFFIXES) for path in request_data.get("image_files", [])]
        if not source_paths:
            raise ValueError("At least one source file is required")
        return source_paths, image_paths

    uploads_dir = STORE.uploads_dir(task_id)
    source_paths = sorted((uploads_dir / "source_files").glob("*"))
    image_paths = sorted((uploads_dir / "image_files").glob("*"))
    if not source_paths:
        raise ValueError("At least one uploaded source file is required")
    return source_paths, image_paths


def _validate_material_relpath(rel_path: str, root: Path, allowed_suffixes: set[str]) -> Path:
    if not rel_path:
        raise ValueError("Empty relative path is not allowed")
    candidate = (root / rel_path).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Path escapes materials root: {rel_path}") from exc
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(rel_path)
    if candidate.suffix.lower() not in allowed_suffixes:
        raise ValueError(f"Unsupported file type: {rel_path}")
    return candidate


def _copy_images(project_path: Path, image_paths: list[Path]) -> None:
    images_dir = project_path / "images"
    images_dir.mkdir(exist_ok=True)
    for image_path in image_paths:
        shutil.copy2(image_path, images_dir / image_path.name)


def _analyze_images(images_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for image_path in sorted(images_dir.glob("*")):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        with Image.open(image_path) as image:
            width, height = image.size
        aspect_ratio = round(width / height, 2) if height else 1.0
        results.append(
            {
                "filename": image_path.name,
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
            }
        )
    return results


def _run_strategist(task_id: str, project_path: Path, request_data: dict[str, Any]) -> dict[str, Any]:
    source_bundle = _collect_source_text(project_path)
    image_inventory = _analyze_images(project_path / "images") if any((project_path / "images").iterdir()) else []
    example_reference = request_data.get("example_reference") or None
    example_context = load_example_prompt_context(example_reference) if example_reference else None

    prefer_style = request_data.get("prefer_style") or "auto"
    if prefer_style == "auto" and example_context and example_context.get("suggested_style") in TEMPLATE_BY_STYLE:
        prefer_style = str(example_context["suggested_style"])
    style_hint = prefer_style if prefer_style != "auto" else "auto based on document type"
    template_name = request_data.get("template_name") or ""
    if template_name:
        _copy_template(project_path, template_name)

    prompt = f"""
Project name: {request_data['project_name']}
Canvas format: {request_data['canvas_format']}
Preferred template: {template_name or 'auto'}
Preferred style: {style_hint}
Requested audience: {request_data.get('audience') or 'auto infer'}
Requested use case: {request_data.get('use_case') or 'auto infer'}
Requested core message: {request_data.get('core_message') or 'auto infer'}
Notes style: {request_data.get('notes_style') or 'formal'}
Available local images: {[item['filename'] for item in image_inventory]}
Example style reference: {example_reference or 'none'}
Source material:
{source_bundle}
"""
    if example_context:
        prompt += f"""

Use the following local example only as a visual and structural style reference. Do not reuse its topic, facts, figures, or narrative unless they also appear in the user's source material.
Example name: {example_context['name']}
Suggested style: {example_context['suggested_style']}
Example summary: {example_context['summary'] or 'N/A'}
Example README excerpt:
{example_context['readme_excerpt'] or 'N/A'}

Example design_spec excerpt:
{example_context['design_spec_excerpt'] or 'N/A'}
"""
    strategy = LLM.chat_json(STRATEGIST_SYSTEM_PROMPT, prompt, max_tokens=6000)
    if example_reference:
        strategy["example_reference"] = example_reference
    strategy["canvas_format"] = request_data["canvas_format"]
    strategy["template_name"] = strategy.get("template_name") or template_name or TEMPLATE_BY_STYLE.get(strategy.get("style_mode", "general"), "")
    if not template_name and strategy["template_name"]:
        _copy_template(project_path, strategy["template_name"])
    strategy["style_mode"] = _normalize_style(strategy.get("style_mode"), prefer_style)
    strategy["pages"] = _normalize_pages(strategy)
    strategy["page_count"] = len(strategy["pages"])
    strategy["image_strategy"] = "user_provided" if image_inventory else "none"
    strategy["theme"] = _normalize_theme(strategy.get("theme") or {}, strategy["style_mode"])
    strategy["typography"] = _normalize_typography(strategy.get("typography") or {})

    (project_path / "strategy.json").write_text(json.dumps(strategy, ensure_ascii=False, indent=2), encoding="utf-8")
    (project_path / "design_spec.md").write_text(
        strategy_to_design_spec(strategy, image_inventory, request_data["project_name"], request_data["canvas_format"]),
        encoding="utf-8",
    )
    STORE.write_stage_metadata(task_id, "strategist", strategy)
    STORE.append_log(task_id, "Strategist output saved")
    return strategy


def _run_executor(task_id: str, project_path: Path, strategy: dict[str, Any]) -> list[dict[str, Any]]:
    slides: list[dict[str, Any]] = []
    image_files = sorted([path.name for path in (project_path / "images").glob("*") if path.is_file()])
    previous_summary = ""
    for page in strategy["pages"]:
        _check_cancel(task_id)
        file_stem = page["file_stem"]
        prompt = f"""
Presentation language: {strategy['language']}
Style mode: {strategy['style_mode']}
Global theme colors: {json.dumps(strategy['theme'], ensure_ascii=False)}
Typography: {json.dumps(strategy['typography'], ensure_ascii=False)}
Available local images: {image_files}
Previous slide summary: {previous_summary or 'None'}
Current page plan: {json.dumps(page, ensure_ascii=False)}
"""
        blueprint = LLM.chat_json(EXECUTOR_SYSTEM_PROMPT, prompt, max_tokens=3000)
        blueprint["index"] = page["index"]
        blueprint["file_stem"] = blueprint.get("file_stem") or page["file_stem"]
        blueprint["page_type"] = page["page_type"]
        blueprint["title"] = blueprint.get("title") or page["title"]
        blueprint["subtitle"] = blueprint.get("subtitle") or page.get("subtitle", "")
        blueprint["image_filename"] = _normalize_image_choice(blueprint.get("image_filename", ""), image_files)
        blueprint["sections"] = _normalize_sections(blueprint.get("sections") or [], page)
        blueprint["kpis"] = _normalize_kpis(blueprint.get("kpis") or [])
        blueprint["speaker_notes"] = blueprint.get("speaker_notes") or page.get("goal", page["title"])
        blueprint["key_points"] = blueprint.get("key_points") or page.get("bullets", [])[:3]
        blueprint["duration_minutes"] = float(blueprint.get("duration_minutes") or 1.0)

        svg_content = render_slide_svg(blueprint, strategy, project_path / "images")
        (project_path / "svg_output" / f"{blueprint['file_stem']}.svg").write_text(svg_content, encoding="utf-8")
        slides.append(blueprint)
        previous_summary = blueprint["title"]
        STORE.append_log(task_id, f"Generated slide {blueprint['file_stem']}")

    STORE.write_stage_metadata(task_id, "executor_svg", {"slides": slides})
    return slides


def _collect_source_text(project_path: Path) -> str:
    chunks: list[str] = []
    for path in sorted((project_path / "sources").glob("*.md")):
        content = path.read_text(encoding="utf-8", errors="replace")
        chunks.append(f"## {path.name}\n{content[:SETTINGS.max_source_chars]}")
    if not chunks:
        raise ValueError("No markdown sources found after import")
    combined = "\n\n".join(chunks)
    return combined[:SETTINGS.max_source_chars]


def _copy_template(project_path: Path, template_name: str) -> None:
    layouts_root = SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts"
    template_dir = layouts_root / template_name
    if not template_dir.exists():
        raise FileNotFoundError(f"Template not found: {template_name}")
    destination = project_path / "templates"
    destination.mkdir(exist_ok=True)
    for path in template_dir.iterdir():
        target = destination / path.name
        if path.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)


def _normalize_style(style_value: Optional[str], preferred: str) -> str:
    if preferred in {"general", "consulting", "consulting_top"}:
        return preferred
    if style_value in {"general", "consulting", "consulting_top"}:
        return style_value
    return "general"


def _normalize_theme(theme: dict[str, Any], style_mode: str) -> dict[str, str]:
    defaults = {
        "general": {
            "background": "#F7F9FC",
            "secondary_background": "#FFFFFF",
            "primary": "#D94841",
            "accent": "#FF7A59",
            "secondary_accent": "#3850A0",
            "text": "#1F2937",
            "muted_text": "#6B7280",
            "border": "#D8DEE9",
        },
        "consulting": {
            "background": "#FFFFFF",
            "secondary_background": "#F6F8FB",
            "primary": "#0F4C81",
            "accent": "#2A7DE1",
            "secondary_accent": "#22A06B",
            "text": "#111827",
            "muted_text": "#6B7280",
            "border": "#D1D5DB",
        },
        "consulting_top": {
            "background": "#0F172A",
            "secondary_background": "#111C33",
            "primary": "#F5B83D",
            "accent": "#E76F51",
            "secondary_accent": "#60A5FA",
            "text": "#F8FAFC",
            "muted_text": "#CBD5E1",
            "border": "#334155",
        },
    }[style_mode]
    normalized = defaults.copy()
    for key in defaults:
        value = str(theme.get(key) or "").strip()
        if value.startswith("#") and len(value) in {4, 7}:
            normalized[key] = value
    return normalized


def _normalize_typography(typography: dict[str, Any]) -> dict[str, Any]:
    body_size = typography.get("body_size")
    try:
        body_size = int(body_size)
    except Exception:
        body_size = 20
    body_size = min(24, max(18, body_size))
    return {
        "title_font": typography.get("title_font") or "Microsoft YaHei",
        "body_font": typography.get("body_font") or "Microsoft YaHei",
        "emphasis_font": typography.get("emphasis_font") or "SimHei",
        "body_size": body_size,
    }


def _normalize_pages(strategy: dict[str, Any]) -> list[dict[str, Any]]:
    raw_pages = strategy.get("pages") or []
    normalized: list[dict[str, Any]] = []
    for index, page in enumerate(raw_pages, start=1):
        title = page.get("title") or f"Slide {index}"
        stem_base = page.get("file_stem") or ("cover" if index == 1 else slugify(title))
        normalized.append(
            {
                "index": index,
                "page_type": page.get("page_type") or ("cover" if index == 1 else "content"),
                "title": title,
                "subtitle": page.get("subtitle") or "",
                "layout": page.get("layout") or "content",
                "goal": page.get("goal") or title,
                "bullets": [str(item) for item in (page.get("bullets") or [])][:5],
                "chart_type": page.get("chart_type") or "",
                "image_filename": page.get("image_filename") or "",
                "file_stem": f"{index:02d}_{slugify(stem_base)}",
            }
        )
    if not normalized:
        normalized = [
            {"index": 1, "page_type": "cover", "title": strategy.get("presentation_title", "Presentation"), "subtitle": "", "layout": "cover", "goal": "Introduce the topic", "bullets": [], "chart_type": "", "image_filename": "", "file_stem": "01_cover"},
            {"index": 2, "page_type": "content", "title": "Overview", "subtitle": "", "layout": "content", "goal": "Summarize the key points", "bullets": ["Background", "Current state", "Recommendation"], "chart_type": "", "image_filename": "", "file_stem": "02_overview"},
            {"index": 3, "page_type": "ending", "title": "Conclusion", "subtitle": "", "layout": "ending", "goal": "Close with the core message", "bullets": ["Action items"], "chart_type": "", "image_filename": "", "file_stem": "03_conclusion"},
        ]
    normalized[0]["page_type"] = "cover"
    normalized[0]["file_stem"] = "01_cover"
    normalized[-1]["page_type"] = "ending"
    if not normalized[-1]["file_stem"].startswith(f"{normalized[-1]['index']:02d}_"):
        normalized[-1]["file_stem"] = f"{normalized[-1]['index']:02d}_{slugify(normalized[-1]['title'])}"
    return normalized[:8]


def _normalize_sections(sections: list[dict[str, Any]], page: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = []
    for section in sections[:4]:
        heading = str(section.get("heading") or "").strip()
        items = [str(item).strip() for item in (section.get("items") or []) if str(item).strip()]
        if heading or items:
            normalized.append({"heading": heading or page["title"], "items": items[:4]})
    if normalized:
        return normalized

    bullets = page.get("bullets") or []
    if not bullets:
        return []
    midpoint = 2 if len(bullets) > 3 else len(bullets)
    sections = [{"heading": "重点", "items": bullets[:midpoint]}]
    if bullets[midpoint:]:
        sections.append({"heading": "补充", "items": bullets[midpoint:]})
    return sections


def _normalize_kpis(kpis: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized = []
    for item in kpis[:3]:
        label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        if label and value:
            normalized.append({"label": label, "value": value})
    return normalized


def _normalize_image_choice(candidate: str, image_files: list[str]) -> str:
    if candidate in image_files:
        return candidate
    return ""


def _run_script(task_id: str, command: list[str]) -> None:
    STORE.append_log(task_id, f"Running command: {' '.join(command)}")
    result = subprocess.run(
        command,
        cwd=SETTINGS.repo_root,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.stdout.strip():
        STORE.append_log(task_id, result.stdout.strip())
    if result.stderr.strip():
        STORE.append_log(task_id, result.stderr.strip())
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")
