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
    style_mode = strategy.get("resolved_style_mode") or strategy.get("style_mode") or "general"
    example_profile = strategy.get("example_style_profile") or {}

    if style_mode == "pixel_retro":
        return _render_pixel_slide_svg(slide, width, height, theme)
    if style_mode == "yijing_classic":
        return _render_yijing_slide_svg(slide, width, height, theme)

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
