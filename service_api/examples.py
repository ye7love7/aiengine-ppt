from __future__ import annotations

import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import SETTINGS
from .llm import LLM
from .models import ArtifactEntry


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg"}
_SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
_HEX_RE = re.compile(r"`?(#[0-9A-Fa-f]{6})`?")
_CLASSIFIER_PROMPT_VERSION = "example-style-classifier-v1"
_STYLE_REGISTRY_VERSION = "style-registry-v1"
_STYLE_REGISTRY: dict[str, dict[str, Any]] = {
    "general": {
        "description": "通用商务演示风格，强调清晰结构和稳妥信息呈现。",
        "template_candidates": ["smart_red"],
        "default_template": "smart_red",
        "render_family": "general",
    },
    "consulting": {
        "description": "高端咨询风，强调结构化分析、结论先行和整齐卡片布局。",
        "template_candidates": ["mckinsey", "exhibit"],
        "default_template": "mckinsey",
        "render_family": "consulting",
    },
    "consulting_top": {
        "description": "顶级咨询/董事会风，强调 exhibits、深色背景和高密度信息组织。",
        "template_candidates": ["exhibit", "mckinsey"],
        "default_template": "exhibit",
        "render_family": "consulting_top",
    },
    "pixel_retro": {
        "description": "像素复古游戏风，强调 HUD、像素边框、霓虹高对比配色。",
        "template_candidates": ["pixel_retro"],
        "default_template": "pixel_retro",
        "render_family": "pixel_retro",
    },
    "government_modern": {
        "description": "现代政务汇报风，强调权威蓝系、规整结构和正式表达。",
        "template_candidates": ["government_blue", "government_red"],
        "default_template": "government_blue",
        "render_family": "government_modern",
    },
    "brand_modern": {
        "description": "品牌现代风，强调品牌色、营销感和简洁视觉节奏。",
        "template_candidates": ["smart_red", "google_style"],
        "default_template": "smart_red",
        "render_family": "brand_modern",
    },
    "psychology_healing": {
        "description": "心理疗愈风，强调柔和色彩、治愈感和情绪引导。",
        "template_candidates": ["psychology_attachment"],
        "default_template": "psychology_attachment",
        "render_family": "psychology_healing",
    },
    "yijing_classic": {
        "description": "易理玄学风，强调阴阳、爻象、古铜金、玄黑与素白对照。",
        "template_candidates": [],
        "default_template": "",
        "render_family": "yijing_classic",
    },
}
_STYLE_TAG_MAP = {
    "pixel": "pixel_retro",
    "像素": "pixel_retro",
    "retro": "pixel_retro",
    "政府": "government_modern",
    "政务": "government_modern",
    "咨询": "consulting",
    "consulting": "consulting",
    "therapy": "psychology_healing",
    "psychology": "psychology_healing",
    "心理": "psychology_healing",
    "品牌": "brand_modern",
    "brand": "brand_modern",
    "易理": "yijing_classic",
    "周易": "yijing_classic",
    "卦": "yijing_classic",
    "阴阳": "yijing_classic",
    "玄学": "yijing_classic",
    "太极": "yijing_classic",
}
_THEME_ROLE_PATTERNS = {
    "background": ["主背景", "主背景色", "背景色", "玄天黑", "deep background", "background"],
    "secondary_background": ["辅背景", "辅助背景", "次背景", "素地白", "卡片底色", "secondary bg", "secondary background"],
    "primary": ["主色", "金石", "古铜金", "primary"],
    "accent": ["强调", "朱砂红", "accent", "阳爻"],
    "secondary_accent": ["辅助", "墨青灰", "secondary accent", "阴爻", "山色"],
    "text": ["主文本", "正文颜色", "body text", "text"],
    "muted_text": ["次文本", "secondary text", "muted text"],
    "border": ["边框", "分隔", "border", "divider"],
}
_TYPOGRAPHY_ROLE_PATTERNS = {
    "title_font": ["title", "h0", "h1", "标题", "封面大标题", "页面标题"],
    "body_font": ["body", "正文", "small", "quote"],
    "emphasis_font": ["emphasis", "强调", "h2", "h3"],
}
_STYLE_PRIORITY = [
    "yijing_classic",
    "pixel_retro",
    "government_modern",
    "consulting_top",
    "consulting",
    "brand_modern",
    "psychology_healing",
]


