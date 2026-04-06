from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "ppt-master" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from project_utils import CANVAS_FORMATS  # type: ignore  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
SVG = f"{{{SVG_NS}}}"
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
ET.register_namespace("", SVG_NS)
TEMPLATE_CONTRACT_REGISTRY_PATH = Path(__file__).with_name("template_contracts.json")


def _load_template_contract_registry() -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, Any]]:
    registry = json.loads(TEMPLATE_CONTRACT_REGISTRY_PATH.read_text(encoding="utf-8"))
    families = registry.get("families") or {}
    templates = registry.get("templates") or {}
    default_family_name = str(registry.get("default_family") or "generic")
    default_contract = families.get(default_family_name) or next(iter(families.values()), {
        "page_files": {
            "cover": ["01_cover.svg"],
            "toc": ["02_toc.svg", "02_chapter.svg"],
            "chapter": ["02_chapter.svg", "03_content.svg"],
            "content": ["03_content.svg"],
            "ending": ["04_ending.svg"],
        },
        "semantic_overrides": {},
        "aliases": {},
    })
    return families, templates, default_contract


TEMPLATE_CONTRACT_FAMILIES, TEMPLATE_CONTRACTS, DEFAULT_TEMPLATE_CONTRACT = _load_template_contract_registry()


def escape_xml(text: str) -> str:
    return html.escape(text or "", quote=True)


