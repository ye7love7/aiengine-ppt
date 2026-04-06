from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional
from PIL import Image

from .config import SETTINGS
from .examples import extract_example_style_profile, load_example_prompt_context, resolve_example_dir
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
    "pixel_retro": "pixel_retro",
    "government_modern": "government_blue",
    "brand_modern": "smart_red",
    "psychology_healing": "psychology_attachment",
    "yijing_classic": "",
}


def _available_template_names() -> set[str]:
    layouts_root = SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts"
    if not layouts_root.exists():
        return set()
    return {path.name for path in layouts_root.iterdir() if path.is_dir()}


def _resolve_existing_template_name(candidate: Any, fallback_style: str = "") -> str:
    normalized = _normalize_template_name(candidate)
    available = _available_template_names()
    if normalized and normalized in available:
        return normalized
    fallback = _normalize_template_name(TEMPLATE_BY_STYLE.get(fallback_style, ""))
    if fallback and fallback in available:
        return fallback
    return ""


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
    example_profile = extract_example_style_profile(resolve_example_dir(example_reference)) if example_reference else None
    style_source = request_data.get("style_source") or ("example_strong" if example_reference else "prompt_reference")
    template_name = _normalize_template_name(request_data.get("template_name"))
    template_locked = bool(template_name)
    style_locked = bool(example_reference and style_source == "example_strong" and not template_locked)

    prefer_style = request_data.get("prefer_style") or "auto"
    if style_locked and example_profile and example_profile.get("style_tag"):
        prefer_style = str(example_profile["style_tag"])
    elif prefer_style == "auto" and example_context and example_context.get("suggested_style") in TEMPLATE_BY_STYLE:
        prefer_style = str(example_context["suggested_style"])
    style_hint = prefer_style if prefer_style != "auto" else "auto based on document type"
    ignored_template_name = ""
    if style_locked:
        if template_name:
            ignored_template_name = template_name
            STORE.append_log(task_id, f"Example strong reference enabled; ignoring explicit template {template_name}")
        template_name = _normalize_template_name(example_profile.get("recommended_template") if example_profile else "")
    elif template_name and example_reference:
        STORE.append_log(
            task_id,
            f"Explicit template {template_name} selected; example reference {example_reference} kept only as a secondary style hint.",
        )
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
Style source: {style_source}
Source material:
{source_bundle}
"""
    if example_context:
        prompt += f"""

Use the following local example only as a visual and structural style reference. Do not reuse its topic, facts, figures, or narrative unless they also appear in the user's source material.
Example name: {example_context['name']}
Suggested style: {example_context['suggested_style']}
Example summary: {example_context['summary'] or 'N/A'}
Example style profile:
{json.dumps(example_context.get('style_profile') or {}, ensure_ascii=False, indent=2)}
Example README excerpt:
{example_context['readme_excerpt'] or 'N/A'}

Example design_spec excerpt:
{example_context['design_spec_excerpt'] or 'N/A'}
"""
    if template_name and example_reference:
        prompt += f"""

Template precedence constraints:
- The user explicitly selected template `{template_name}`. Treat this template as the primary layout and composition constraint.
- The example reference may influence tone and detail rhythm, but it must not override or replace the selected template.
"""
    if style_locked and example_profile:
        prompt += f"""

