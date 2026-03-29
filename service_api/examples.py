from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from .config import SETTINGS
from .models import ArtifactEntry


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg"}
_SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
_HEX_RE = re.compile(r"`?(#[0-9A-Fa-f]{6})`?")
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
}
_RECOMMENDED_TEMPLATE_BY_STYLE = {
    "pixel_retro": "pixel_retro",
    "government_modern": "government_blue",
    "consulting": "mckinsey",
    "consulting_top": "exhibit",
    "psychology_healing": "psychology_attachment",
    "brand_modern": "smart_red",
    "general": "",
}


def list_examples() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted(SETTINGS.examples_root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir():
            continue
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
    design_spec_text = _read_excerpt(example_dir / "design_spec.md", 20000)
    svg_dir = example_dir / "svg_final"
    if not svg_dir.exists():
        svg_dir = example_dir / "svg_output"

    theme = _extract_theme_from_design_spec(design_spec_text)
    typography = _extract_typography_from_design_spec(design_spec_text)
    svg_profile = _extract_svg_profile(svg_dir)
    style_tag = _infer_style_tag(example_dir.name, design_spec_text, suggested_style)
    recommended_template = _resolve_recommended_template(style_tag, example_dir.name)

    return {
        "style_tag": style_tag,
        "suggested_style": suggested_style,
        "recommended_template": recommended_template,
        "theme": theme,
        "typography": typography,
        "layout_tags": svg_profile["layout_tags"],
        "page_layout_map": svg_profile["page_layout_map"],
        "page_archetypes": svg_profile["page_archetypes"],
        "visual_rules": svg_profile["visual_rules"],
        "can_extract_svg": svg_profile["can_extract_svg"],
        "fallback_reason": svg_profile["fallback_reason"],
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
    style_profile = extract_example_style_profile(example_dir) if (example_dir / "design_spec.md").exists() else None
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
        "recommended_template": style_profile["recommended_template"] if style_profile else "",
        "style_tag": style_profile["style_tag"] if style_profile else _infer_style(example_dir.name),
        "can_extract_svg": bool(style_profile and style_profile["can_extract_svg"]),
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


def _infer_style_tag(name: str, design_spec_text: str, suggested_style: str) -> str:
    haystack = f"{name}\n{design_spec_text}".lower()
    for needle, style_tag in _STYLE_TAG_MAP.items():
        if needle in haystack:
            return style_tag
    return suggested_style or "general"


def _resolve_recommended_template(style_tag: str, example_name: str) -> str:
    if style_tag in _RECOMMENDED_TEMPLATE_BY_STYLE:
        return _RECOMMENDED_TEMPLATE_BY_STYLE[style_tag]
    lowered = example_name.lower()
    if "pixel" in lowered or "像素" in example_name:
        return "pixel_retro"
    return ""


def _extract_theme_from_design_spec(text: str) -> dict[str, str]:
    role_map = {
        "background": "background",
        "secondary bg": "secondary_background",
        "secondary background": "secondary_background",
        "primary": "primary",
        "accent": "accent",
        "secondary accent": "secondary_accent",
        "body text": "text",
        "text": "text",
        "secondary text": "muted_text",
        "muted text": "muted_text",
        "border/divider": "border",
        "border": "border",
    }
    theme: dict[str, str] = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        columns = [part.strip().strip("*`") for part in line.split("|")]
        if len(columns) < 4:
            continue
        role = columns[1].lower()
        color = columns[2] if columns[2].startswith("#") else columns[3]
        match = _HEX_RE.search(color)
        if not match:
            continue
        key = role_map.get(role)
        if key:
            theme[key] = match.group(1).upper()
    return theme


def _extract_typography_from_design_spec(text: str) -> dict[str, Any]:
    role_map = {
        "title": "title_font",
        "body": "body_font",
        "emphasis": "emphasis_font",
    }
    typography: dict[str, Any] = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        columns = [part.strip().strip("*`") for part in line.split("|")]
        if len(columns) < 4:
            continue
        role = columns[1].lower()
        value = columns[2] or columns[3]
        key = role_map.get(role)
        if key and value:
            typography[key] = value
        if "body size" in role:
            match = re.search(r"(\d{2})", value)
            if match:
                typography["body_size"] = int(match.group(1))
    return typography


def _extract_svg_profile(svg_dir: Path) -> dict[str, Any]:
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

    for svg_path in sorted(svg_dir.glob("*.svg"))[:10]:
        try:
            tree = ET.parse(svg_path)
            root = tree.getroot()
        except Exception:
            continue
        rects = root.findall(".//svg:rect", _SVG_NS)
        texts = root.findall(".//svg:text", _SVG_NS)
        bands = []
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
                height = float(rect.get("height") or 0)
            except ValueError:
                continue
            if y <= 24 and height <= 120:
                bands.append(height)
        if bands:
            title_band_heights.append(max(bands))

        text_count = len(texts)
        rect_count = len(rects)
        if rect_count >= 6:
            layout_tags["card_grid"] += 1
        if text_count >= 8:
            layout_tags["dense_text"] += 1
        if any("toc" in svg_path.stem.lower() or "目录" in svg_path.stem for _ in [0]):
            layout_tags["toc"] += 1

        page_kind = _infer_page_kind(svg_path.stem)
        archetype = _infer_svg_archetype(svg_path.stem, rect_count, text_count)
        page_archetypes[page_kind] = archetype
        page_layout_map[svg_path.stem] = {
            "rect_count": rect_count,
            "text_count": text_count,
            "title_band_height": max(bands) if bands else 0,
            "page_kind": page_kind,
            "archetype": archetype,
        }

    top_colors = [color for color, _ in fill_colors.most_common(4)]
    avg_radius = round(sum(rect_radii) / len(rect_radii), 1) if rect_radii else 0
    avg_band_height = round(sum(title_band_heights) / len(title_band_heights), 1) if title_band_heights else 0

    return {
        "layout_tags": [tag for tag, _ in layout_tags.most_common(4)],
        "page_layout_map": page_layout_map,
        "page_archetypes": page_archetypes,
        "visual_rules": {
            "dominant_colors": top_colors,
            "background_mode": "dark" if top_colors and top_colors[0] in {"#0D1117", "#111827", "#0F172A"} else "light",
            "title_band_height": avg_band_height,
            "panel_radius": avg_radius,
            "frame_style": "sharp" if avg_radius <= 6 else "soft",
        },
        "can_extract_svg": bool(page_layout_map),
        "fallback_reason": "" if page_layout_map else "svg parsing yielded no usable structural features",
    }


def _infer_page_kind(stem: str) -> str:
    lowered = stem.lower()
    if "cover" in lowered:
        return "cover"
    if "navigation" in lowered or "toc" in lowered or "目录" in stem:
        return "toc"
    if "summary" in lowered or "ending" in lowered or "conclusion" in lowered:
        return "ending"
    return "content"


def _infer_svg_archetype(stem: str, rect_count: int, text_count: int) -> str:
    lowered = stem.lower()
    if "cover" in lowered:
        return "pixel_cover_hud"
    if "navigation" in lowered or "toc" in lowered:
        return "pixel_navigation_list"
    if "summary" in lowered or "ending" in lowered:
        return "pixel_summary_board"
    if "vs" in lowered or "compare" in lowered:
        return "pixel_compare_board"
    if rect_count >= 10:
        return "pixel_triple_panel"
    if text_count >= 10:
        return "pixel_dense_panel"
    return "pixel_dual_panel"
