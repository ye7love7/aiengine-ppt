from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "ppt-master" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from project_utils import CANVAS_FORMATS  # type: ignore  # noqa: E402


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


def render_slide_svg(slide: dict[str, Any], strategy: dict[str, Any], image_dir: Path) -> str:
    canvas = CANVAS_FORMATS[strategy.get("canvas_format", "ppt169")]
    width, height = [int(part) for part in canvas["viewbox"].split()[2:]]
    theme = strategy["theme"]
    typography = strategy["typography"]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{canvas["viewbox"]}" width="{width}" height="{height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{theme["background"]}"/>',
        f'<rect x="0" y="0" width="{width}" height="16" fill="{theme["primary"]}"/>',
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


def strategy_to_design_spec(strategy: dict[str, Any], image_inventory: list[dict[str, Any]], project_name: str, canvas_format: str) -> str:
    canvas = CANVAS_FORMATS[canvas_format]
    pages_md = []
    for page in strategy["pages"]:
        bullets = "\n".join(f"  - {item}" for item in page.get("bullets", [])[:5]) or "  - TBD"
        chart_line = f'- **Chart**: {page.get("chart_type")}\n' if page.get("chart_type") else ""
        pages_md.append(
            f"#### Slide {page['index']:02d} - {page['title']}\n\n"
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