def list_examples() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted(SETTINGS.examples_root.iterdir(), key=lambda item: item.name.lower()):
        if path.is_dir():
            results.append(_build_example_metadata(path))
    return results


def get_example_detail(name: str) -> dict[str, Any]:
    example_dir = resolve_example_dir(name)
    style_profile = extract_example_style_profile(example_dir)
    return {
        "example": _build_example_metadata(example_dir),
        "artifacts": [artifact.model_dump() for artifact in build_example_artifacts(example_dir)],
        "preview": {
            "readme_excerpt": _read_excerpt(example_dir / "README.md", 2400),
            "design_spec_excerpt": _read_excerpt(example_dir / "design_spec.md", 6000),
        },
        "style_profile": style_profile,
    }


def validate_example_reference(name: str | None) -> str | None:
    if not name:
        return None
    resolve_example_dir(name)
    return name


def load_example_prompt_context(name: str) -> dict[str, Any]:
    example_dir = resolve_example_dir(name)
    metadata = _build_example_metadata(example_dir)
    style_profile = extract_example_style_profile(example_dir)
    return {
        "name": metadata["name"],
        "suggested_style": metadata["suggested_style"],
        "summary": metadata["summary"],
        "readme_excerpt": _read_excerpt(example_dir / "README.md", 2400),
        "design_spec_excerpt": _read_excerpt(example_dir / "design_spec.md", 8000),
        "style_profile": style_profile,
    }