Hard example-strong constraints:
- Lock the visual direction to this example style profile and do not fall back to generic business styling.
- Reuse the example's theme colors, typography tone, layout tags, and recommended template when they are present.
- Keep the content topic new, but keep the visual language aligned with the example.
"""
    strategy = LLM.chat_json(
        STRATEGIST_SYSTEM_PROMPT,
        prompt,
        max_tokens=6000,
        task_id=task_id,
        stage_label="strategist",
    )
    if example_reference:
        strategy["example_reference"] = example_reference
    strategy["style_source"] = style_source
    strategy["style_locked"] = style_locked
    strategy["example_style_profile"] = example_profile or {}
    strategy["canvas_format"] = request_data["canvas_format"]
    strategy["project_name"] = request_data["project_name"]
    if style_locked and example_profile:
        locked_style = str(example_profile.get("style_tag") or prefer_style or "general")
        strategy["style_mode"] = locked_style
        strategy["template_name"] = _resolve_existing_template_name(
            template_name or TEMPLATE_BY_STYLE.get(locked_style, ""),
            locked_style,
        )
    else:
        strategy["style_mode"] = _normalize_style(strategy.get("style_mode"), prefer_style)
        llm_template_name = _normalize_template_name(strategy.get("template_name"))
        strategy["template_name"] = _resolve_existing_template_name(
            template_name or llm_template_name or TEMPLATE_BY_STYLE.get(strategy.get("style_mode", "general"), ""),
            strategy["style_mode"],
        )
        if template_name and llm_template_name and llm_template_name != strategy["template_name"]:
            STORE.append_log(
                task_id,
                f"Strategist proposed template '{llm_template_name}', but explicit template '{strategy['template_name']}' takes precedence.",
            )
        elif llm_template_name and llm_template_name != strategy["template_name"]:
            STORE.append_log(
                task_id,
                f"Strategist proposed unknown template '{llm_template_name}', falling back to '{strategy['template_name'] or 'no template'}'.",
            )
        if not template_name and strategy["template_name"]:
            _copy_template(project_path, strategy["template_name"])
    strategy["pages"] = _normalize_pages(strategy)
    strategy["page_count"] = len(strategy["pages"])
    strategy["image_strategy"] = "user_provided" if image_inventory else "none"
    strategy["theme"] = _normalize_theme(
        strategy.get("theme") or {},
        strategy["style_mode"],
        locked_theme=(example_profile or {}).get("theme") if style_locked else None,
        visual_rules=(example_profile or {}).get("visual_rules") if style_locked else None,
    )
    strategy["typography"] = _normalize_typography(
        strategy.get("typography") or {},
        locked_typography=(example_profile or {}).get("typography") if style_locked else None,
    )
    strategy["resolved_template_name"] = strategy.get("template_name") or ""
    strategy["resolved_style_mode"] = strategy.get("style_mode") or "general"
    strategy["ignored_template_name"] = ignored_template_name

    (project_path / "strategy.json").write_text(json.dumps(strategy, ensure_ascii=False, indent=2), encoding="utf-8")
    (project_path / "design_spec.md").write_text(
        strategy_to_design_spec(strategy, image_inventory, request_data["project_name"], request_data["canvas_format"]),
        encoding="utf-8",
    )
    STORE.write_stage_metadata(task_id, "strategist", strategy)
    STORE.update_state(
        task_id,
        stage_details={
            "style_summary": {
                "style_source": style_source,
                "example_reference": example_reference or "",
                "resolved_template_name": strategy["resolved_template_name"],
                "resolved_style_mode": strategy["resolved_style_mode"],
                "style_locked": style_locked,
                "ignored_template_name": ignored_template_name,
            }
        },
    )
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
Example style profile: {json.dumps(strategy.get('example_style_profile') or {}, ensure_ascii=False)}
Available local images: {image_files}
Previous slide summary: {previous_summary or 'None'}
Current page plan: {json.dumps(page, ensure_ascii=False)}
"""
        blueprint = LLM.chat_json(
            EXECUTOR_SYSTEM_PROMPT,
            prompt,
            max_tokens=3000,
            task_id=task_id,
            stage_label=f"executor_{file_stem}",
        )
        blueprint["index"] = page["index"]
        blueprint["file_stem"] = blueprint.get("file_stem") or page["file_stem"]
        blueprint["page_type"] = page["page_type"]
        blueprint["title"] = blueprint.get("title") or page["title"]
        blueprint["subtitle"] = blueprint.get("subtitle") or page.get("subtitle", "")
        blueprint["image_filename"] = _normalize_image_choice(blueprint.get("image_filename", ""), image_files)
        blueprint["sections"] = _normalize_sections(blueprint.get("sections") or [], page)
        blueprint["kpis"] = _normalize_kpis(blueprint.get("kpis") or [])
        blueprint["content_archetype"] = page.get("content_archetype") or _normalize_content_archetype(
            blueprint.get("content_archetype"),
            page["page_type"],
            page.get("layout", ""),
            blueprint["sections"],
            blueprint["kpis"],
            blueprint["image_filename"],
        )
        blueprint["speaker_notes"] = blueprint.get("speaker_notes") or page.get("goal", page["title"])
        blueprint["key_points"] = blueprint.get("key_points") or page.get("bullets", [])[:3]
        blueprint["duration_minutes"] = float(blueprint.get("duration_minutes") or 1.0)

        svg_content = render_slide_svg(blueprint, strategy, project_path / "images", project_path / "templates")
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