def slugify(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", value.strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return text.lower() or "slide"


def split_text(text: str, max_chars: int) -> list[str]:
    if not text:
        return []
    words = text.split()
    if len(words) == 1 and len(words[0]) > max_chars:
        text = words[0]
        chunks = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
        return chunks

    lines: list[str] = []
    current = ""
    for word in words or list(text):
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines or [text[:max_chars]]


def text_block(x: int, y: int, lines: list[str], font_size: int, fill: str, weight: str = "400") -> str:
    if not lines:
        return ""
    tspan_lines = []
    for index, line in enumerate(lines):
        dy = "0" if index == 0 else f"{int(font_size * 1.45)}"
        tspan_lines.append(f'<tspan x="{x}" dy="{dy}">{escape_xml(line)}</tspan>')
    return (
        f'<text x="{x}" y="{y}" font-size="{font_size}" font-weight="{weight}" '
        f'fill="{fill}" font-family="Microsoft YaHei, Arial, sans-serif">'
        + "".join(tspan_lines)
        + "</text>"
    )


def render_slide_svg(
    slide: dict[str, Any],
    strategy: dict[str, Any],
    image_dir: Path,
    template_dir: Path | None = None,
) -> str:
    canvas = CANVAS_FORMATS[strategy.get("canvas_format", "ppt169")]
    width, height = [int(part) for part in canvas["viewbox"].split()[2:]]
    theme = strategy["theme"]
    typography = strategy["typography"]
    style_mode = strategy.get("resolved_style_mode") or strategy.get("style_mode") or "general"
    example_profile = strategy.get("example_style_profile") or {}

    if template_dir:
        template_svg = _render_template_driven_slide(slide, strategy, image_dir, template_dir, width, height)
        if template_svg:
            return template_svg

    if style_mode == "pixel_retro":
        return _render_pixel_slide_svg(slide, width, height, theme)
    if style_mode == "yijing_classic":
        return _render_yijing_slide_svg(slide, width, height, theme)
    if style_mode == "government_modern":
        return _render_government_slide_svg(slide, width, height, theme, typography, example_profile)
    if style_mode in {"consulting", "consulting_top"}:
        return _render_consulting_slide_svg(slide, width, height, theme, typography, style_mode, example_profile)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{canvas["viewbox"]}" width="{width}" height="{height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{theme["background"]}"/>',
        f'<rect x="0" y="0" width="{width}" height="{_resolve_title_band_height(example_profile)}" fill="{theme["primary"]}"/>',
    ]

    page_type = slide.get("page_type", "content")
    title = slide.get("title", "")
    subtitle = slide.get("subtitle", "")
    highlight = slide.get("highlight", "")
    image_filename = slide.get("image_filename") or ""
    image_path = image_dir / image_filename if image_filename else None

    if page_type == "cover":
        if image_path and image_path.exists():
            parts.append(
                f'<image href="../images/{escape_xml(image_filename)}" x="{width - 470}" y="0" width="470" height="{height}" preserveAspectRatio="xMidYMid slice"/>'
            )
            parts.append(f'<rect x="{width - 470}" y="0" width="470" height="{height}" fill="{theme["background"]}" fill-opacity="0.25"/>')
        parts.append(f'<rect x="72" y="120" width="680" height="460" rx="24" fill="{theme["secondary_background"]}" fill-opacity="0.92"/>')
        parts.append(text_block(110, 210, split_text(title, 14), 34, theme["text"], "700"))
        if subtitle:
            parts.append(text_block(110, 330, split_text(subtitle, 28), 20, theme["muted_text"], "400"))
        if highlight:
            parts.append(f'<rect x="110" y="450" width="520" height="82" rx="16" fill="{theme["accent"]}" fill-opacity="0.12"/>')
            parts.append(text_block(136, 495, split_text(highlight, 34), 18, theme["text"], "600"))
    elif page_type in {"chapter", "ending"}:
        parts.append(f'<rect x="70" y="120" width="{width - 140}" height="{height - 240}" rx="28" fill="{theme["secondary_background"]}"/>')
        parts.append(text_block(120, 250, split_text(title, 18), 36, theme["text"], "700"))
        if subtitle:
            parts.append(text_block(120, 340, split_text(subtitle, 36), 20, theme["muted_text"]))
        if highlight:
            parts.append(text_block(120, 460, split_text(highlight, 38), 18, theme["accent"], "600"))
    elif page_type == "toc":
        parts.append(text_block(80, 92, split_text(title or "目录", 20), 28, theme["text"], "700"))
        y = 170
        for idx, section in enumerate(slide.get("sections", []), start=1):
            parts.append(f'<rect x="90" y="{y - 28}" width="64" height="64" rx="16" fill="{theme["primary"]}" fill-opacity="0.14"/>')
            parts.append(text_block(110, y + 12, [str(idx)], 24, theme["primary"], "700"))
            parts.append(text_block(190, y + 2, split_text(section.get("heading", ""), 28), 22, theme["text"], "600"))
            y += 96
    else:
        parts.append(text_block(70, 86, split_text(title, 24), 28, theme["text"], "700"))
        parts.append(f'<line x1="70" y1="104" x2="{width - 70}" y2="104" stroke="{theme["border"]}" stroke-width="2"/>')
        card_y = 140
        if image_path and image_path.exists():
            parts.append(f'<rect x="{width - 410}" y="146" width="320" height="210" rx="22" fill="{theme["secondary_background"]}"/>')
            parts.append(
                f'<image href="../images/{escape_xml(image_filename)}" x="{width - 410}" y="146" width="320" height="210" preserveAspectRatio="xMidYMid slice"/>'
            )
            parts.append(f'<rect x="{width - 410}" y="146" width="320" height="210" rx="22" fill="{theme["background"]}" fill-opacity="0.1"/>')
        x_positions = [70, 430]
        width_card = 300 if image_path and image_path.exists() else 520
        for index, section in enumerate(slide.get("sections", [])[:4]):
            col = index % 2
            row = index // 2
            x = x_positions[col]
            y = card_y + row * 180
            parts.append(f'<rect x="{x}" y="{y}" width="{width_card}" height="146" rx="18" fill="{theme["secondary_background"]}"/>')
            parts.append(text_block(x + 22, y + 34, split_text(section.get("heading", ""), 18), 20, theme["primary"], "700"))
            bullet_y = y + 66
            for item in section.get("items", [])[:4]:
                parts.append(f'<circle cx="{x + 28}" cy="{bullet_y - 6}" r="4" fill="{theme["accent"]}"/>')
                parts.append(text_block(x + 44, bullet_y, split_text(item, 28 if width_card > 400 else 18), typography["body_size"], theme["text"]))
                bullet_y += typography["body_size"] + 18
        if slide.get("kpis"):
            kpi_x = 70
            kpi_y = height - 128
            for kpi in slide["kpis"][:3]:
                parts.append(f'<rect x="{kpi_x}" y="{kpi_y}" width="220" height="76" rx="16" fill="{theme["primary"]}" fill-opacity="0.1"/>')
                parts.append(text_block(kpi_x + 18, kpi_y + 32, split_text(kpi.get("value", ""), 10), 24, theme["primary"], "700"))
                parts.append(text_block(kpi_x + 18, kpi_y + 58, split_text(kpi.get("label", ""), 18), 14, theme["muted_text"], "500"))
                kpi_x += 242
        if highlight:
            parts.append(f'<rect x="{width - 360}" y="{height - 146}" width="280" height="96" rx="18" fill="{theme["accent"]}" fill-opacity="0.12"/>')
            parts.append(text_block(width - 336, height - 104, split_text(highlight, 18), 18, theme["text"], "600"))

    parts.append(
        f'<text x="{width - 96}" y="{height - 32}" font-size="14" fill="{theme["muted_text"]}" font-family="Arial, sans-serif">{slide["index"]:02d}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _render_template_driven_slide(
    slide: dict[str, Any],
    strategy: dict[str, Any],
    image_dir: Path,
    template_dir: Path,
    width: int,
    height: int,
) -> str | None:
    template_name = str(strategy.get("resolved_template_name") or strategy.get("template_name") or "").strip()
    template_contract = _get_template_contract(template_name)
    template_path = _resolve_template_svg_path(template_dir, slide.get("page_type", "content"), template_contract)
    if not template_path or not template_path.exists():
        return None
    try:
        root = ET.fromstring(template_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None

    parent_map = {child: parent for parent in root.iter() for child in parent}
    placeholders = _build_template_placeholders(slide, strategy, template_contract)
    content_box = _detect_content_box(root)

    for elem in list(root.iter()):
        for attr_name, attr_value in list(elem.attrib.items()):
            if "{{" in attr_value:
                elem.set(attr_name, _replace_inline_placeholders(attr_value, placeholders))

    for elem in list(root.iter()):
        if elem.tag != f"{SVG}text":
            continue
        raw_text = "".join(elem.itertext()).strip()
        if not raw_text:
            continue
        if "{{CONTENT_AREA}}" in raw_text or _is_template_hint_text(raw_text):
            if content_box and _element_within_box(elem, content_box):
                parent = parent_map.get(elem)
                if parent is not None:
                    parent.remove(elem)
            elif "{{CONTENT_AREA}}" in raw_text:
                parent = parent_map.get(elem)
                if parent is not None:
                    parent.remove(elem)
            continue
        _replace_text_placeholders(elem, placeholders)

    if content_box:
        placeholder_rect = content_box.get("element")
        if placeholder_rect is not None:
            parent = parent_map.get(placeholder_rect)
            if parent is not None:
                parent.remove(placeholder_rect)
        content_group = _render_template_content_group(slide, strategy, image_dir, template_contract, content_box, width, height)
        if content_group:
            root.append(ET.fromstring(content_group))

    return ET.tostring(root, encoding="unicode")


def _get_template_contract(template_name: str) -> dict[str, Any]:
    family = TEMPLATE_CONTRACTS.get(template_name, "generic")
    return TEMPLATE_CONTRACT_FAMILIES.get(family, DEFAULT_TEMPLATE_CONTRACT)


def _resolve_template_svg_path(template_dir: Path, page_type: str, template_contract: dict[str, Any]) -> Path | None:
    page_files = template_contract.get("page_files") or DEFAULT_TEMPLATE_CONTRACT["page_files"]
    candidates = page_files.get(page_type, ["03_content.svg"])
    for candidate in candidates:
        path = template_dir / candidate
        if path.exists():
            return path
    return None


def _get_template_layout_config(template_contract: dict[str, Any], archetype: str) -> dict[str, Any]:
    default_layouts = DEFAULT_TEMPLATE_CONTRACT.get("content_layouts") or {}
    default_shared = default_layouts.get("shared") or {}
    default_specific = default_layouts.get(archetype) or {}
    contract_layouts = template_contract.get("content_layouts") or {}
    contract_shared = contract_layouts.get("shared") or {}
    contract_specific = contract_layouts.get(archetype) or {}
    return {
        **default_shared,
        **default_specific,
        **contract_shared,
        **contract_specific,
    }


def _build_template_placeholders(slide: dict[str, Any], strategy: dict[str, Any], template_contract: dict[str, Any]) -> dict[str, str]:
    semantic_values = _build_base_template_semantics(slide, strategy)
    _apply_family_template_semantics(semantic_values, slide, strategy, template_contract)
    placeholders = {key: str(value or "") for key, value in semantic_values.items()}
    aliases = template_contract.get("aliases") or {}
    for semantic_key, placeholder_names in aliases.items():
        value = semantic_values.get(semantic_key.upper(), semantic_values.get(semantic_key, ""))
        for placeholder_name in placeholder_names:
            placeholders[str(placeholder_name)] = str(value or "")
    return {key: str(value or "") for key, value in placeholders.items()}


def _build_base_template_semantics(slide: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    page_num = int(slide.get("index") or 1)
    sections = slide.get("sections") or []
    key_points = slide.get("key_points") or []
    kpis = slide.get("kpis") or []
    highlight = slide.get("highlight") or ""
    project_name = str(strategy.get("project_name") or "")
    chapter_num = _infer_chapter_num(slide.get("title") or "", page_num)
    chapter_desc = slide.get("goal") or highlight or slide.get("subtitle") or " · ".join(key_points[:2]) or slide.get("title") or ""
    summary = _build_template_summary_payload(slide)
    feature_items = _collect_template_feature_items(slide)
    comparison = _build_template_compare_payload(slide)
    tag_items = _collect_template_tag_items(slide)
    goal_items = _build_template_goal_payload(slide)
    institution = str(strategy.get("organization") or strategy.get("audience") or project_name).strip()
    department = str(strategy.get("use_case") or strategy.get("audience") or "").strip()
    contact_info = highlight or strategy.get("core_message") or ""
    source = str(strategy.get("presentation_title") or project_name).strip()

    semantic_values = {
        "TITLE": slide.get("title") or strategy.get("presentation_title") or "",
        "TITLE_EN": slide.get("subtitle") or strategy.get("use_case") or "",
        "SUBTITLE": slide.get("subtitle") or "",
        "AUTHOR": project_name,
        "AUTHOR_EN": slugify(project_name).replace("-", " ").upper(),
        "VERSION": strategy.get("resolved_template_name") or "v1.0",
        "TOTAL_PAGES": str(strategy.get("page_count") or page_num),
        "DATE": today,
        "PROJECT_ID": slugify(project_name).upper(),
        "PRESENTER": project_name,
        "ORGANIZATION": institution,
        "ORG_SHORT": project_name[:24],
        "PAGE_TITLE": slide.get("title") or "",
        "PAGE_TITLE_EN": slide.get("subtitle") or strategy.get("use_case") or "",
        "PAGE_SUBTITLE": slide.get("subtitle") or "",
        "PAGE_NUM": f"{page_num:02d}",
        "CHAPTER_NUM": chapter_num,
        "CHAPTER_TITLE": slide.get("title") or "",
        "CHAPTER_SUBTITLE": slide.get("subtitle") or "",
        "CHAPTER_TITLE_EN": slide.get("subtitle") or "",
        "CHAPTER_DESC": chapter_desc,
        "CHAPTER_EN": slide.get("subtitle") or strategy.get("use_case") or "",
        "KEY_MESSAGE": highlight or " · ".join(key_points[:3]) or slide.get("title") or "",
        "SOURCE": source,
        "THANK_YOU": slide.get("title") or "感谢聆听",
        "THANK_YOU_EN": slide.get("subtitle") or "THANK YOU",
        "ENDING_SUBTITLE": slide.get("subtitle") or "请批评指正",
        "END_SUBTITLE": slide.get("subtitle") or "请批评指正",
        "CONTACT_NAME": project_name,
        "CONTACT_INFO": contact_info,
        "CONTACT_LINE_2": source,
        "COPYRIGHT": str(datetime.now().year),
        "CONTENT_AREA": "",
        "STAT_1": str(len(sections)),
        "STAT_2": str(sum(len(section.get("items", [])) for section in sections)),
        "STAT_3": str(len(key_points) or len(sections)),
        "CTA_TEXT": highlight or slide.get("title") or "Thank you",
        "CLOSING_MESSAGE": highlight or slide.get("goal") or slide.get("subtitle") or "欢迎交流",
        "WEBSITE": source,
        "ADVISOR": project_name,
        "DEPARTMENT": department,
        "INSTITUTION": institution,
        "EMAIL": source,
        "SECTION_NAME": slide.get("title") or "",
        "SECTION_NUM": chapter_num,
        "LOGO": project_name[:12],
        "LOGO_HEADER": project_name[:12],
        "LOGO_LARGE": project_name[:12],
        "QUOTE": highlight or slide.get("goal") or slide.get("title") or "",
        "QUOTE_AUTHOR": project_name,
        "COVER_BG_IMAGE": "",
    }
    for idx in range(1, 7):
        section = sections[idx - 1] if idx - 1 < len(sections) else {}
        items = section.get("items", []) if isinstance(section, dict) else []
        semantic_values[f"TOC_ITEM_{idx}_TITLE"] = section.get("heading", "") if isinstance(section, dict) else ""
        semantic_values[f"TOC_ITEM_{idx}_DESC"] = " / ".join(str(item) for item in items[:2])
    for idx in range(1, 4):
        item = summary[idx - 1]
        semantic_values[f"SUMMARY_{idx}_TITLE"] = item["title"]
        semantic_values[f"SUMMARY_{idx}_LINE_1"] = item["lines"][0]
        semantic_values[f"SUMMARY_{idx}_LINE_2"] = item["lines"][1]
        semantic_values[f"SUMMARY_{idx}_LINE_3"] = item["lines"][2]
        semantic_values[f"SUMMARY_{idx}_STAT"] = item["stat"]
    for idx in range(1, 5):
        semantic_values[f"FEATURE_{idx}"] = feature_items[idx - 1] if idx - 1 < len(feature_items) else ""
        semantic_values[f"TAG_{idx}"] = tag_items[idx - 1] if idx - 1 < len(tag_items) else ""
        goal = goal_items[idx - 1]
        semantic_values[f"GOAL_{idx}"] = goal["title"]
        semantic_values[f"GOAL_{idx}_DESC"] = goal["desc"]
    semantic_values["COMPARE_A"] = comparison["header_a"]
    semantic_values["COMPARE_B"] = comparison["header_b"]
    semantic_values["STAT_1_LABEL"] = kpis[0].get("label", "指标 1") if len(kpis) > 0 else "指标 1"
    semantic_values["STAT_2_LABEL"] = kpis[1].get("label", "指标 2") if len(kpis) > 1 else "指标 2"
    semantic_values["STAT_3_LABEL"] = kpis[2].get("label", "指标 3") if len(kpis) > 2 else "指标 3"
    semantic_values["STAT_LABEL_1"] = semantic_values["STAT_1_LABEL"]
    semantic_values["STAT_LABEL_2"] = semantic_values["STAT_2_LABEL"]
    semantic_values["STAT_LABEL_3"] = semantic_values["STAT_3_LABEL"]
    semantic_values["STAT_NUMBER_1"] = semantic_values["STAT_1"]
    semantic_values["STAT_NUMBER_2"] = semantic_values["STAT_2"]
    semantic_values["STAT_NUMBER_3"] = semantic_values["STAT_3"]
    for idx in range(1, 4):
        row = comparison["rows"][idx - 1]
        semantic_values[f"ROW_{idx}_A"] = row[0]
        semantic_values[f"ROW_{idx}_B"] = row[1]
    return semantic_values


def _apply_family_template_semantics(
    semantic_values: dict[str, Any],
    slide: dict[str, Any],
    strategy: dict[str, Any],
    template_contract: dict[str, Any],
) -> None:
    overrides = template_contract.get("semantic_overrides") or {}
    for semantic_key, source_name in overrides.items():
        value = _resolve_template_semantic_source(str(source_name), slide, strategy, semantic_values)
        semantic_values[semantic_key] = value
        semantic_values[str(semantic_key).upper()] = value


def _resolve_template_semantic_source(
    source_name: str,
    slide: dict[str, Any],
    strategy: dict[str, Any],
    semantic_values: dict[str, Any],
) -> str:
    project_name = str(strategy.get("project_name") or "")
    use_case = str(strategy.get("use_case") or "")
    audience = str(strategy.get("audience") or "")
    organization = str(strategy.get("organization") or "")
    subtitle = str(slide.get("subtitle") or "")
    highlight = str(slide.get("highlight") or "")
    goal = str(slide.get("goal") or "")
    title = str(slide.get("title") or "")
    core_message = str(strategy.get("core_message") or "")
    source = str(semantic_values.get("SOURCE") or "")

    if source_name == "image_filename":
        return str(slide.get("image_filename") or "")
    if source_name == "project_name":
        return project_name
    if source_name == "project_short":
        return project_name[:12]
    if source_name == "project_slug_upper":
        return slugify(project_name).replace("_", " ").upper()
    if source_name == "source":
        return source
    if source_name == "subtitle_or_use_case":
        return subtitle or use_case
    if source_name == "organization_or_audience_or_project_name":
        return organization or audience or project_name
    if source_name == "use_case_or_audience":
        return use_case or audience
    if source_name == "highlight_or_core_message":
        return highlight or core_message
    if source_name == "core_message_or_highlight_or_title":
        return core_message or highlight or title
    if source_name == "highlight_or_goal_or_title":
        return highlight or goal or title
    if source_name == "subtitle_or_literal_thank_you":
        return subtitle or "THANK YOU"
    return str(semantic_values.get(source_name.upper(), semantic_values.get(source_name, "")) or "")


def _build_template_summary_payload(slide: dict[str, Any]) -> list[dict[str, Any]]:
    sections = slide.get("sections") or []
    key_points = slide.get("key_points") or []
    kpis = slide.get("kpis") or []
    summary: list[dict[str, Any]] = []
    for idx in range(3):
        section = sections[idx] if idx < len(sections) else {}
        heading = str(section.get("heading") or (key_points[idx] if idx < len(key_points) else f"要点 {idx + 1}")).strip()
        items = [str(item).strip() for item in section.get("items", [])[:3]] if isinstance(section, dict) else []
        while len(items) < 3:
            fallback = key_points[len(items)] if len(items) < len(key_points) else ""
            items.append(str(fallback or ""))
        stat = ""
        if idx < len(kpis):
            kpi = kpis[idx]
            stat = f'{kpi.get("label", "")}: {kpi.get("value", "")}'.strip(": ")
        summary.append({"title": heading, "lines": items[:3], "stat": stat})
    return summary


def _collect_template_feature_items(slide: dict[str, Any]) -> list[str]:
    sections = slide.get("sections") or []
    features: list[str] = []
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        if heading:
            features.append(heading)
        for item in section.get("items", [])[:4]:
            if len(features) >= 4:
                break
            features.append(str(item).strip())
        if len(features) >= 4:
            break
    while len(features) < 4:
        features.append("")
    return features[:4]


def _collect_template_tag_items(slide: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for point in slide.get("key_points", [])[:4]:
        tags.append(str(point).strip())
    if not tags:
        for section in slide.get("sections", [])[:4]:
            heading = str(section.get("heading") or "").strip()
            if heading:
                tags.append(heading)
    while len(tags) < 4:
        tags.append("")
    return tags[:4]


def _build_template_goal_payload(slide: dict[str, Any]) -> list[dict[str, str]]:
    goals: list[dict[str, str]] = []
    sections = slide.get("sections") or []
    for idx in range(4):
        section = sections[idx] if idx < len(sections) else {}
        title = str(section.get("heading") or "").strip() if isinstance(section, dict) else ""
        desc = ""
        if isinstance(section, dict):
            items = [str(item).strip() for item in section.get("items", [])[:2]]
            desc = " / ".join(item for item in items if item)
        if not title and idx < len(slide.get("key_points", []) or []):
            title = str(slide["key_points"][idx]).strip()
        goals.append({"title": title, "desc": desc})
    return goals


def _build_template_compare_payload(slide: dict[str, Any]) -> dict[str, Any]:
    sections = slide.get("sections") or []
    kpis = slide.get("kpis") or []
    header_a = str(sections[0].get("heading") if len(sections) > 0 else (kpis[0].get("label") if len(kpis) > 0 else "当前")).strip() or "当前"
    header_b = str(sections[1].get("heading") if len(sections) > 1 else (kpis[1].get("label") if len(kpis) > 1 else "目标")).strip() or "目标"
    rows: list[tuple[str, str]] = []
    for idx in range(3):
        left = ""
        right = ""
        if len(sections) > 0 and idx < len(sections[0].get("items", [])):
            left = str(sections[0]["items"][idx]).strip()
        if len(sections) > 1 and idx < len(sections[1].get("items", [])):
            right = str(sections[1]["items"][idx]).strip()
        if not left and idx < len(kpis):
            left = str(kpis[idx].get("label") or "").strip()
        if not right and idx < len(kpis):
            right = str(kpis[idx].get("value") or "").strip()
        rows.append((left, right))
    return {"header_a": header_a, "header_b": header_b, "rows": rows}


def _replace_inline_placeholders(text: str, placeholders: dict[str, str]) -> str:
    return PLACEHOLDER_RE.sub(lambda match: escape_xml(placeholders.get(match.group(1), "")), text)


def _replace_text_placeholders(elem: ET.Element, placeholders: dict[str, str]) -> None:
    text = elem.text or ""
    if "{{" not in text:
        return
    stripped = text.strip()
    full_match = PLACEHOLDER_RE.fullmatch(stripped)
    if full_match:
        replacement = placeholders.get(full_match.group(1), "")
        lines = _wrap_placeholder_text(full_match.group(1), replacement)
        for child in list(elem):
            elem.remove(child)
        if len(lines) <= 1:
            elem.text = replacement
            return
        elem.text = None
        x_value = elem.get("x") or "0"
        line_height = _line_height_for_text(elem)
        for idx, line in enumerate(lines):
            tspan = ET.Element(f"{SVG}tspan")
            tspan.set("x", x_value)
            tspan.set("dy", "0" if idx == 0 else str(line_height))
            tspan.text = line
            elem.append(tspan)
        return
    elem.text = PLACEHOLDER_RE.sub(lambda match: placeholders.get(match.group(1), ""), text)


def _wrap_placeholder_text(name: str, value: str) -> list[str]:
    if not value:
        return [""]
    wrap_map = {
        "TITLE": 18,
        "SUBTITLE": 32,
        "PAGE_TITLE": 24,
        "PAGE_TITLE_EN": 32,
        "CHAPTER_TITLE": 22,
        "CHAPTER_SUBTITLE": 32,
        "CHAPTER_TITLE_EN": 32,
        "CHAPTER_DESC": 40,
        "KEY_MESSAGE": 56,
        "ENDING_SUBTITLE": 32,
        "END_SUBTITLE": 32,
        "THANK_YOU_EN": 32,
        "CTA_TEXT": 36,
        **{f"SUMMARY_{idx}_TITLE": 22 for idx in range(1, 4)},
        **{f"SUMMARY_{idx}_LINE_{line}": 22 for idx in range(1, 4) for line in range(1, 4)},
        **{f"SUMMARY_{idx}_STAT": 28 for idx in range(1, 4)},
        **{f"FEATURE_{idx}": 20 for idx in range(1, 5)},
        "COMPARE_A": 16,
        "COMPARE_B": 16,
        **{f"ROW_{idx}_A": 16 for idx in range(1, 4)},
        **{f"ROW_{idx}_B": 16 for idx in range(1, 4)},
        **{f"TOC_ITEM_{idx}_TITLE": 24 for idx in range(1, 7)},
        **{f"TOC_ITEM_{idx}_DESC": 34 for idx in range(1, 7)},
    }
    max_chars = wrap_map.get(name)
    return split_text(value, max_chars)[:3] if max_chars else [value]


def _line_height_for_text(elem: ET.Element) -> int:
    font_size = elem.get("font-size") or "20"
    match = re.search(r"(\d+)", font_size)
    size = int(match.group(1)) if match else 20
    return int(size * 1.35)


def _detect_content_box(root: ET.Element) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_area = -1.0
    for rect in root.iter(f"{SVG}rect"):
        if not rect.get("stroke-dasharray"):
            continue
        try:
            x = float(rect.get("x") or 0)
            y = float(rect.get("y") or 0)
            box_width = float(rect.get("width") or 0)
            box_height = float(rect.get("height") or 0)
        except ValueError:
            continue
        area = box_width * box_height
        if area > best_area:
            best_area = area
            best = {"x": x, "y": y, "width": box_width, "height": box_height, "element": rect}
    return best


def _is_template_hint_text(text: str) -> bool:
    markers = ["Executor", "自由布局", "可用空间", "内容区域", "由 Executor", "AI 灵活布局区域", "可使用的布局模式"]
    return any(marker in text for marker in markers)


def _element_within_box(elem: ET.Element, box: dict[str, Any]) -> bool:
    try:
        x = float(elem.get("x") or 0)
        y = float(elem.get("y") or 0)
    except ValueError:
        return False
    return box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"]


def _infer_chapter_num(title: str, page_num: int) -> str:
    match = re.match(r"\s*([一二三四五六七八九十\d]+)", title)
    return match.group(1) if match else f"{page_num:02d}"


def _render_template_content_group(
    slide: dict[str, Any],
    strategy: dict[str, Any],
    image_dir: Path,
    template_contract: dict[str, Any],
    box: dict[str, Any],
    width: int,
    height: int,
) -> str:
    del width, height
    theme = strategy["theme"]
    typography = strategy["typography"]
    sections = slide.get("sections") or [{"heading": slide.get("title", ""), "items": slide.get("key_points", [])[:3]}]
    kpis = slide.get("kpis") or []
    archetype = str(slide.get("content_archetype") or "lead_cards").strip().lower()
    image_filename = slide.get("image_filename") or ""
    image_path = image_dir / image_filename if image_filename else None
    x = int(box["x"])
    y = int(box["y"])
    box_width = int(box["width"])
    box_height = int(box["height"])
    shared_layout = _get_template_layout_config(template_contract, "shared")
    pad = int(shared_layout.get("outer_pad", 24))
    parts = [f'<g xmlns="{SVG_NS}">']

    body_x = x + pad
    body_y = y + pad
    body_w = box_width - pad * 2
    body_h = box_height - pad * 2
    layout_config = _get_template_layout_config(template_contract, archetype)
    footer_mode = str(layout_config.get("summary_footer", "none")).strip().lower()
    kpi_zone = str(layout_config.get("kpi_zone", "none")).strip().lower()
    footer_height = 38 if footer_mode == "compact" else 0
    kpi_reserved_height = 0

    if archetype == "kpi_row" and kpis:
        consumed = _append_template_kpi_row(parts, kpis, body_x, body_y, body_w, theme, _get_template_layout_config(template_contract, "kpi_row"))
        body_y += consumed
        body_h -= consumed
    elif kpi_zone == "top" and kpis:
        consumed = _append_template_kpi_row(parts, kpis, body_x, body_y, body_w, theme, _get_template_layout_config(template_contract, "kpi_row"))
        body_y += consumed
        body_h -= consumed
    elif kpi_zone == "bottom" and kpis:
        kpi_reserved_height = int(_get_template_layout_config(template_contract, "kpi_row").get("consumed_height", 104))

    if footer_height:
        body_h -= footer_height
    if kpi_reserved_height:
        body_h -= kpi_reserved_height

    if archetype == "image_left_text_right" and image_path and image_path.exists():
        _append_template_image_text_layout(parts, sections, image_filename, image_path, body_x, body_y, body_w, body_h, theme, typography, layout_config)
    elif archetype == "dual_column":
        _append_template_dual_column_layout(parts, sections, body_x, body_y, body_w, body_h, theme, typography, layout_config)
    elif archetype == "list_grid":
        _append_template_list_grid_layout(parts, sections, body_x, body_y, body_w, body_h, theme, typography, layout_config)
    else:
        _append_template_lead_cards_layout(parts, sections, body_x, body_y, body_w, body_h, theme, typography, layout_config)

    footer_y = body_y + body_h
    if footer_height:
        _append_template_footer_summary(parts, sections, body_x, footer_y, body_w, theme)
        footer_y += footer_height
    if kpi_reserved_height:
        _append_template_kpi_row(parts, kpis, body_x, footer_y, body_w, theme, _get_template_layout_config(template_contract, "kpi_row"))

    parts.append("</g>")
    return "".join(parts)


def _append_template_kpi_row(
    parts: list[str],
    kpis: list[dict[str, Any]],
    body_x: int,
    body_y: int,
    body_w: int,
    theme: dict[str, str],
    layout_config: dict[str, Any],
) -> int:
    card_gap = int(layout_config.get("card_gap", 16))
    card_height = int(layout_config.get("card_height", 84))
    card_radius = int(layout_config.get("card_radius", 14))
    label_size = int(layout_config.get("label_size", 14))
    value_size = int(layout_config.get("value_size", 24))
    card_count = min(3, len(kpis))
    card_w = int((body_w - card_gap * (card_count - 1)) / max(1, card_count))
    for idx, kpi in enumerate(kpis[:card_count]):
        card_x = body_x + idx * (card_w + card_gap)
        parts.append(f'<rect x="{card_x}" y="{body_y}" width="{card_w}" height="{card_height}" rx="{card_radius}" fill="{theme["secondary_background"]}" stroke="{theme["border"]}" stroke-width="1"/>')
        parts.append(text_block(card_x + 18, body_y + 34, split_text(kpi.get("label", ""), 18)[:1], label_size, theme["muted_text"], "600"))
        parts.append(text_block(card_x + 18, body_y + 64, split_text(kpi.get("value", ""), 16)[:1], value_size, theme["primary"], "700"))
    return int(layout_config.get("consumed_height", card_height + 20))


def _append_template_lead_cards_layout(
    parts: list[str],
    sections: list[dict[str, Any]],
    body_x: int,
    body_y: int,
    body_w: int,
    body_h: int,
    theme: dict[str, str],
    typography: dict[str, Any],
    layout_config: dict[str, Any],
) -> None:
    lead = sections[0]
    lead_h = int(layout_config.get("lead_height_multi", 124)) if len(sections) > 1 else min(int(layout_config.get("lead_height_single_max", 172)), body_h)
    card_radius = int(layout_config.get("card_radius", 16))
    sub_card_radius = int(layout_config.get("sub_card_radius", 14))
    section_gap = int(layout_config.get("section_gap", 18))
    sub_gap = int(layout_config.get("sub_gap", 16))
    parts.append(f'<rect x="{body_x}" y="{body_y}" width="{body_w}" height="{lead_h}" rx="{card_radius}" fill="{theme["secondary_background"]}" stroke="{theme["border"]}" stroke-width="1"/>')
    parts.append(text_block(body_x + 22, body_y + 34, split_text(lead.get("heading", ""), 22)[:2], 20, theme["text"], "700"))
    bullet_y = body_y + 66
    for item in lead.get("items", [])[:4]:
        parts.append(f'<circle cx="{body_x + 28}" cy="{bullet_y - 6}" r="4" fill="{theme["primary"]}"/>')
        parts.append(text_block(body_x + 42, bullet_y, split_text(str(item), 44)[:2], typography.get("body_size", 18), theme["text"]))
        bullet_y += 38

    remaining = sections[1:4]
    if not remaining:
        return

    sub_y = body_y + lead_h + section_gap
    sub_count = len(remaining)
    sub_w = int((body_w - sub_gap * max(0, sub_count - 1)) / max(1, sub_count))
    for idx, section in enumerate(remaining):
        card_x = body_x + idx * (sub_w + sub_gap)
        card_h = max(120, body_h - lead_h - section_gap)
        parts.append(f'<rect x="{card_x}" y="{sub_y}" width="{sub_w}" height="{card_h}" rx="{sub_card_radius}" fill="{theme["secondary_background"]}" stroke="{theme["border"]}" stroke-width="1"/>')
        parts.append(text_block(card_x + 18, sub_y + 30, split_text(section.get("heading", ""), 16)[:2], 17, theme["text"], "700"))
        item_y = sub_y + 58
        for item in section.get("items", [])[:4]:
            parts.append(f'<circle cx="{card_x + 22}" cy="{item_y - 6}" r="3.5" fill="{theme["accent"]}"/>')
            parts.append(text_block(card_x + 34, item_y, split_text(str(item), 20)[:2], 14, theme["text"]))
            item_y += 30


def _append_template_dual_column_layout(
    parts: list[str],
    sections: list[dict[str, Any]],
    body_x: int,
    body_y: int,
    body_w: int,
    body_h: int,
    theme: dict[str, str],
    typography: dict[str, Any],
    layout_config: dict[str, Any],
) -> None:
    gap = int(layout_config.get("gap", 18))
    card_radius = int(layout_config.get("card_radius", 16))
    header_bar_height = int(layout_config.get("header_bar_height", 8))
    col_w = int((body_w - gap) / 2)
    for idx in range(min(2, len(sections))):
        section = sections[idx]
        x = body_x + idx * (col_w + gap)
        parts.append(f'<rect x="{x}" y="{body_y}" width="{col_w}" height="{body_h}" rx="{card_radius}" fill="{theme["secondary_background"]}" stroke="{theme["border"]}" stroke-width="1"/>')
        parts.append(f'<rect x="{x}" y="{body_y}" width="{col_w}" height="{header_bar_height}" rx="{card_radius}" fill="{theme["primary"]}"/>')
        parts.append(text_block(x + 20, body_y + 34, split_text(section.get("heading", ""), 18)[:2], 19, theme["text"], "700"))
        item_y = body_y + 66
        for item in section.get("items", [])[:6]:
            parts.append(f'<circle cx="{x + 24}" cy="{item_y - 6}" r="4" fill="{theme["accent"]}"/>')
            parts.append(text_block(x + 36, item_y, split_text(str(item), 22)[:2], typography.get("body_size", 18), theme["text"]))
            item_y += typography.get("body_size", 18) + 18
    footer_mode = str(layout_config.get("summary_footer", "compact")).strip().lower()
    if footer_mode == "inline_compact" and len(sections) > 2:
        footer_y = body_y + body_h - 54
        extras = " / ".join(section.get("heading", "") for section in sections[2:4] if section.get("heading"))
        if extras:
            parts.append(text_block(body_x + 8, footer_y, split_text(extras, 56)[:2], 14, theme["muted_text"], "600"))


def _append_template_list_grid_layout(
    parts: list[str],
    sections: list[dict[str, Any]],
    body_x: int,
    body_y: int,
    body_w: int,
    body_h: int,
    theme: dict[str, str],
    typography: dict[str, Any],
    layout_config: dict[str, Any],
) -> None:
    cols = int(layout_config.get("cols", 2))
    gap = int(layout_config.get("gap", 18))
    card_radius = int(layout_config.get("card_radius", 16))
    rows = max(1, (min(4, len(sections)) + 1) // 2)
    card_w = int((body_w - gap) / cols)
    card_h = int((body_h - gap * max(0, rows - 1)) / rows)
    for idx, section in enumerate(sections[:4]):
        row = idx // 2
        col = idx % 2
        x = body_x + col * (card_w + gap)
        y = body_y + row * (card_h + gap)
        parts.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="{card_radius}" fill="{theme["secondary_background"]}" stroke="{theme["border"]}" stroke-width="1"/>')
        parts.append(text_block(x + 18, y + 32, split_text(section.get("heading", ""), 18)[:2], 18, theme["text"], "700"))
        item_y = y + 58
        for item in section.get("items", [])[:4]:
            parts.append(f'<rect x="{x + 18}" y="{item_y - 12}" width="8" height="8" fill="{theme["primary"]}"/>')
            parts.append(text_block(x + 34, item_y, split_text(str(item), 20)[:2], 14, theme["text"]))
            item_y += 28


def _append_template_image_text_layout(
    parts: list[str],
    sections: list[dict[str, Any]],
    image_filename: str,
    image_path: Path,
    body_x: int,
    body_y: int,
    body_w: int,
    body_h: int,
    theme: dict[str, str],
    typography: dict[str, Any],
    layout_config: dict[str, Any],
) -> None:
    image_ratio = float(layout_config.get("image_ratio", 0.36))
    gap = int(layout_config.get("gap", 20))
    image_height_ratio = float(layout_config.get("image_height_ratio", 0.78))
    card_radius = int(layout_config.get("card_radius", 16))
    image_side = str(layout_config.get("image_side", "left")).strip().lower()
    image_w = int(body_w * image_ratio)
    text_w = body_w - image_w - gap
    image_h = min(body_h, int(body_h * image_height_ratio))
    if image_side == "right":
        text_x = body_x
        image_x = body_x + text_w + gap
    else:
        image_x = body_x
        text_x = body_x + image_w + gap
    parts.append(f'<rect x="{image_x}" y="{body_y}" width="{image_w}" height="{image_h}" rx="{card_radius}" fill="{theme["secondary_background"]}" stroke="{theme["border"]}" stroke-width="1"/>')
    parts.append(f'<image href="../images/{escape_xml(image_filename)}" x="{image_x}" y="{body_y}" width="{image_w}" height="{image_h}" preserveAspectRatio="xMidYMid slice"/>')
    parts.append(f'<rect x="{image_x}" y="{body_y}" width="{image_w}" height="{image_h}" rx="{card_radius}" fill="{theme["background"]}" fill-opacity="0.06"/>')

    lead = sections[0]
    parts.append(f'<rect x="{text_x}" y="{body_y}" width="{text_w}" height="{body_h}" rx="{card_radius}" fill="{theme["secondary_background"]}" stroke="{theme["border"]}" stroke-width="1"/>')
    parts.append(text_block(text_x + 20, body_y + 34, split_text(lead.get("heading", ""), 18)[:2], 20, theme["text"], "700"))
    item_y = body_y + 66
    for item in lead.get("items", [])[:6]:
        parts.append(f'<circle cx="{text_x + 24}" cy="{item_y - 6}" r="4" fill="{theme["accent"]}"/>')
        parts.append(text_block(text_x + 38, item_y, split_text(str(item), 22)[:2], typography.get("body_size", 18), theme["text"]))
        item_y += typography.get("body_size", 18) + 18
    footer_mode = str(layout_config.get("summary_footer", "compact")).strip().lower()
    if footer_mode == "inline_compact" and len(sections) > 1:
        summary = " / ".join(section.get("heading", "") for section in sections[1:3] if section.get("heading"))
        if summary:
            parts.append(text_block(text_x + 20, body_y + body_h - 34, split_text(summary, 34)[:2], 14, theme["muted_text"], "600"))


def _append_template_footer_summary(
    parts: list[str],
    sections: list[dict[str, Any]],
    body_x: int,
    footer_y: int,
    body_w: int,
    theme: dict[str, str],
) -> None:
    extras = " / ".join(section.get("heading", "") for section in sections[2:5] if section.get("heading"))
    if not extras:
        return
    parts.append(f'<line x1="{body_x}" y1="{footer_y + 6}" x2="{body_x + body_w}" y2="{footer_y + 6}" stroke="{theme["border"]}" stroke-width="1"/>')
    parts.append(text_block(body_x + 8, footer_y + 28, split_text(extras, 56)[:2], 14, theme["muted_text"], "600"))


def _render_government_slide_svg(
    slide: dict[str, Any],
    width: int,
    height: int,
    theme: dict[str, str],
    typography: dict[str, Any],
    example_profile: dict[str, Any],
) -> str:
    page_type = slide.get("page_type", "content")
    title = slide.get("title", "")
    subtitle = slide.get("subtitle", "")
    highlight = slide.get("highlight", "")
    sections = slide.get("sections", [])
    kpis = slide.get("kpis", [])
    primary = theme.get("primary", "#0D4EA6")
    accent = theme.get("accent", "#C00000")
    secondary = theme.get("secondary_accent", "#1C7ED6")
    bg = theme.get("background", "#F8FAFF")
    panel = theme.get("secondary_background", "#FFFFFF")
    text = theme.get("text", "#22324A")
    muted = theme.get("muted_text", "#5B6B83")
    border = theme.get("border", "#D7E0EC")
    body_size = int(typography.get("body_size") or 18)
    band_height = max(36, _resolve_title_band_height(example_profile))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{bg}"/>',
        f'<rect x="0" y="0" width="{width}" height="{band_height}" fill="{primary}"/>',
        f'<rect x="0" y="{band_height}" width="{width}" height="4" fill="{accent}"/>',
        f'<rect x="48" y="76" width="{width - 96}" height="{height - 120}" fill="{panel}" stroke="{border}" stroke-width="1.5"/>',
    ]

    if page_type == "cover":
        parts.append(f'<rect x="92" y="148" width="10" height="{height - 280}" fill="{accent}"/>')
        parts.append(text_block(130, 210, split_text(title, 16), 34, primary, "700"))
        if subtitle:
            parts.append(text_block(132, 322, split_text(subtitle, 28), 20, muted, "500"))
        if highlight:
            parts.append(f'<rect x="132" y="{height - 188}" width="420" height="64" fill="{secondary}" fill-opacity="0.12"/>')
            parts.append(text_block(154, height - 146, split_text(highlight, 28), 18, text, "700"))
        parts.append(f'<line x1="132" y1="{height - 96}" x2="{width - 132}" y2="{height - 96}" stroke="{border}" stroke-width="1.5"/>')

    elif page_type == "toc":
        parts.append(text_block(88, 116, split_text(title or "目录", 18), 28, primary, "700"))
        if subtitle:
            parts.append(text_block(width - 240, 114, split_text(subtitle, 18), 15, muted, "500"))
        y = 178
        for idx, section in enumerate(sections[:6], start=1):
            box_h = 72
            x = 92 if idx <= 3 else width // 2 + 18
            row = idx - 1 if idx <= 3 else idx - 4
            box_y = y + row * 108
            box_w = width // 2 - 128
            parts.append(f'<rect x="{x}" y="{box_y}" width="{box_w}" height="{box_h}" fill="{bg}" stroke="{border}" stroke-width="1"/>')
            parts.append(f'<rect x="{x}" y="{box_y}" width="72" height="{box_h}" fill="{primary}"/>')
            parts.append(text_block(x + 22, box_y + 46, [f"{idx:02d}"], 24, "#FFFFFF", "700"))
            parts.append(text_block(x + 94, box_y + 30, split_text(section.get("heading", ""), 16), 18, text, "700"))
            items = section.get("items", [])
            if items:
                parts.append(text_block(x + 94, box_y + 54, split_text(" / ".join(items[:3]), 24), 13, muted, "500"))

    elif page_type in {"chapter", "ending"}:
        parts.append(f'<rect x="92" y="158" width="{width - 184}" height="{height - 256}" fill="{bg}" stroke="{border}" stroke-width="1"/>')
        parts.append(f'<line x1="92" y1="222" x2="{width - 92}" y2="222" stroke="{accent}" stroke-width="3"/>')
        parts.append(text_block(126, 210, split_text(title, 18), 34, primary, "700"))
        if subtitle:
            parts.append(text_block(126, 286, split_text(subtitle, 32), 19, muted, "500"))
        if highlight:
            parts.append(text_block(126, 382, split_text(highlight, 40), 18, accent, "600"))
        if page_type == "ending" and kpis:
            x = 126
            for kpi in kpis[:3]:
                parts.append(f'<rect x="{x}" y="{height - 178}" width="230" height="70" fill="{panel}" stroke="{border}" stroke-width="1"/>')
                parts.append(text_block(x + 18, height - 140, split_text(kpi.get("value", ""), 12), 20, primary, "700"))
                parts.append(text_block(x + 18, height - 114, split_text(kpi.get("label", ""), 18), 13, muted, "500"))
                x += 248

    else:
        parts.append(text_block(84, 118, split_text(title, 22), 28, primary, "700"))
        if subtitle:
            parts.append(text_block(84, 156, split_text(subtitle, 32), 16, muted, "500"))
        parts.append(f'<line x1="84" y1="178" x2="{width - 84}" y2="178" stroke="{accent}" stroke-width="2"/>')
        if highlight:
            parts.append(f'<rect x="{width - 360}" y="96" width="248" height="54" fill="{accent}" fill-opacity="0.08"/>')
            parts.append(text_block(width - 338, 128, split_text(highlight, 18), 15, accent, "700"))

        if sections:
            lead = sections[0]
            parts.append(f'<rect x="84" y="206" width="{width - 168}" height="118" fill="{bg}" stroke="{border}" stroke-width="1"/>')
            parts.append(f'<rect x="84" y="206" width="8" height="118" fill="{accent}"/>')
            parts.append(text_block(110, 242, split_text(lead.get("heading", ""), 20), 20, primary, "700"))
            bullet_y = 274
            for item in lead.get("items", [])[:4]:
                parts.append(f'<rect x="110" y="{bullet_y - 12}" width="8" height="8" fill="{secondary}"/>')
                parts.append(text_block(128, bullet_y, split_text(item, 42), body_size, text, "500"))
                bullet_y += body_size + 18

        small_y = 344
        for idx, section in enumerate(sections[1:5], start=1):
            col = 0 if idx % 2 == 1 else 1
            row = (idx - 1) // 2
            x = 84 + col * ((width - 184) // 2 + 16)
            y = small_y + row * 130
            box_w = (width - 184) // 2
            parts.append(f'<rect x="{x}" y="{y}" width="{box_w}" height="110" fill="{panel}" stroke="{border}" stroke-width="1"/>')
            parts.append(f'<rect x="{x}" y="{y}" width="8" height="110" fill="{primary if idx > 2 else secondary}"/>')
            parts.append(text_block(x + 24, y + 32, split_text(section.get("heading", ""), 18), 18, primary, "700"))
            items = section.get("items", [])[:3]
            if items:
                parts.append(text_block(x + 24, y + 60, split_text(" / ".join(items), 28), 14, muted, "500"))

        if kpis:
            x = 84
            y = height - 104
            for kpi in kpis[:3]:
                parts.append(f'<rect x="{x}" y="{y}" width="210" height="54" fill="{panel}" stroke="{border}" stroke-width="1"/>')
                parts.append(text_block(x + 16, y + 24, split_text(kpi.get("value", ""), 12), 18, primary, "700"))
                parts.append(text_block(x + 16, y + 44, split_text(kpi.get("label", ""), 18), 12, muted, "500"))
                x += 228

    parts.append(f'<text x="{width - 78}" y="{height - 24}" font-size="16" fill="{muted}" font-family="Arial, sans-serif">{slide["index"]:02d}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _render_consulting_slide_svg(
    slide: dict[str, Any],
    width: int,
    height: int,
    theme: dict[str, str],
    typography: dict[str, Any],
    style_mode: str,
    example_profile: dict[str, Any],
) -> str:
    page_type = slide.get("page_type", "content")
    title = slide.get("title", "")
    subtitle = slide.get("subtitle", "")
    highlight = slide.get("highlight", "")
    sections = slide.get("sections", [])
    kpis = slide.get("kpis", [])
    archetype = slide.get("example_archetype") or ""
    primary = theme.get("primary", "#17375E")
    accent = theme.get("accent", "#4A90D9")
    secondary = theme.get("secondary_accent", accent)
    bg = theme.get("background", "#F8FAFC")
    panel = theme.get("secondary_background", "#FFFFFF")
    text = theme.get("text", "#334155")
    muted = theme.get("muted_text", "#64748B")
    border = theme.get("border", "#E2E8F0")
    title_size = 30 if style_mode == "consulting_top" else 28
    body_size = int(typography.get("body_size") or 18)
    title_band_height = max(44, int(_resolve_title_band_height(example_profile)))
    frame_style = ((example_profile.get("visual_rules") or {}).get("frame_style") or "sharp").lower()
    panel_radius = 0 if frame_style == "sharp" else 10

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{bg}"/>',
        f'<rect x="0" y="0" width="{width}" height="{title_band_height}" fill="{primary}"/>',
    ]

    if page_type == "cover":
        parts.append(f'<rect x="82" y="118" width="{width - 164}" height="{height - 180}" rx="{panel_radius}" fill="{panel}" stroke="{border}" stroke-width="1.5"/>')
        parts.append(f'<rect x="82" y="118" width="8" height="{height - 180}" fill="{accent}"/>')
        parts.append(text_block(132, 210, split_text(title, 18), title_size + 8, primary, "700"))
        if subtitle:
            parts.append(text_block(132, 330, split_text(subtitle, 34), 20, muted, "500"))
        if highlight:
            parts.append(f'<rect x="132" y="{height - 180}" width="{width - 264}" height="64" rx="{panel_radius}" fill="{accent}" fill-opacity="0.1"/>')
            parts.append(text_block(154, height - 138, split_text(highlight, 36), 18, text, "700"))

    elif page_type == "toc":
        parts.append(text_block(84, 96, split_text(title or "目录", 18), title_size, "#FFFFFF", "700"))
        if subtitle:
            parts.append(text_block(width - 240, 94, split_text(subtitle, 18), 16, "#D9E3F0", "500"))
        parts.append(f'<rect x="70" y="132" width="{width - 140}" height="{height - 200}" rx="{panel_radius}" fill="{panel}" stroke="{border}" stroke-width="1.5"/>')
        column_x = [106, width // 2 + 14]
        y = 194
        for idx, section in enumerate(sections[:6], start=1):
            col = 0 if idx <= 3 else 1
            row = idx - 1 if col == 0 else idx - 4
            box_y = y + row * 126
            x = column_x[col]
            parts.append(f'<rect x="{x}" y="{box_y}" width="{width//2 - 130}" height="92" rx="{panel_radius}" fill="{bg}" stroke="{border}" stroke-width="1"/>')
            parts.append(f'<rect x="{x}" y="{box_y}" width="88" height="92" fill="{primary}"/>')
            parts.append(text_block(x + 26, box_y + 56, [f"{idx:02d}"], 30, "#FFFFFF", "700"))
            parts.append(text_block(x + 112, box_y + 34, split_text(section.get("heading", ""), 16), 20, text, "700"))
            items = section.get("items", [])
            if items:
                parts.append(text_block(x + 112, box_y + 62, split_text(" / ".join(items[:3]), 26), 14, muted, "500"))

    elif page_type == "ending":
        parts.append(f'<rect x="72" y="150" width="{width - 144}" height="{height - 240}" rx="{panel_radius}" fill="{panel}" stroke="{border}" stroke-width="1.5"/>')
        parts.append(f'<line x1="72" y1="226" x2="{width - 72}" y2="226" stroke="{accent}" stroke-width="3"/>')
        parts.append(text_block(120, 214, split_text(title, 18), 36, primary, "700"))
        if subtitle:
            parts.append(text_block(120, 286, split_text(subtitle, 28), 20, muted, "500"))
        if highlight:
            parts.append(text_block(120, 390, split_text(highlight, 40), 18, accent, "600"))
        if kpis:
            x = 120
            for kpi in kpis[:3]:
                parts.append(f'<rect x="{x}" y="{height - 180}" width="250" height="76" rx="{panel_radius}" fill="{bg}" stroke="{border}" stroke-width="1"/>')
                parts.append(text_block(x + 18, height - 138, split_text(kpi.get("value", ""), 12), 22, primary, "700"))
                parts.append(text_block(x + 18, height - 110, split_text(kpi.get("label", ""), 18), 14, muted, "500"))
                x += 272

    else:
        parts.append(text_block(74, 94, split_text(title, 22), title_size, "#FFFFFF", "700"))
        if subtitle:
            parts.append(text_block(width - 380, 92, split_text(subtitle, 30), 15, "#D9E3F0", "500"))
        parts.append(f'<rect x="64" y="128" width="{width - 128}" height="{height - 176}" rx="{panel_radius}" fill="{panel}" stroke="{border}" stroke-width="1.5"/>')
        label = highlight or subtitle or ""
        if label:
            parts.append(f'<rect x="88" y="156" width="280" height="40" rx="{panel_radius}" fill="{accent}" fill-opacity="0.1"/>')
            parts.append(text_block(106, 183, split_text(label, 20), 16, accent, "700"))

        if archetype == "content_panel" or style_mode == "consulting_top":
            left_x, right_x = 88, width // 2 + 12
            panel_w = width // 2 - 116
            panel_h = height - 266
            if sections:
                lead = sections[0]
                parts.append(f'<rect x="{left_x}" y="214" width="{panel_w}" height="{panel_h}" rx="{panel_radius}" fill="{bg}" stroke="{border}" stroke-width="1"/>')
                parts.append(text_block(left_x + 24, 252, split_text(lead.get("heading", ""), 18), 22, primary, "700"))
                bullet_y = 292
                for item in lead.get("items", [])[:5]:
                    parts.append(f'<rect x="{left_x + 24}" y="{bullet_y - 14}" width="10" height="10" fill="{accent}"/>')
                    parts.append(text_block(left_x + 46, bullet_y, split_text(item, 22), body_size, text, "500"))
                    bullet_y += body_size + 22
            stack_y = 214
            for idx, section in enumerate(sections[1:4], start=1):
                box_h = 96
                parts.append(f'<rect x="{right_x}" y="{stack_y}" width="{panel_w}" height="{box_h}" rx="{panel_radius}" fill="{bg}" stroke="{border}" stroke-width="1"/>')
                color = accent if idx == 1 else (secondary if idx == 2 else primary)
                parts.append(f'<rect x="{right_x}" y="{stack_y}" width="8" height="{box_h}" fill="{color}"/>')
                parts.append(text_block(right_x + 22, stack_y + 34, split_text(section.get("heading", ""), 18), 18, text, "700"))
                items = " / ".join(section.get("items", [])[:3])
                if items:
                    parts.append(text_block(right_x + 22, stack_y + 62, split_text(items, 28), 14, muted, "500"))
                stack_y += box_h + 18
        else:
            y = 214
            for idx, section in enumerate(sections[:4], start=1):
                box_h = 96
                parts.append(f'<rect x="88" y="{y}" width="{width - 176}" height="{box_h}" rx="{panel_radius}" fill="{bg}" stroke="{border}" stroke-width="1"/>')
                parts.append(f'<rect x="88" y="{y}" width="112" height="{box_h}" fill="{primary}"/>')
                parts.append(text_block(118, y + 56, [f"{idx:02d}"], 28, "#FFFFFF", "700"))
                parts.append(text_block(224, y + 34, split_text(section.get("heading", ""), 18), 20, text, "700"))
                items = " / ".join(section.get("items", [])[:4])
                if items:
                    parts.append(text_block(224, y + 64, split_text(items, 40), 14, muted, "500"))
                y += box_h + 18

        if kpis:
            x = 88
            kpi_y = height - 128
            for kpi in kpis[:3]:
                parts.append(f'<rect x="{x}" y="{kpi_y}" width="220" height="64" rx="{panel_radius}" fill="{bg}" stroke="{border}" stroke-width="1"/>')
                parts.append(text_block(x + 18, kpi_y + 28, split_text(kpi.get("value", ""), 12), 20, primary, "700"))
                parts.append(text_block(x + 18, kpi_y + 50, split_text(kpi.get("label", ""), 18), 12, muted, "500"))
                x += 240

    parts.append(f'<text x="{width - 78}" y="{height - 24}" font-size="16" fill="{muted}" font-family="Arial, sans-serif">{slide["index"]:02d}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _render_pixel_slide_svg(slide: dict[str, Any], width: int, height: int, theme: dict[str, str]) -> str:
    title = slide.get("title", "")
    subtitle = slide.get("subtitle", "")
    sections = slide.get("sections", [])
    title_lines = split_text(title, 18)
    title_y = 88
    title_size = 34 if len(title_lines) <= 1 else 28
    subtitle_y = title_y + (len(title_lines) * int(title_size * 1.45)) + 14
    archetype = slide.get("example_archetype") or _infer_pixel_archetype_from_slide(slide, sections)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{theme["background"]}"/>',
        f'<rect x="0" y="64" width="{width}" height="2" fill="{theme["border"]}" fill-opacity="0.5"/>',
        text_block(84, title_y, title_lines, title_size, theme["primary"], "700"),
    ]
    if subtitle:
        parts.append(text_block(84, subtitle_y, split_text(subtitle, 34), 18, theme["muted_text"], "500"))

    page_type = slide.get("page_type", "content")
    if page_type == "cover":
        parts.append(f'<rect x="82" y="178" width="{width - 164}" height="{height - 286}" fill="{theme["secondary_background"]}" stroke="{theme["accent"]}" stroke-width="4"/>')
        highlight = slide.get("highlight") or slide.get("speaker_notes") or ""
        if highlight:
            parts.append(text_block(118, 290, split_text(highlight, 44), 22, theme["text"], "600"))
    elif page_type == "toc":
        y = 188
        for idx, section in enumerate(sections, start=1):
            parts.append(f'<rect x="92" y="{y - 36}" width="{width - 184}" height="78" fill="{theme["secondary_background"]}" stroke="{theme["accent"]}" stroke-width="3"/>')
            parts.append(f'<rect x="92" y="{y - 36}" width="92" height="78" fill="{theme["primary"]}"/>')
            parts.append(text_block(122, y + 14, [str(idx)], 30, theme["background"], "700"))
            parts.append(text_block(214, y + 8, split_text(section.get("heading", ""), 28), 22, theme["text"], "700"))
            y += 104
    elif page_type == "ending":
        parts.extend(_render_pixel_ending(slide, width, height, theme))
    else:
        boxes = _pixel_boxes_for_archetype(archetype, len(sections) or 1, width, height)
        for box, section in zip(boxes, sections[: len(boxes)]):
            x, y, w, h, color = box
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{theme["secondary_background"]}" stroke="{color}" stroke-width="4"/>')
            parts.append(f'<rect x="{x}" y="{y}" width="92" height="70" fill="{color}"/>')
            parts.append(text_block(x + 22, y + 44, [str(section.get("index") or slide.get("index") or "")], 26, theme["background"], "700"))
            parts.append(text_block(x + 116, y + 42, split_text(section.get("heading", ""), 18), 18, color, "700"))
            bullet_y = y + 92
            for item in section.get("items", [])[:4]:
                parts.append(text_block(x + 28, bullet_y, [f"• {item}"], 16, theme["text"], "500"))
                bullet_y += 42
        highlight = slide.get("highlight") or ""
        if highlight:
            parts.append(f'<rect x="86" y="{height - 126}" width="{width - 172}" height="78" fill="{theme["secondary_background"]}" stroke="{theme["secondary_accent"]}" stroke-width="4"/>')
            parts.append(text_block(116, height - 78, split_text(highlight, 44), 20, theme["secondary_accent"], "700"))

    parts.append(f'<text x="{width - 74}" y="{height - 22}" font-size="18" fill="{theme["muted_text"]}" font-family="Consolas, monospace">{slide["index"]:02d}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _render_yijing_slide_svg(slide: dict[str, Any], width: int, height: int, theme: dict[str, str]) -> str:
    title = slide.get("title", "")
    subtitle = slide.get("subtitle", "")
    sections = slide.get("sections", [])
    archetype = slide.get("example_archetype") or _infer_yijing_archetype_from_slide(slide, sections)
    page_type = slide.get("page_type", "content")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
    ]

    if page_type in {"cover", "ending"}:
        parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="{theme["background"]}"/>')
        parts.append(f'<rect x="0" y="0" width="{width}" height="18" fill="{theme["secondary_accent"]}" fill-opacity="0.9"/>')
    else:
        parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="{theme["secondary_background"]}"/>')
        parts.append(f'<rect x="0" y="0" width="{width}" height="14" fill="{theme["secondary_accent"]}" fill-opacity="0.9"/>')

    if page_type == "cover":
        parts.extend(_render_yijing_cover(slide, width, height, theme))
    elif page_type == "toc":
        parts.extend(_render_yijing_toc(slide, width, height, theme))
    elif page_type == "ending":
        parts.extend(_render_yijing_ending(slide, width, height, theme))
    else:
        parts.extend(_render_yijing_content(slide, width, height, theme, sections, archetype, title, subtitle))

    parts.append(
        f'<text x="{width - 66}" y="{height - 24}" font-size="15" fill="{theme["muted_text"]}" '
        f'font-family="Microsoft YaHei, Arial, sans-serif">{slide["index"]:02d}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _pixel_boxes_for_archetype(archetype: str, section_count: int, width: int, height: int) -> list[tuple[int, int, int, int, str]]:
    colors = ["#39FF14", "#00D4FF", "#FF2E97", "#FFD700"]
    if archetype == "pixel_compare_board":
        return [
            (64, 176, 552, 274, colors[0]),
            (664, 176, 552, 274, colors[2]),
        ]
    if archetype == "pixel_triple_panel":
        return [
            (48, 176, 382, 262, colors[0]),
            (450, 176, 382, 262, colors[1]),
            (852, 176, 382, 262, colors[2]),
        ]
    if section_count <= 2:
        return [
            (86, 176, 520, 262, colors[0]),
            (672, 176, 520, 262, colors[1]),
        ]
    if section_count == 3:
        return [
            (48, 176, 382, 262, colors[0]),
            (450, 176, 382, 262, colors[1]),
            (852, 176, 382, 262, colors[2]),
        ]
    return [
        (70, 166, 520, 188, colors[0]),
        (650, 166, 520, 188, colors[1]),
        (70, 392, 520, 188, colors[2]),
        (650, 392, 520, 188, colors[3]),
    ]


def _render_pixel_ending(slide: dict[str, Any], width: int, height: int, theme: dict[str, str]) -> list[str]:
    highlight = slide.get("highlight") or slide.get("speaker_notes") or ""
    lines = split_text(highlight, 48)[:3]
    return [
        f'<rect x="72" y="182" width="{width - 144}" height="170" fill="{theme["secondary_background"]}" stroke="{theme["secondary_accent"]}" stroke-width="4"/>',
        text_block(108, 244, lines or ["READY TO CONTINUE"], 24, theme["secondary_accent"], "700"),
        f'<rect x="72" y="404" width="{width - 144}" height="148" fill="{theme["secondary_background"]}" stroke="{theme["primary"]}" stroke-width="4"/>',
        text_block(108, 468, split_text(slide.get("title", ""), 24), 28, theme["primary"], "700"),
        text_block(108, 512, split_text(slide.get("subtitle", ""), 42), 18, theme["text"], "500"),
    ]


def _render_yijing_cover(slide: dict[str, Any], width: int, height: int, theme: dict[str, str]) -> list[str]:
    title_lines = split_text(slide.get("title", ""), 16)
    subtitle_lines = split_text(slide.get("subtitle", ""), 24)
    return [
        f'<rect x="84" y="110" width="560" height="{height - 220}" fill="#1A2430" fill-opacity="0.92"/>',
        f'<line x1="120" y1="178" x2="680" y2="178" stroke="{theme["primary"]}" stroke-width="3"/>',
        text_block(118, 208, title_lines, 34, theme["primary"], "700"),
        text_block(118, 310, subtitle_lines[:2], 20, theme["muted_text"], "500"),
        f'<rect x="122" y="{height - 170}" width="430" height="84" fill="{theme["secondary_accent"]}" fill-opacity="0.32"/>',
        text_block(150, height - 122, split_text(slide.get("highlight") or slide.get("speaker_notes") or "", 24)[:2], 20, theme["text"], "600"),
        f'<circle cx="{width - 186}" cy="{height / 2:.0f}" r="74" fill="none" stroke="{theme["primary"]}" stroke-width="4" stroke-opacity="0.9"/>',
        f'<path d="M {width - 186} {height / 2 - 74:.0f} A 74 74 0 0 1 {width - 186} {height / 2 + 74:.0f}" fill="{theme["secondary_background"]}" fill-opacity="0.92"/>',
        f'<path d="M {width - 186} {height / 2 - 74:.0f} A 74 74 0 0 0 {width - 186} {height / 2 + 74:.0f}" fill="{theme["background"]}" fill-opacity="0.4"/>',
        f'<circle cx="{width - 186}" cy="{height / 2 - 36:.0f}" r="12" fill="{theme["primary"]}"/>',
        f'<circle cx="{width - 186}" cy="{height / 2 + 36:.0f}" r="12" fill="{theme["secondary_background"]}"/>',
    ]


def _render_yijing_toc(slide: dict[str, Any], width: int, height: int, theme: dict[str, str]) -> list[str]:
    parts = [
        text_block(88, 92, split_text(slide.get("title") or "目录", 18), 30, "#2C3E50", "700"),
        f'<line x1="88" y1="114" x2="{width - 120}" y2="114" stroke="{theme["primary"]}" stroke-width="3"/>',
    ]
    y = 172
    for idx, section in enumerate(slide.get("sections", [])[:6], start=1):
        parts.append(f'<rect x="92" y="{y - 34}" width="{width - 184}" height="78" rx="18" fill="#FFFFFF" stroke="{theme["border"]}" stroke-width="2"/>')
        parts.append(f'<rect x="92" y="{y - 34}" width="94" height="78" rx="18" fill="{theme["secondary_accent"]}" fill-opacity="0.14"/>')
        parts.append(text_block(124, y + 12, [f"{idx:02d}"], 24, theme["secondary_accent"], "700"))
        parts.append(text_block(224, y + 6, split_text(section.get("heading", ""), 26), 21, "#2C3E50", "600"))
        y += 96
    return parts


def _render_yijing_content(
    slide: dict[str, Any],
    width: int,
    height: int,
    theme: dict[str, str],
    sections: list[dict[str, Any]],
    archetype: str,
    title: str,
    subtitle: str,
) -> list[str]:
    parts = [
        text_block(76, 88, split_text(title, 22), 28, "#2C3E50", "700"),
        f'<line x1="76" y1="108" x2="{width - 90}" y2="108" stroke="{theme["primary"]}" stroke-width="3"/>',
    ]
    if subtitle:
        parts.append(text_block(76, 136, split_text(subtitle, 34), 16, theme["muted_text"], "500"))

    if archetype == "yijing_lines_panel":
        parts.extend(_render_yijing_lines_panel(slide, width, height, theme, sections))
        return parts
    if archetype == "yijing_dual_panel":
        parts.extend(_render_yijing_dual_panel(slide, width, height, theme, sections))
        return parts
    parts.extend(_render_yijing_text_panel(slide, width, height, theme, sections))
    return parts


def _render_yijing_lines_panel(
    slide: dict[str, Any],
    width: int,
    height: int,
    theme: dict[str, str],
    sections: list[dict[str, Any]],
) -> list[str]:
    left = sections[0] if sections else {"heading": "卦象结构", "items": []}
    right = sections[1] if len(sections) > 1 else {"heading": "核心解读", "items": slide.get("key_points", [])[:3]}
    parts = [
        f'<rect x="58" y="156" width="548" height="430" rx="20" fill="#233243" stroke="{theme["secondary_accent"]}" stroke-width="2"/>',
        f'<rect x="706" y="156" width="520" height="430" rx="20" fill="#FFFFFF" stroke="{theme["accent"]}" stroke-width="2"/>',
        f'<rect x="58" y="156" width="548" height="56" rx="20" fill="{theme["secondary_accent"]}"/>',
        f'<rect x="706" y="156" width="520" height="56" rx="20" fill="{theme["accent"]}"/>',
        text_block(252, 192, split_text(left.get("heading", ""), 12), 20, "#FFFFFF", "700"),
        text_block(900, 192, split_text(right.get("heading", ""), 12), 20, "#FFFFFF", "700"),
    ]
    yao_y = 250
    for idx in range(6):
        is_yang = idx in {0, 2, 5}
        line_y = yao_y + idx * 34
        if is_yang:
            parts.append(f'<rect x="258" y="{line_y}" width="146" height="8" rx="4" fill="{theme["primary"] if idx == 3 else "#8A98A6"}"/>')
        else:
            parts.append(f'<rect x="236" y="{line_y}" width="52" height="8" rx="4" fill="#8A98A6"/>')
            parts.append(f'<rect x="322" y="{line_y}" width="52" height="8" rx="4" fill="#8A98A6"/>')
        parts.append(f'<rect x="430" y="{line_y}" width="52" height="8" rx="4" fill="#8A98A6"/>')
        parts.append(f'<rect x="516" y="{line_y}" width="52" height="8" rx="4" fill="#8A98A6"/>')
    quote = slide.get("highlight") or slide.get("speaker_notes") or "谦，亨，君子有终。"
    parts.append(f'<rect x="94" y="420" width="476" height="88" rx="14" fill="none" stroke="{theme["primary"]}" stroke-width="2"/>')
    parts.append(text_block(146, 464, split_text(quote, 18)[:2], 18, theme["primary"], "700"))

    item_y = 262
    for item in right.get("items", [])[:4]:
        parts.append(f'<rect x="742" y="{item_y - 24}" width="444" height="74" rx="14" fill="#F8F8F6" stroke="{theme["border"]}" stroke-width="1.5"/>')
        parts.append(f'<rect x="742" y="{item_y - 24}" width="6" height="74" fill="{theme["secondary_accent"] if item_y < 330 else theme["accent"]}"/>')
        parts.append(text_block(776, item_y + 4, split_text(item, 20), 17, "#2C3E50", "600"))
        item_y += 92
    return parts


def _render_yijing_dual_panel(
    slide: dict[str, Any],
    width: int,
    height: int,
    theme: dict[str, str],
    sections: list[dict[str, Any]],
) -> list[str]:
    colors = [theme["secondary_accent"], theme["accent"]]
    boxes = [(58, 170, 548, 400), (674, 170, 548, 400)]
    parts: list[str] = []
    for idx, section in enumerate(sections[:2] or [{"heading": slide.get("title", ""), "items": slide.get("key_points", [])[:3]}]):
        x, y, w, h = boxes[min(idx, 1)]
        color = colors[min(idx, 1)]
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" fill="#FFFFFF" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="58" rx="20" fill="{color}" fill-opacity="0.12"/>')
        parts.append(text_block(x + 28, y + 38, split_text(section.get("heading", ""), 16), 20, color, "700"))
        bullet_y = y + 98
        for item in section.get("items", [])[:5]:
            parts.append(f'<circle cx="{x + 30}" cy="{bullet_y - 6}" r="4" fill="{color}"/>')
            parts.append(text_block(x + 48, bullet_y, split_text(item, 20), 17, "#2C3E50", "500"))
            bullet_y += 54
    return parts


def _render_yijing_text_panel(
    slide: dict[str, Any],
    width: int,
    height: int,
    theme: dict[str, str],
    sections: list[dict[str, Any]],
) -> list[str]:
    parts = [f'<rect x="70" y="168" width="{width - 140}" height="392" rx="22" fill="#FFFFFF" stroke="{theme["border"]}" stroke-width="2"/>']
    current_y = 214
    for section in sections[:4]:
        parts.append(text_block(104, current_y, split_text(section.get("heading", ""), 24), 20, theme["primary"], "700"))
        current_y += 34
        for item in section.get("items", [])[:4]:
            parts.append(f'<circle cx="112" cy="{current_y - 6}" r="4" fill="{theme["accent"]}"/>')
            parts.append(text_block(130, current_y, split_text(item, 42), 17, "#2C3E50", "500"))
            current_y += 38
        current_y += 18
    return parts


def _render_yijing_ending(slide: dict[str, Any], width: int, height: int, theme: dict[str, str]) -> list[str]:
    highlight = slide.get("highlight") or slide.get("speaker_notes") or "谦受益，满招损。"
    return [
        f'<rect x="124" y="156" width="{width - 248}" height="360" rx="26" fill="#16202C" stroke="{theme["primary"]}" stroke-width="2"/>',
        text_block(188, 250, split_text(slide.get("title", ""), 18), 34, theme["primary"], "700"),
        text_block(188, 334, split_text(highlight, 28)[:3], 22, theme["text"], "500"),
        f'<line x1="188" y1="384" x2="{width - 188}" y2="384" stroke="{theme["secondary_accent"]}" stroke-width="2" stroke-opacity="0.7"/>',
        text_block(188, 444, split_text(slide.get("subtitle", "") or "以谦守正，以静制动。", 30), 18, theme["muted_text"], "500"),
    ]


def _infer_pixel_archetype_from_slide(slide: dict[str, Any], sections: list[dict[str, Any]]) -> str:
    chart_type = slide.get("chart_type") or ""
    if slide.get("page_type") == "toc":
        return "pixel_navigation_list"
    if slide.get("page_type") == "ending":
        return "pixel_summary_board"
    if chart_type == "comparison":
        return "pixel_compare_board"
    if len(sections) >= 3:
        return "pixel_triple_panel"
    return "pixel_dual_panel"


def _infer_yijing_archetype_from_slide(slide: dict[str, Any], sections: list[dict[str, Any]]) -> str:
    page_type = slide.get("page_type")
    chart_type = slide.get("chart_type") or ""
    title = slide.get("title", "")
    if page_type == "cover":
        return "yijing_cover_taiji"
    if page_type == "toc":
        return "yijing_toc_scroll"
    if page_type == "ending":
        return "yijing_ending_quote"
    if "卦" in title or "六爻" in title:
        return "yijing_lines_panel"
    if chart_type == "comparison" or len(sections) >= 2:
        return "yijing_dual_panel"
    return "yijing_text_panel"


def _resolve_title_band_height(example_profile: dict[str, Any]) -> int:
    visual_rules = example_profile.get("visual_rules") or {}
    try:
        band_height = int(float(visual_rules.get("title_band_height") or 16))
    except Exception:
        band_height = 16
    return max(12, min(96, band_height))


def strategy_to_design_spec(strategy: dict[str, Any], image_inventory: list[dict[str, Any]], project_name: str, canvas_format: str) -> str:
    canvas = CANVAS_FORMATS[canvas_format]
    pages_md = []
    for page in strategy["pages"]:
        bullets = "\n".join(f"  - {item}" for item in page.get("bullets", [])[:5]) or "  - TBD"
        chart_line = f'- **Chart**: {page.get("chart_type")}\n' if page.get("chart_type") else ""
        pages_md.append(
            f"#### Slide {page['index']:02d} - {page['title']}\n\n"
            f"- **Page Role**: {page.get('page_type', 'content')}\n"
            f"- **Content Archetype**: {page.get('content_archetype', 'empty')}\n"
            f"- **Layout**: {page.get('layout', 'content')}\n"
            f"- **Title**: {page['title']}\n"
            f"- **Subtitle**: {page.get('subtitle', '')}\n"
            f"{chart_line}"
            f"- **Content**:\n{bullets}\n"
        )

    inventory_md = ""
    if image_inventory:
        rows = []
        for item in image_inventory:
            rows.append(
                f"| {item['filename']} | {item['width']}x{item['height']} | {item['aspect_ratio']:.2f} | Existing | Illustration | Existing | - |"
            )
        inventory_md = "\n".join(rows)
    else:
        inventory_md = "| - | - | - | No images | - | - | - |"

    theme = strategy["theme"]
    typo = strategy["typography"]
    return f"""# {project_name} - Design Spec

## I. Project Information

| Item | Value |
| ---- | ----- |
| **Project Name** | {project_name} |
| **Canvas Format** | {canvas['name']} ({canvas['dimensions']}) |
| **Page Count** | {strategy['page_count']} |
| **Design Style** | {strategy['style_mode']} |
| **Target Audience** | {strategy['audience']} |
| **Use Case** | {strategy['use_case']} |

## II. Canvas Specification

| Property | Value |
| -------- | ----- |
| **Format** | {canvas['name']} |
| **Dimensions** | {canvas['dimensions']} |
| **viewBox** | `{canvas['viewbox']}` |

## III. Visual Theme

| Role | HEX |
| ---- | --- |
| **Background** | `{theme['background']}` |
| **Secondary bg** | `{theme['secondary_background']}` |
| **Primary** | `{theme['primary']}` |
| **Accent** | `{theme['accent']}` |
| **Secondary accent** | `{theme['secondary_accent']}` |
| **Body text** | `{theme['text']}` |
| **Secondary text** | `{theme['muted_text']}` |
| **Border/divider** | `{theme['border']}` |

## IV. Typography System

| Role | Font |
| ---- | ---- |
| **Title** | {typo['title_font']} |
| **Body** | {typo['body_font']} |
| **Emphasis** | {typo['emphasis_font']} |
| **Body Size** | {typo['body_size']}px |

## VIII. Image Resource List

| Filename | Dimensions | Ratio | Purpose | Type | Status | Generation Description |
| -------- | ---------- | ----- | ------- | ---- | ------ | ---------------------- |
{inventory_md}

## IX. Content Outline

{chr(10).join(pages_md)}

## X. Speaker Notes Requirements

- Match SVG names such as `01_cover.md`
- Notes style: conversational and concise
- Each page includes key points and duration
"""


def notes_to_total_md(slides: list[dict[str, Any]], language: str) -> str:
    if language.startswith("zh"):
        transition = "[过渡]"
        key_points_label = "要点："
        duration_label = "时长："
    else:
        transition = "[Transition]"
        key_points_label = "Key points:"
        duration_label = "Duration:"

    parts = []
    for index, slide in enumerate(slides):
        heading = f"# {slide['file_stem']}"
        body = slide["speaker_notes"].strip()
        if index > 0 and not body.startswith(transition):
            body = f"{transition} {body}"
        key_points = " / ".join(slide.get("key_points", [])[:3])
        duration = slide.get("duration_minutes", 1.0)
        parts.append(
            f"{heading}\n\n{body}\n\n{key_points_label} {key_points}\n{duration_label} {duration} minutes\n"
        )
    return "\n---\n\n".join(parts) + "\n"