def extract_example_style_profile(example_dir: Path) -> dict[str, Any]:
    suggested_style = _infer_style(example_dir.name)
    design_spec_text = _read_excerpt(example_dir / "design_spec.md", 24000)
    svg_dir = example_dir / "svg_final"
    if not svg_dir.exists():
        svg_dir = example_dir / "svg_output"

    rule_style_tag = _infer_style_tag(example_dir.name, design_spec_text, suggested_style)
    svg_profile = _extract_svg_profile(svg_dir, rule_style_tag)
    theme = _extract_theme_from_design_spec(design_spec_text, rule_style_tag)
    typography = _extract_typography_from_design_spec(design_spec_text, rule_style_tag)
    rule_template = _resolve_recommended_template(rule_style_tag, example_dir.name)

    classification = _resolve_example_style_classification(
        example_dir=example_dir,
        design_spec_text=design_spec_text,
        svg_dir=svg_dir,
        suggested_style=suggested_style,
        theme=theme,
        typography=typography,
        svg_profile=svg_profile,
        rule_style_tag=rule_style_tag,
        rule_template=rule_template,
    )

    final_style_tag = classification["style_tag"]
    if final_style_tag != rule_style_tag:
        svg_profile = _extract_svg_profile(svg_dir, final_style_tag)
        theme = _extract_theme_from_design_spec(design_spec_text, final_style_tag)
        typography = _extract_typography_from_design_spec(design_spec_text, final_style_tag)

    return {
        "style_tag": final_style_tag,
        "suggested_style": suggested_style,
        "recommended_template": classification["recommended_template"],
        "theme": theme,
        "typography": typography,
        "layout_tags": svg_profile["layout_tags"],
        "page_layout_map": svg_profile["page_layout_map"],
        "page_archetypes": svg_profile["page_archetypes"],
        "visual_rules": svg_profile["visual_rules"],
        "can_extract_svg": svg_profile["can_extract_svg"],
        "fallback_reason": svg_profile["fallback_reason"],
        "style_source": classification["style_source"],
        "style_confidence": classification["confidence"],
        "style_reason": classification["reason"],
        "style_classification": classification,
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
        candidates.append(("svg_pptx" if pptx_path.name.endswith("_svg.pptx") else "native_pptx", pptx_path, "file"))
    for name, path, kind in candidates:
        if path.exists():
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
    return Path(shutil.make_archive(str(archive_base), "zip", root_dir=source))


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
    style_profile = extract_example_style_profile(example_dir) if (example_dir / "design_spec.md").exists() else None
    return {
        "name": example_dir.name,
        "title": example_dir.name,
        "relative_path": str(example_dir.relative_to(SETTINGS.repo_root)),
        "page_count": len([path for path in svg_dir.glob("*.svg") if path.is_file()]) if svg_dir.exists() else 0,
        "image_count": len([path for path in (example_dir / "images").glob("*") if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES]) if (example_dir / "images").exists() else 0,
        "has_design_spec": (example_dir / "design_spec.md").exists(),
        "has_readme": (example_dir / "README.md").exists(),
        "has_native_pptx": any(path.is_file() and not path.name.endswith("_svg.pptx") for path in example_dir.glob("*.pptx")),
        "has_svg_pptx": any(path.is_file() and path.name.endswith("_svg.pptx") for path in example_dir.glob("*.pptx")),
        "suggested_style": _infer_style(example_dir.name),
        "summary": _extract_summary(example_dir),
        "recommended_template": style_profile["recommended_template"] if style_profile else "",
        "style_tag": style_profile["style_tag"] if style_profile else _infer_style(example_dir.name),
        "style_source": style_profile["style_source"] if style_profile else "rule_fallback",
        "style_confidence": style_profile["style_confidence"] if style_profile else 0.0,
        "style_reason": style_profile["style_reason"] if style_profile else "",
        "can_extract_svg": bool(style_profile and style_profile["can_extract_svg"]),
    }


def _resolve_example_style_classification(
    *,
    example_dir: Path,
    design_spec_text: str,
    svg_dir: Path,
    suggested_style: str,
    theme: dict[str, str],
    typography: dict[str, Any],
    svg_profile: dict[str, Any],
    rule_style_tag: str,
    rule_template: str,
) -> dict[str, Any]:
    fingerprint = _build_example_classifier_fingerprint(example_dir, design_spec_text, svg_dir)
    cached = _load_cached_style_classification(example_dir.name, fingerprint)
    if cached:
        return cached

    fallback = _build_rule_fallback_decision(rule_style_tag, rule_template)
    try:
        classified = _classify_style_with_llm(
            example_dir=example_dir,
            design_spec_text=design_spec_text,
            suggested_style=suggested_style,
            theme=theme,
            typography=typography,
            svg_profile=svg_profile,
            rule_style_tag=rule_style_tag,
            rule_template=rule_template,
        )
    except Exception:
        return fallback

    result = _sanitize_classifier_output(classified, fallback)
    _write_cached_style_classification(example_dir.name, fingerprint, result)
    return result


def _classify_style_with_llm(
    *,
    example_dir: Path,
    design_spec_text: str,
    suggested_style: str,
    theme: dict[str, str],
    typography: dict[str, Any],
    svg_profile: dict[str, Any],
    rule_style_tag: str,
    rule_template: str,
) -> dict[str, Any]:
    registry_prompt = []
    for style_tag, config in _STYLE_REGISTRY.items():
        registry_prompt.append(
            {
                "style_tag": style_tag,
                "description": config["description"],
                "template_candidates": config["template_candidates"],
                "default_template": config["default_template"],
                "render_family": config.get("render_family", style_tag),
            }
        )
    system_prompt = """You classify a presentation example into one registered style family.

Rules:
- Output valid JSON only.
- You must select style_tag from the provided registry only.
- recommended_template must be one of that style's template_candidates, or empty string if none applies.
- Do not invent new style tags or templates.
- Do not generate theme colors, typography, content, or SVG.

Return this schema:
{
  "style_tag": "string",
  "recommended_template": "string",
  "confidence": 0.0,
  "reason": "short string"
}
"""
    user_prompt = json.dumps(
        {
            "example_name": example_dir.name,
            "suggested_style": suggested_style,
            "rule_fallback": {
                "style_tag": rule_style_tag,
                "recommended_template": rule_template,
            },
            "style_registry": registry_prompt,
            "theme_summary": theme,
            "typography_summary": typography,
            "svg_summary": {
                "layout_tags": svg_profile.get("layout_tags") or [],
                "page_archetypes": svg_profile.get("page_archetypes") or {},
                "visual_rules": svg_profile.get("visual_rules") or {},
            },
            "design_spec_excerpt": design_spec_text[:8000],
        },
        ensure_ascii=False,
        indent=2,
    )
    return LLM.chat_json(system_prompt, user_prompt, max_tokens=1200)


def _sanitize_classifier_output(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    style_tag = str(payload.get("style_tag") or "").strip()
    if style_tag not in _STYLE_REGISTRY:
        return fallback
    candidates = _STYLE_REGISTRY[style_tag]["template_candidates"]
    recommended_template = str(payload.get("recommended_template") or "").strip()
    if recommended_template and recommended_template not in candidates:
        recommended_template = ""
    if not recommended_template:
        recommended_template = _STYLE_REGISTRY[style_tag]["default_template"]
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(payload.get("reason") or "").strip()[:240]
    return {
        "style_tag": style_tag,
        "recommended_template": recommended_template,
        "confidence": confidence,
        "reason": reason or fallback["reason"],
        "style_source": "llm_classified",
        "classifier_model": SETTINGS.llm_model,
        "prompt_version": _CLASSIFIER_PROMPT_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _build_rule_fallback_decision(style_tag: str, recommended_template: str) -> dict[str, Any]:
    return {
        "style_tag": style_tag,
        "recommended_template": recommended_template,
        "confidence": 0.0,
        "reason": "Fallback to local rule-based style inference.",
        "style_source": "rule_fallback",
        "classifier_model": "",
        "prompt_version": _CLASSIFIER_PROMPT_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _build_example_classifier_fingerprint(example_dir: Path, design_spec_text: str, svg_dir: Path) -> str:
    svg_signature = []
    if svg_dir.exists():
        for path in sorted(svg_dir.glob("*.svg"))[:40]:
            svg_signature.append({"name": path.name, "mtime_ns": path.stat().st_mtime_ns, "size": path.stat().st_size})
    payload = {
        "example_name": example_dir.name,
        "design_spec_sha256": hashlib.sha256(design_spec_text.encode("utf-8", errors="replace")).hexdigest(),
        "svg_signature": svg_signature,
        "style_registry_version": _STYLE_REGISTRY_VERSION,
        "prompt_version": _CLASSIFIER_PROMPT_VERSION,
        "llm_model": SETTINGS.llm_model,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _style_cache_path(example_name: str) -> Path:
    safe_name = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "_", example_name).strip("_") or "example"
    return SETTINGS.example_style_cache_root / f"{safe_name}.json"


def _load_cached_style_classification(example_name: str, fingerprint: str) -> dict[str, Any] | None:
    path = _style_cache_path(example_name)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("fingerprint") != fingerprint:
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    return result


def _write_cached_style_classification(example_name: str, fingerprint: str, result: dict[str, Any]) -> None:
    path = _style_cache_path(example_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "example_name": example_name,
        "fingerprint": fingerprint,
        "result": result,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _infer_style_tag(name: str, design_spec_text: str, suggested_style: str) -> str:
    haystack = f"{name}\n{design_spec_text}".lower()
    for style_tag in _STYLE_PRIORITY:
        needles = [needle for needle, mapped in _STYLE_TAG_MAP.items() if mapped == style_tag]
        if any(needle.lower() in haystack for needle in needles):
            return style_tag
    return suggested_style or "general"


def _resolve_recommended_template(style_tag: str, example_name: str) -> str:
    config = _STYLE_REGISTRY.get(style_tag) or {}
    default_template = str(config.get("default_template") or "")
    if default_template:
        return default_template
    lowered = example_name.lower()
    if "pixel" in lowered or "像素" in example_name:
        return "pixel_retro"
    return ""


def _extract_theme_from_design_spec(text: str, style_tag: str) -> dict[str, str]:
    theme: dict[str, str] = {}
    for raw_line in text.splitlines():
        if "|" not in raw_line:
            continue
        match = _HEX_RE.search(raw_line)
        if not match:
            continue
        line = raw_line.replace("`", "")
        color = match.group(1).upper()
        lower_line = line.lower()
        for key, patterns in _THEME_ROLE_PATTERNS.items():
            if any(pattern.lower() in lower_line for pattern in patterns):
                theme.setdefault(key, color)
    if style_tag == "yijing_classic":
        theme.setdefault("background", "#0D1117")
        theme.setdefault("secondary_background", "#F5F3EF")
        theme.setdefault("primary", "#B8860B")
        theme.setdefault("accent", "#C94C4C")
        theme.setdefault("secondary_accent", "#2D5A5A")
        theme.setdefault("text", "#E8E4DC")
        theme.setdefault("muted_text", "#8B9A9A")
        theme.setdefault("border", "#4A5568")
    return theme


def _extract_typography_from_design_spec(text: str, style_tag: str) -> dict[str, Any]:
    typography: dict[str, Any] = {}

    font_block = re.search(r"font-family\s*:\s*([^;]+);", text, re.IGNORECASE)
    if font_block:
        value = font_block.group(1).strip()
        typography["title_font"] = value
        typography["body_font"] = value
        typography["emphasis_font"] = value

    for raw_line in text.splitlines():
        if "|" not in raw_line:
            continue
        columns = [part.strip().strip("*`") for part in raw_line.split("|") if part.strip()]
        if len(columns) < 2:
            continue
        role = columns[0].lower()
        value = columns[-1]
        if "px" in value:
            match = re.search(r"(\d{2})", value)
            if match and ("body" in role or "正文" in role):
                typography["body_size"] = int(match.group(1))
        for key, patterns in _TYPOGRAPHY_ROLE_PATTERNS.items():
            if any(pattern.lower() in role for pattern in patterns):
                if any(font_name in value for font_name in ['"', "Microsoft", "PingFang", "Noto", "system-ui", "sans-serif"]):
                    typography[key] = value

    if style_tag == "yijing_classic":
        font_family = typography.get("body_font") or '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", system-ui, sans-serif'
        typography.setdefault("title_font", font_family)
        typography.setdefault("body_font", font_family)
        typography.setdefault("emphasis_font", font_family)
        typography.setdefault("body_size", 18)
    return typography


def _extract_svg_profile(svg_dir: Path, style_tag: str) -> dict[str, Any]:
    if not svg_dir.exists():
        return {
            "layout_tags": [],
            "page_layout_map": {},
            "page_archetypes": {},
            "visual_rules": {},
            "can_extract_svg": False,
            "fallback_reason": "svg_final/svg_output missing",
        }

    layout_tags: Counter[str] = Counter()
    page_layout_map: dict[str, dict[str, Any]] = {}
    page_archetypes: dict[str, str] = {}
    title_band_heights: list[float] = []
    fill_colors: Counter[str] = Counter()
    rect_radii: list[float] = []

    for svg_path in sorted(svg_dir.glob("*.svg"))[:20]:
        try:
            root = ET.parse(svg_path).getroot()
        except Exception:
            continue
        rects = root.findall(".//svg:rect", _SVG_NS)
        texts = root.findall(".//svg:text", _SVG_NS)
        bands: list[float] = []
        for rect in rects:
            fill = (rect.get("fill") or "").upper()
            if fill.startswith("#"):
                fill_colors[fill] += 1
            try:
                rect_radii.append(float(rect.get("rx") or 0))
            except ValueError:
                pass
            try:
                y = float(rect.get("y") or 0)
                h = float(rect.get("height") or 0)
            except ValueError:
                continue
            if y <= 120 and h <= 140:
                bands.append(h)
        if bands:
            title_band_heights.append(max(bands))

        page_kind = _infer_page_kind(svg_path.stem)
        archetype = _infer_svg_archetype(svg_path.stem, len(rects), len(texts), style_tag)
        page_archetypes[page_kind] = archetype
        page_layout_map[svg_path.stem] = {
            "rect_count": len(rects),
            "text_count": len(texts),
            "title_band_height": max(bands) if bands else 0,
            "page_kind": page_kind,
            "archetype": archetype,
        }
        if len(rects) >= 6:
            layout_tags["card_grid"] += 1
        if len(texts) >= 8:
            layout_tags["dense_text"] += 1
        if page_kind == "toc":
            layout_tags["toc"] += 1

    top_colors = [color for color, _ in fill_colors.most_common(4)]
    return {
        "layout_tags": [tag for tag, _ in layout_tags.most_common(4)],
        "page_layout_map": page_layout_map,
        "page_archetypes": page_archetypes,
        "visual_rules": {
            "dominant_colors": top_colors,
            "background_mode": "dark" if top_colors and top_colors[0] in {"#0D1117", "#111827", "#0F172A"} else "light",
            "title_band_height": round(sum(title_band_heights) / len(title_band_heights), 1) if title_band_heights else 0,
            "panel_radius": round(sum(rect_radii) / len(rect_radii), 1) if rect_radii else 0,
            "frame_style": "sharp" if (round(sum(rect_radii) / len(rect_radii), 1) if rect_radii else 0) <= 6 else "soft",
        },
        "can_extract_svg": bool(page_layout_map),
        "fallback_reason": "" if page_layout_map else "svg parsing yielded no usable structural features",
    }


def _infer_page_kind(stem: str) -> str:
    lowered = stem.lower()
    if any(token in lowered for token in ["cover", "封面"]):
        return "cover"
    if any(token in lowered for token in ["toc", "navigation", "目录", "目录导航"]):
        return "toc"
    if any(token in lowered for token in ["summary", "ending", "conclusion", "结论", "总结", "感谢页", "感谢"]):
        return "ending"
    return "content"


def _infer_svg_archetype(stem: str, rect_count: int, text_count: int, style_tag: str) -> str:
    page_kind = _infer_page_kind(stem)
    lowered = stem.lower()
    if style_tag == "pixel_retro":
        if page_kind == "cover":
            return "pixel_cover_hud"
        if page_kind == "toc":
            return "pixel_navigation_list"
        if page_kind == "ending":
            return "pixel_summary_board"
        if "vs" in lowered or "compare" in lowered:
            return "pixel_compare_board"
        if rect_count >= 10:
            return "pixel_triple_panel"
        if text_count >= 10:
            return "pixel_dense_panel"
        return "pixel_dual_panel"
    if style_tag == "yijing_classic":
        if page_kind == "cover":
            return "yijing_cover_taiji"
        if page_kind == "toc":
            return "yijing_toc_scroll"
        if page_kind == "ending":
            return "yijing_ending_quote"
        if "六爻" in stem or "卦" in stem:
            return "yijing_lines_panel"
        if rect_count >= 3 and text_count >= 18:
            return "yijing_dual_panel"
        return "yijing_text_panel"
    if page_kind == "cover":
        return "cover_focus"
    if page_kind == "toc":
        return "toc_list"
    if page_kind == "ending":
        return "ending_summary"
    return "content_panel"