def _normalize_template_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower() in {"auto", "none", "null", "default"}:
        return ""
    return text


def _normalize_style(style_value: Optional[str], preferred: str) -> str:
    if preferred in TEMPLATE_BY_STYLE:
        return preferred
    if style_value in TEMPLATE_BY_STYLE:
        return style_value
    return "general"


def _normalize_theme(
    theme: dict[str, Any],
    style_mode: str,
    locked_theme: Optional[dict[str, Any]] = None,
    visual_rules: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    defaults_by_style = {
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
        "pixel_retro": {
            "background": "#0D1117",
            "secondary_background": "#161B22",
            "primary": "#39FF14",
            "accent": "#00D4FF",
            "secondary_accent": "#FF2E97",
            "text": "#E6EDF3",
            "muted_text": "#8B949E",
            "border": "#30363D",
        },
        "government_modern": {
            "background": "#F8FAFF",
            "secondary_background": "#FFFFFF",
            "primary": "#0D4EA6",
            "accent": "#1C7ED6",
            "secondary_accent": "#4DABF7",
            "text": "#102A43",
            "muted_text": "#486581",
            "border": "#D9E2EC",
        },
        "brand_modern": {
            "background": "#FFF9F5",
            "secondary_background": "#FFFFFF",
            "primary": "#C7512D",
            "accent": "#F28C28",
            "secondary_accent": "#2E86AB",
            "text": "#1F2933",
            "muted_text": "#52606D",
            "border": "#E5E7EB",
        },
        "psychology_healing": {
            "background": "#FAFCFF",
            "secondary_background": "#FFFFFF",
            "primary": "#5A7D9A",
            "accent": "#7BC6CC",
            "secondary_accent": "#F4A261",
            "text": "#34495E",
            "muted_text": "#6C7A89",
            "border": "#D6E4F0",
        },
        "yijing_classic": {
            "background": "#0D1117",
            "secondary_background": "#F5F3EF",
            "primary": "#B8860B",
            "accent": "#C94C4C",
            "secondary_accent": "#2D5A5A",
            "text": "#E8E4DC",
            "muted_text": "#8B9A9A",
            "border": "#4A5568",
        },
    }
    defaults = defaults_by_style.get(style_mode, defaults_by_style["general"])
    normalized = defaults.copy()
    for key, value in (locked_theme or {}).items():
        text = str(value or "").strip()
        if text.startswith("#") and len(text) == 7:
            normalized[key] = text.upper()
    for key in defaults:
        value = str(theme.get(key) or "").strip()
        if value.startswith("#") and len(value) in {4, 7}:
            normalized[key] = value
    if visual_rules and visual_rules.get("background_mode") == "dark":
        normalized["background"] = normalized.get("background", "#0F172A")
        normalized["secondary_background"] = normalized.get("secondary_background", "#111C33")
    return normalized


def _normalize_typography(typography: dict[str, Any], locked_typography: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    body_size = typography.get("body_size")
    try:
        body_size = int(body_size)
    except Exception:
        body_size = locked_typography.get("body_size") if locked_typography else 20
    body_size = min(24, max(18, body_size))
    return {
        "title_font": typography.get("title_font") or (locked_typography or {}).get("title_font") or "Microsoft YaHei",
        "body_font": typography.get("body_font") or (locked_typography or {}).get("body_font") or "Microsoft YaHei",
        "emphasis_font": typography.get("emphasis_font") or (locked_typography or {}).get("emphasis_font") or "SimHei",
        "body_size": body_size,
    }


def _normalize_pages(strategy: dict[str, Any]) -> list[dict[str, Any]]:
    raw_pages = strategy.get("pages") or []
    example_profile = strategy.get("example_style_profile") or {}
    example_page_archetypes = example_profile.get("page_archetypes") or {}
    normalized: list[dict[str, Any]] = []
    for index, page in enumerate(raw_pages, start=1):
        title = page.get("title") or f"Slide {index}"
        stem_base = page.get("file_stem") or ("cover" if index == 1 else slugify(title))
        page_type = page.get("page_type") or ("cover" if index == 1 else "content")
        normalized.append(
            {
                "index": index,
                "page_type": page_type,
                "content_archetype": _normalize_content_archetype(
                    page.get("content_archetype"),
                    page_type,
                    page.get("layout") or "content",
                    page.get("sections") or [],
                    page.get("kpis") or [],
                    page.get("image_filename") or "",
                ),
                "title": title,
                "subtitle": page.get("subtitle") or "",
                "layout": page.get("layout") or "content",
                "goal": page.get("goal") or title,
                "bullets": [str(item) for item in (page.get("bullets") or [])][:5],
                "chart_type": page.get("chart_type") or "",
                "image_filename": page.get("image_filename") or "",
                "file_stem": f"{index:02d}_{slugify(stem_base)}",
                "example_archetype": example_page_archetypes.get(page_type, ""),
            }
        )
    if not normalized:
        normalized = [
            {"index": 1, "page_type": "cover", "content_archetype": "empty", "title": strategy.get("presentation_title", "Presentation"), "subtitle": "", "layout": "cover", "goal": "Introduce the topic", "bullets": [], "chart_type": "", "image_filename": "", "file_stem": "01_cover"},
            {"index": 2, "page_type": "content", "content_archetype": "lead_cards", "title": "Overview", "subtitle": "", "layout": "content", "goal": "Summarize the key points", "bullets": ["Background", "Current state", "Recommendation"], "chart_type": "", "image_filename": "", "file_stem": "02_overview"},
            {"index": 3, "page_type": "ending", "content_archetype": "empty", "title": "Conclusion", "subtitle": "", "layout": "ending", "goal": "Close with the core message", "bullets": ["Action items"], "chart_type": "", "image_filename": "", "file_stem": "03_conclusion"},
        ]
    normalized[0]["page_type"] = "cover"
    normalized[0]["file_stem"] = "01_cover"
    normalized[-1]["page_type"] = "ending"
    if not normalized[-1]["file_stem"].startswith(f"{normalized[-1]['index']:02d}_"):
        normalized[-1]["file_stem"] = f"{normalized[-1]['index']:02d}_{slugify(normalized[-1]['title'])}"
    return normalized[:8]


def _normalize_content_archetype(
    value: Any,
    page_type: str,
    layout: str,
    sections: list[dict[str, Any]] | list[Any],
    kpis: list[dict[str, Any]] | list[Any],
    image_filename: str,
) -> str:
    allowed = {"lead_cards", "dual_column", "kpi_row", "list_grid", "image_left_text_right", "empty"}
    text = str(value or "").strip().lower()
    if text in allowed:
        return text

    if page_type != "content":
        return "empty"

    layout_text = str(layout or "").strip().lower()
    if "three_column" in layout_text or "grid" in layout_text:
        return "list_grid"
    if "split" in layout_text or "two_column" in layout_text or "dual" in layout_text:
        return "dual_column"
    if "timeline" in layout_text:
        return "lead_cards"

    if image_filename:
        return "image_left_text_right"
    if kpis:
        return "kpi_row"
    section_count = len(sections or [])
    if section_count >= 3:
        return "list_grid"
    if section_count == 2:
        return "dual_column"
    return "lead_cards"


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
