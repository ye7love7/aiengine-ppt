from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from service_api.config import SETTINGS  # noqa: E402
from service_api.examples import extract_example_style_profile, resolve_example_dir  # noqa: E402
from service_api.main import app  # noqa: E402
from service_api.pipeline import _normalize_content_archetype, _normalize_template_name, _run_strategist  # noqa: E402
from service_api.rendering import (  # noqa: E402
    TEMPLATE_CONTRACTS,
    TEMPLATE_CONTRACT_REGISTRY_PATH,
    _build_template_placeholders,
    _get_template_layout_config,
    _get_template_contract,
    render_slide_svg,
)


def _fake_style_classifier(system_prompt: str, user_prompt: str, max_tokens: int = 1200, **_: object) -> dict[str, object]:
    payload = json.loads(user_prompt)
    example_name = str(payload.get("example_name") or "")
    if "像素风" in example_name:
        return {
            "style_tag": "pixel_retro",
            "recommended_template": "pixel_retro",
            "confidence": 0.96,
            "reason": "Example uses pixel retro HUD language.",
        }
    if "易理风" in example_name:
        return {
            "style_tag": "yijing_classic",
            "recommended_template": "",
            "confidence": 0.95,
            "reason": "Example centers on 易理/卦象/阴阳 visual grammar.",
        }
    if "顶级咨询" in example_name:
        return {
            "style_tag": "consulting_top",
            "recommended_template": "exhibit",
            "confidence": 0.9,
            "reason": "Example has board-style exhibit structure.",
        }
    return {
        "style_tag": "consulting",
        "recommended_template": "mckinsey",
        "confidence": 0.7,
        "reason": "Fallback consulting classification for tests.",
    }


class ServiceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._classifier_patcher = patch("service_api.examples.LLM.chat_json", side_effect=_fake_style_classifier)
        cls._classifier_patcher.start()
        cls.client = TestClient(app)
        (SETTINGS.materials_docs_root / "sample.md").write_text("# Sample\n\nHello", encoding="utf-8")
        (SETTINGS.materials_images_root / "sample.png").write_bytes(b"fake")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._classifier_patcher.stop()
        for path in [
            SETTINGS.materials_docs_root / "sample.md",
            SETTINGS.materials_images_root / "sample.png",
        ]:
            if path.exists():
                path.unlink()

    def setUp(self) -> None:
        shutil.rmtree(SETTINGS.example_style_cache_root, ignore_errors=True)
        SETTINGS.example_style_cache_root.mkdir(parents=True, exist_ok=True)

    def test_materials_is_public(self) -> None:
        response = self.client.get("/api/v1/materials")
        self.assertEqual(response.status_code, 200)

    def test_materials_lists_seed_files(self) -> None:
        response = self.client.get("/api/v1/materials")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        doc_paths = {item["path"] for item in payload["docs"]}
        image_paths = {item["path"] for item in payload["images"]}
        self.assertIn("sample.md", doc_paths)
        self.assertIn("sample.png", image_paths)
        self.assertNotIn(".gitkeep", doc_paths)
        self.assertNotIn(".gitkeep", image_paths)

    def test_examples_list_is_available(self) -> None:
        response = self.client.get("/api/v1/examples")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("examples", payload)
        self.assertTrue(payload["examples"])

    def test_examples_list_avoids_full_style_extraction(self) -> None:
        with patch("service_api.examples.extract_example_style_profile", side_effect=AssertionError("should not run for list view")):
            response = self.client.get("/api/v1/examples")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["examples"])

    def test_templates_list_is_available(self) -> None:
        response = self.client.get("/api/v1/templates")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        template_names = {item["name"] for item in payload["templates"]}
        self.assertIn("mckinsey", template_names)

    def test_example_detail_and_download_are_available(self) -> None:
        list_response = self.client.get("/api/v1/examples")
        example_name = list_response.json()["examples"][0]["name"]

        detail_response = self.client.get(f"/api/v1/examples/{example_name}")
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["example"]["name"], example_name)
        self.assertIn("style_profile", detail_payload)
        artifact_names = {item["name"] for item in detail_payload["artifacts"]}
        self.assertIn("design_spec", artifact_names)

        download_response = self.client.get(f"/api/v1/examples/{example_name}/download/design_spec")
        self.assertEqual(download_response.status_code, 200)

    def test_create_task_records_optional_upstream_user_id(self) -> None:
        payload = {
            "source_mode": "path",
            "project_name": "trace-demo",
            "canvas_format": "ppt169",
            "example_reference": None,
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": ["native_pptx", "svg_pptx"],
            "source_files": ["sample.md"],
            "image_files": [],
        }
        with patch("service_api.main.run_task", lambda task_id: None):
            response = self.client.post(
                "/api/v1/tasks",
                json=payload,
                headers={"X-Request-User-Id": "user-42"},
            )
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        try:
            state_response = self.client.get(f"/api/v1/tasks/{task_id}")
            self.assertEqual(state_response.status_code, 200)
            state_payload = state_response.json()
            self.assertEqual(state_payload["upstream_user_id"], "user-42")

            log_path = SETTINGS.jobs_root / task_id / "run.log"
            self.assertTrue(log_path.exists())
            self.assertIn("upstream_user_id=user-42", log_path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(SETTINGS.jobs_root / task_id, ignore_errors=True)

    def test_create_task_auto_generates_project_name_when_blank(self) -> None:
        payload = {
            "source_mode": "path",
            "project_name": "",
            "canvas_format": "ppt169",
            "example_reference": None,
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": ["native_pptx", "svg_pptx"],
            "source_files": ["sample.md"],
            "image_files": [],
        }
        with patch("service_api.main.run_task", lambda task_id: None):
            response = self.client.post("/api/v1/tasks", json=payload)
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        try:
            state_payload = self.client.get(f"/api/v1/tasks/{task_id}").json()
            self.assertTrue(state_payload["request"]["project_name"].startswith("ppt_task_"))
        finally:
            shutil.rmtree(SETTINGS.jobs_root / task_id, ignore_errors=True)

    def test_create_task_accepts_example_reference(self) -> None:
        example_name = self.client.get("/api/v1/examples").json()["examples"][0]["name"]
        payload = {
            "source_mode": "path",
            "project_name": "style-demo",
            "canvas_format": "ppt169",
            "example_reference": example_name,
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": ["native_pptx", "svg_pptx"],
            "source_files": ["sample.md"],
            "image_files": [],
        }
        with patch("service_api.main.run_task", lambda task_id: None):
            response = self.client.post("/api/v1/tasks", json=payload)
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        try:
            state_payload = self.client.get(f"/api/v1/tasks/{task_id}").json()
            self.assertEqual(state_payload["request"]["example_reference"], example_name)
            self.assertEqual(state_payload["request"]["style_source"], "example_strong")
        finally:
            shutil.rmtree(SETTINGS.jobs_root / task_id, ignore_errors=True)

    def test_run_strategist_prefers_explicit_template_over_example_reference(self) -> None:
        example_profile = {
            "style_tag": "consulting_top",
            "recommended_template": "exhibit",
            "theme": {"primary": "#123456"},
            "typography": {"body_size": 19},
            "visual_rules": {"frame_style": "board"},
        }
        example_context = {
            "name": "ppt169_顶级咨询风_甘孜州经济财政分析",
            "suggested_style": "consulting_top",
            "summary": "Top consulting sample.",
            "style_profile": example_profile,
            "readme_excerpt": "sample readme",
            "design_spec_excerpt": "sample design spec",
        }
        llm_strategy = {
            "language": "zh-CN",
            "presentation_title": "测试汇报",
            "audience": "领导",
            "use_case": "汇报",
            "core_message": "测试",
            "style_mode": "consulting_top",
            "template_name": "exhibit",
            "theme": {},
            "typography": {},
            "page_count": 2,
            "pages": [
                {
                    "index": 1,
                    "page_type": "cover",
                    "title": "封面",
                    "subtitle": "副标题",
                    "layout": "cover",
                    "goal": "goal",
                    "bullets": [],
                    "chart_type": "",
                    "image_filename": "",
                },
                {
                    "index": 2,
                    "page_type": "ending",
                    "title": "结束",
                    "subtitle": "",
                    "layout": "ending",
                    "goal": "goal",
                    "bullets": [],
                    "chart_type": "",
                    "image_filename": "",
                },
            ],
        }
        request_data = {
            "project_name": "template-first",
            "canvas_format": "ppt169",
            "template_name": "mckinsey",
            "example_reference": example_context["name"],
            "style_source": "example_strong",
            "prefer_style": "auto",
            "notes_style": "formal",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / "images").mkdir(parents=True, exist_ok=True)
            with patch("service_api.pipeline._collect_source_text", return_value="# Sample"), \
                 patch("service_api.pipeline._analyze_images", return_value=[]), \
                 patch("service_api.pipeline.load_example_prompt_context", return_value=example_context), \
                 patch("service_api.pipeline.extract_example_style_profile", return_value=example_profile), \
                 patch("service_api.pipeline.strategy_to_design_spec", return_value="# spec"), \
                 patch("service_api.pipeline._copy_template") as mock_copy_template, \
                 patch("service_api.pipeline.LLM.chat_json", return_value=llm_strategy), \
                 patch("service_api.pipeline.STORE.append_log"), \
                 patch("service_api.pipeline.STORE.write_stage_metadata"), \
                 patch("service_api.pipeline.STORE.update_state"):
                strategy = _run_strategist("task-template-first", project_path, request_data)
        self.assertFalse(strategy["style_locked"])
        self.assertEqual(strategy["template_name"], "mckinsey")
        self.assertEqual(strategy["resolved_template_name"], "mckinsey")
        self.assertEqual(strategy["example_reference"], example_context["name"])
        mock_copy_template.assert_called_with(project_path, "mckinsey")

    def test_run_strategist_preserves_page_content_archetype(self) -> None:
        llm_strategy = {
            "language": "zh-CN",
            "presentation_title": "模板收敛",
            "audience": "领导",
            "use_case": "汇报",
            "core_message": "模板优先",
            "style_mode": "consulting_top",
            "template_name": "exhibit",
            "theme": {},
            "typography": {},
            "image_strategy": "none",
            "page_count": 3,
            "pages": [
                {"index": 1, "page_type": "cover", "content_archetype": "empty", "title": "封面", "subtitle": "", "layout": "cover", "goal": "封面", "bullets": [], "chart_type": "", "image_filename": ""},
                {"index": 2, "page_type": "content", "content_archetype": "dual_column", "title": "正文", "subtitle": "", "layout": "split_left_right", "goal": "正文", "bullets": ["A", "B"], "chart_type": "", "image_filename": ""},
                {"index": 3, "page_type": "ending", "content_archetype": "empty", "title": "结束", "subtitle": "", "layout": "ending", "goal": "结束", "bullets": [], "chart_type": "", "image_filename": ""},
            ],
        }
        request_data = {
            "project_name": "archetype-demo",
            "canvas_format": "ppt169",
            "template_name": "exhibit",
            "prefer_style": "auto",
            "notes_style": "formal",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / "images").mkdir(parents=True, exist_ok=True)
            with patch("service_api.pipeline._collect_source_text", return_value="# Sample"), \
                 patch("service_api.pipeline._analyze_images", return_value=[]), \
                 patch("service_api.pipeline.strategy_to_design_spec", return_value="# spec"), \
                 patch("service_api.pipeline._copy_template"), \
                 patch("service_api.pipeline.LLM.chat_json", return_value=llm_strategy), \
                 patch("service_api.pipeline.STORE.append_log"), \
                 patch("service_api.pipeline.STORE.write_stage_metadata"), \
                 patch("service_api.pipeline.STORE.update_state"):
                strategy = _run_strategist("task-archetype", project_path, request_data)
        self.assertEqual(strategy["pages"][1]["content_archetype"], "dual_column")

    def test_normalize_content_archetype_infers_from_layout_and_assets(self) -> None:
        self.assertEqual(_normalize_content_archetype("", "content", "three_column", [], [], ""), "list_grid")
        self.assertEqual(_normalize_content_archetype("", "content", "split_left_right", [], [], ""), "dual_column")
        self.assertEqual(_normalize_content_archetype("", "content", "content", [], [], "demo.png"), "image_left_text_right")
        self.assertEqual(_normalize_content_archetype("", "ending", "ending", [], [], ""), "empty")

    def test_template_contract_table_maps_core_templates_to_families(self) -> None:
        self.assertTrue(TEMPLATE_CONTRACT_REGISTRY_PATH.exists())
        self.assertEqual(TEMPLATE_CONTRACTS["exhibit"], "consulting")
        self.assertEqual(TEMPLATE_CONTRACTS["pixel_retro"], "pixel_retro")
        self.assertEqual(TEMPLATE_CONTRACTS["government_blue"], "government")
        self.assertEqual(_get_template_contract("exhibit")["aliases"]["chapter_desc"], ["CHAPTER_DESC"])
        self.assertEqual(_get_template_contract("pixel_retro")["aliases"]["cta_text"], ["CTA_TEXT"])

    def test_template_contract_table_splits_generic_into_explicit_families(self) -> None:
        self.assertEqual(TEMPLATE_CONTRACTS["academic_defense"], "academic")
        self.assertEqual(TEMPLATE_CONTRACTS["medical_university"], "academic")
        self.assertEqual(TEMPLATE_CONTRACTS["重庆大学"], "academic")
        self.assertEqual(TEMPLATE_CONTRACTS["psychology_attachment"], "psychology")
        self.assertEqual(TEMPLATE_CONTRACTS["科技蓝商务"], "cn_corporate")
        self.assertEqual(TEMPLATE_CONTRACTS["招商银行"], "cn_corporate")
        self.assertIn("chapter_en", _get_template_contract("psychology_attachment")["aliases"])
        self.assertIn("logo_header", _get_template_contract("科技蓝商务")["aliases"])

    def test_template_contract_semantic_overrides_drive_psychology_fields(self) -> None:
        slide = {
            "index": 1,
            "page_type": "cover",
            "title": "心理课题",
            "subtitle": "PSYCHOLOGY",
            "highlight": "建立稳定心理支持机制",
            "goal": "提升韧性",
            "image_filename": "mind-cover.png",
            "sections": [],
            "key_points": [],
            "kpis": [],
        }
        strategy = {
            "project_name": "psy-demo",
            "use_case": "课题汇报",
            "audience": "教师",
            "presentation_title": "心理课题",
            "core_message": "建立稳定心理支持机制",
        }
        placeholders = _build_template_placeholders(slide, strategy, _get_template_contract("psychology_attachment"))
        self.assertEqual(placeholders["COVER_BG_IMAGE"], "mind-cover.png")
        self.assertEqual(placeholders["QUOTE"], "建立稳定心理支持机制")
        self.assertEqual(placeholders["TITLE_EN"], "PSYCHOLOGY")
        self.assertEqual(placeholders["CONTACT_LINE_2"], "心理课题")

    def test_template_contract_semantic_overrides_drive_pixel_cta(self) -> None:
        slide = {
            "index": 8,
            "page_type": "ending",
            "title": "感谢聆听",
            "subtitle": "",
            "highlight": "",
            "goal": "",
            "sections": [],
            "key_points": [],
            "kpis": [],
        }
        strategy = {
            "project_name": "pixel-demo",
            "use_case": "汇报",
            "audience": "领导",
            "presentation_title": "像素汇报",
            "core_message": "持续推进 AI 能力建设",
        }
        placeholders = _build_template_placeholders(slide, strategy, _get_template_contract("pixel_retro"))
        self.assertEqual(placeholders["CTA_TEXT"], "持续推进 AI 能力建设")

    def test_template_contract_layout_config_merges_family_overrides(self) -> None:
        consulting_lead = _get_template_layout_config(_get_template_contract("exhibit"), "lead_cards")
        government_dual = _get_template_layout_config(_get_template_contract("government_blue"), "dual_column")
        generic_image = _get_template_layout_config(_get_template_contract("unknown-template"), "image_left_text_right")
        self.assertEqual(consulting_lead["lead_height_multi"], 136)
        self.assertEqual(consulting_lead["outer_pad"], 24)
        self.assertEqual(government_dual["header_bar_height"], 10)
        self.assertEqual(government_dual["gap"], 16)
        self.assertEqual(generic_image["image_ratio"], 0.36)

    def test_pixel_example_exposes_pixel_retro_recommendation(self) -> None:
        detail_response = self.client.get("/api/v1/examples/ppt169_像素风_git_introduction")
        self.assertEqual(detail_response.status_code, 200)
        payload = detail_response.json()
        self.assertEqual(payload["style_profile"]["style_tag"], "pixel_retro")
        self.assertEqual(payload["style_profile"]["recommended_template"], "pixel_retro")
        self.assertEqual(payload["style_profile"]["style_source"], "llm_classified")

    def test_yijing_example_exposes_yijing_classic_profile(self) -> None:
        profile = extract_example_style_profile(resolve_example_dir("ppt169_易理风_地山谦卦深度研究"))
        self.assertEqual(profile["style_tag"], "yijing_classic")
        self.assertEqual(profile["recommended_template"], "")
        self.assertEqual(profile["page_archetypes"].get("cover"), "yijing_cover_taiji")
        self.assertEqual(profile["page_archetypes"].get("toc"), "yijing_toc_scroll")
        self.assertEqual(profile["page_archetypes"].get("ending"), "yijing_ending_quote")
        self.assertEqual(profile["theme"]["primary"], "#B8860B")
        self.assertEqual(profile["typography"]["body_size"], 18)

    def test_style_classifier_cache_hit_avoids_second_llm_call(self) -> None:
        example_dir = resolve_example_dir("ppt169_像素风_git_introduction")
        with patch(
            "service_api.examples._classify_style_with_llm",
            return_value={"style_tag": "pixel_retro", "recommended_template": "pixel_retro", "confidence": 0.99, "reason": "cached test"},
        ) as mock_classify:
            first = extract_example_style_profile(example_dir)
            second = extract_example_style_profile(example_dir)
        self.assertEqual(first["style_tag"], "pixel_retro")
        self.assertEqual(second["style_tag"], "pixel_retro")
        self.assertEqual(mock_classify.call_count, 1)

    def test_style_classifier_cache_invalidation_triggers_new_llm_call(self) -> None:
        example_dir = resolve_example_dir("ppt169_像素风_git_introduction")
        with patch("service_api.examples._build_example_classifier_fingerprint", side_effect=["fingerprint-a", "fingerprint-b"]):
            with patch(
                "service_api.examples._classify_style_with_llm",
                return_value={"style_tag": "pixel_retro", "recommended_template": "pixel_retro", "confidence": 0.99, "reason": "invalidate test"},
            ) as mock_classify:
                extract_example_style_profile(example_dir)
                extract_example_style_profile(example_dir)
        self.assertEqual(mock_classify.call_count, 2)

    def test_style_classifier_fallback_keeps_rule_result(self) -> None:
        example_dir = resolve_example_dir("ppt169_易理风_地山谦卦深度研究")
        with patch("service_api.examples._classify_style_with_llm", side_effect=RuntimeError("llm down")):
            profile = extract_example_style_profile(example_dir)
        self.assertEqual(profile["style_tag"], "yijing_classic")
        self.assertEqual(profile["style_source"], "rule_fallback")
        self.assertEqual(profile["style_confidence"], 0.0)

    def test_pixel_renderer_moves_subtitle_below_multi_line_title(self) -> None:
        slide = {
            "index": 5,
            "page_type": "content",
            "title": "MODULE 03: COMBAT SUPPORT",
            "subtitle": "Battle support and governance",
            "sections": [{"heading": "A", "items": ["x"]}, {"heading": "B", "items": ["y"]}],
            "highlight": "",
            "chart_type": "comparison",
        }
        strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#0D1117",
                "secondary_background": "#161B22",
                "primary": "#39FF14",
                "accent": "#00D4FF",
                "secondary_accent": "#FF2E97",
                "text": "#E6EDF3",
                "muted_text": "#8B949E",
                "border": "#30363D",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 20},
            "resolved_style_mode": "pixel_retro",
            "example_style_profile": {},
        }
        svg = render_slide_svg(slide, strategy, SETTINGS.materials_images_root)
        self.assertIn('y="182"', svg)
        self.assertIn("MODULE 03:", svg)

    def test_yijing_renderer_uses_dedicated_visual_language(self) -> None:
        slide = {
            "index": 3,
            "page_type": "content",
            "title": "地山谦：六十四卦中的唯一全吉之卦",
            "subtitle": "卦象结构解析与谦卦唯一性",
            "sections": [
                {"heading": "卦象结构解析", "items": ["上卦为地，下卦为山", "六爻层次体现内刚外柔", "谦以自牧，守正持中"]},
                {"heading": "谦卦唯一性", "items": ["六十四卦中罕见的全吉范式", "越是谦退越显其力量", "适合作为稳健治理的隐喻"]},
            ],
            "highlight": "谦，亨，君子有终。",
            "chart_type": "comparison",
            "example_archetype": "yijing_lines_panel",
        }
        strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#0D1117",
                "secondary_background": "#F5F3EF",
                "primary": "#B8860B",
                "accent": "#C94C4C",
                "secondary_accent": "#2D5A5A",
                "text": "#E8E4DC",
                "muted_text": "#8B9A9A",
                "border": "#4A5568",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 18},
            "resolved_style_mode": "yijing_classic",
            "example_style_profile": {},
        }
        svg = render_slide_svg(slide, strategy, SETTINGS.materials_images_root)
        self.assertIn("#B8860B", svg)
        self.assertIn("#2D5A5A", svg)
        self.assertIn("地山谦", svg)
        self.assertIn("六十四卦中的唯一全吉之卦", svg)

    def test_template_driven_cover_uses_template_structure(self) -> None:
        slide = {
            "index": 1,
            "page_type": "cover",
            "title": "模板驱动封面",
            "subtitle": "副标题",
            "sections": [],
            "highlight": "",
        }
        strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#FFFFFF",
                "secondary_background": "#F5F7FA",
                "primary": "#003366",
                "accent": "#C00000",
                "secondary_accent": "#007ACC",
                "text": "#333333",
                "muted_text": "#666666",
                "border": "#E0E0E0",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 20},
            "resolved_style_mode": "consulting_top",
            "resolved_template_name": "exhibit",
            "presentation_title": "模板驱动封面",
            "project_name": "template-demo",
            "page_count": 6,
            "example_style_profile": {},
        }
        template_dir = SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts" / "exhibit"
        svg = render_slide_svg(slide, strategy, SETTINGS.materials_images_root, template_dir)
        self.assertIn('stroke="#D4AF37"', svg)
        self.assertIn("模板驱动封面", svg)
        self.assertNotIn("{{TITLE}}", svg)

    def test_template_driven_content_replaces_placeholder_area(self) -> None:
        slide = {
            "index": 3,
            "page_type": "content",
            "title": "一、核心能力",
            "subtitle": "内容页",
            "sections": [
                {"heading": "数据治理", "items": ["统一底座", "标准接口"]},
                {"heading": "实战支撑", "items": ["模型研判", "快速响应"]},
            ],
            "kpis": [{"label": "覆盖单位", "value": "100+"}],
            "highlight": "模板内容区已回填",
            "key_points": ["统一底座", "实战支撑"],
        }
        strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#FFFFFF",
                "secondary_background": "#F5F7FA",
                "primary": "#003366",
                "accent": "#C00000",
                "secondary_accent": "#007ACC",
                "text": "#333333",
                "muted_text": "#666666",
                "border": "#E0E0E0",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 18},
            "resolved_style_mode": "consulting_top",
            "resolved_template_name": "exhibit",
            "presentation_title": "模板内容页",
            "project_name": "template-demo",
            "page_count": 6,
            "example_style_profile": {},
        }
        template_dir = SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts" / "exhibit"
        svg = render_slide_svg(slide, strategy, SETTINGS.materials_images_root, template_dir)
        self.assertIn("数据治理", svg)
        self.assertIn("模板内容区已回填", svg)
        self.assertNotIn("{{CONTENT_AREA}}", svg)

    def test_template_driven_content_uses_dual_column_archetype(self) -> None:
        slide = {
            "index": 3,
            "page_type": "content",
            "content_archetype": "dual_column",
            "title": "双栏页",
            "subtitle": "dual",
            "sections": [
                {"heading": "左栏", "items": ["统一底座", "标准接口"]},
                {"heading": "右栏", "items": ["模型研判", "快速响应"]},
            ],
            "kpis": [],
            "highlight": "",
            "key_points": ["统一底座", "模型研判"],
        }
        strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#FFFFFF",
                "secondary_background": "#F5F7FA",
                "primary": "#003366",
                "accent": "#C00000",
                "secondary_accent": "#007ACC",
                "text": "#333333",
                "muted_text": "#666666",
                "border": "#E0E0E0",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 18},
            "resolved_style_mode": "consulting_top",
            "resolved_template_name": "exhibit",
            "presentation_title": "模板内容页",
            "project_name": "template-demo",
            "page_count": 6,
            "example_style_profile": {},
        }
        template_dir = SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts" / "exhibit"
        svg = render_slide_svg(slide, strategy, SETTINGS.materials_images_root, template_dir)
        self.assertIn("左栏", svg)
        self.assertIn("右栏", svg)
        self.assertGreaterEqual(svg.count('rx="16" fill="#F5F7FA" stroke="#E0E0E0" stroke-width="1"'), 2)

    def test_template_driven_dual_column_footer_summary_follows_profile(self) -> None:
        slide = {
            "index": 3,
            "page_type": "content",
            "content_archetype": "dual_column",
            "title": "双栏页",
            "subtitle": "dual",
            "sections": [
                {"heading": "左栏", "items": ["统一底座", "标准接口"]},
                {"heading": "右栏", "items": ["模型研判", "快速响应"]},
                {"heading": "扩展总结", "items": ["补充说明"]},
            ],
            "kpis": [],
            "highlight": "",
            "key_points": ["统一底座", "模型研判", "扩展总结"],
        }
        base_strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#FFFFFF",
                "secondary_background": "#F5F7FA",
                "primary": "#003366",
                "accent": "#C00000",
                "secondary_accent": "#007ACC",
                "text": "#333333",
                "muted_text": "#666666",
                "border": "#E0E0E0",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 18},
            "presentation_title": "模板内容页",
            "project_name": "template-demo",
            "page_count": 6,
            "example_style_profile": {},
        }
        consulting_svg = render_slide_svg(
            slide,
            {**base_strategy, "resolved_style_mode": "consulting_top", "resolved_template_name": "exhibit"},
            SETTINGS.materials_images_root,
            SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts" / "exhibit",
        )
        government_svg = render_slide_svg(
            slide,
            {**base_strategy, "resolved_style_mode": "government_modern", "resolved_template_name": "government_blue"},
            SETTINGS.materials_images_root,
            SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts" / "government_blue",
        )
        self.assertIn("扩展总结", consulting_svg)
        self.assertNotIn("扩展总结", government_svg)

    def test_template_driven_lead_cards_kpi_zone_follows_profile(self) -> None:
        slide = {
            "index": 3,
            "page_type": "content",
            "content_archetype": "lead_cards",
            "title": "核心能力",
            "subtitle": "",
            "sections": [
                {"heading": "数据治理", "items": ["统一底座", "标准接口"]},
                {"heading": "实战支撑", "items": ["模型研判", "快速响应"]},
            ],
            "kpis": [{"label": "覆盖单位", "value": "100+"}, {"label": "模型数", "value": "30+"}],
            "highlight": "",
            "key_points": ["统一底座", "模型研判"],
        }
        strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#FFFFFF",
                "secondary_background": "#F5F7FA",
                "primary": "#003366",
                "accent": "#C00000",
                "secondary_accent": "#007ACC",
                "text": "#333333",
                "muted_text": "#666666",
                "border": "#E0E0E0",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 18},
            "resolved_style_mode": "government_modern",
            "resolved_template_name": "government_blue",
            "presentation_title": "政务模板内容页",
            "project_name": "gov-demo",
            "page_count": 6,
            "example_style_profile": {},
        }
        template_dir = SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts" / "government_blue"
        svg = render_slide_svg(slide, strategy, SETTINGS.materials_images_root, template_dir)
        self.assertIn("覆盖单位", svg)
        self.assertIn("100+", svg)

    def test_template_driven_chapter_replaces_contract_aliases(self) -> None:
        slide = {
            "index": 2,
            "page_type": "chapter",
            "content_archetype": "empty",
            "title": "第二章 能力体系",
            "subtitle": "CAPABILITY SYSTEM",
            "goal": "章节说明",
            "sections": [],
            "kpis": [],
            "highlight": "",
            "key_points": [],
        }
        strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#0D1117",
                "secondary_background": "#111C33",
                "primary": "#F5B83D",
                "accent": "#E76F51",
                "secondary_accent": "#60A5FA",
                "text": "#F8FAFC",
                "muted_text": "#CBD5E1",
                "border": "#334155",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 20},
            "resolved_style_mode": "consulting_top",
            "resolved_template_name": "exhibit",
            "presentation_title": "模板章节页",
            "project_name": "template-demo",
            "page_count": 6,
            "audience": "省公安厅",
            "example_style_profile": {},
        }
        template_dir = SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts" / "exhibit"
        svg = render_slide_svg(slide, strategy, SETTINGS.materials_images_root, template_dir)
        self.assertIn("第二章 能力体系", svg)
        self.assertIn("章节说明", svg)
        self.assertNotIn("{{CHAPTER_TITLE}}", svg)
        self.assertNotIn("{{CHAPTER_DESC}}", svg)

    def test_template_driven_pixel_ending_populates_summary_contract(self) -> None:
        slide = {
            "index": 8,
            "page_type": "ending",
            "content_archetype": "empty",
            "title": "感谢聆听",
            "subtitle": "像素收尾页",
            "sections": [
                {"heading": "成果回顾", "items": ["统一底座", "模型提效", "支撑实战"]},
                {"heading": "能力清单", "items": ["研判", "预警", "调度"]},
            ],
            "kpis": [{"label": "覆盖单位", "value": "100+"}, {"label": "模型数", "value": "30+"}],
            "highlight": "继续推进 AI 能力建设",
            "key_points": ["统一底座", "模型提效", "支撑实战"],
        }
        strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#0D1117",
                "secondary_background": "#161B22",
                "primary": "#39FF14",
                "accent": "#00D4FF",
                "secondary_accent": "#FF2E97",
                "text": "#E6EDF3",
                "muted_text": "#8B949E",
                "border": "#30363D",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 18},
            "resolved_style_mode": "pixel_retro",
            "resolved_template_name": "pixel_retro",
            "presentation_title": "像素结束页",
            "project_name": "template-demo",
            "page_count": 8,
            "core_message": "继续推进 AI 能力建设",
            "example_style_profile": {},
        }
        template_dir = SETTINGS.repo_root / "skills" / "ppt-master" / "templates" / "layouts" / "pixel_retro"
        svg = render_slide_svg(slide, strategy, SETTINGS.materials_images_root, template_dir)
        self.assertIn("成果回顾", svg)
        self.assertIn("能力清单", svg)
        self.assertIn("继续推进 AI 能力建设", svg)
        self.assertNotIn("{{SUMMARY_1_TITLE}}", svg)
        self.assertNotIn("{{CTA_TEXT}}", svg)

    def test_template_driver_falls_back_to_style_renderer_when_template_missing(self) -> None:
        slide = {
            "index": 2,
            "page_type": "content",
            "title": "Fallback",
            "subtitle": "retro",
            "sections": [{"heading": "A", "items": ["B"]}],
            "highlight": "",
            "chart_type": "",
        }
        strategy = {
            "canvas_format": "ppt169",
            "theme": {
                "background": "#0D1117",
                "secondary_background": "#161B22",
                "primary": "#39FF14",
                "accent": "#00D4FF",
                "secondary_accent": "#FF2E97",
                "text": "#E6EDF3",
                "muted_text": "#8B949E",
                "border": "#30363D",
            },
            "typography": {"title_font": "Microsoft YaHei", "body_font": "Microsoft YaHei", "emphasis_font": "SimHei", "body_size": 20},
            "resolved_style_mode": "pixel_retro",
            "resolved_template_name": "pixel_retro",
            "example_style_profile": {},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            svg = render_slide_svg(slide, strategy, SETTINGS.materials_images_root, Path(tmpdir))
        self.assertIn("#39FF14", svg)
        self.assertIn("Fallback", svg)

    def test_create_task_rejects_unknown_example_reference(self) -> None:
        payload = {
            "source_mode": "path",
            "project_name": "style-demo",
            "canvas_format": "ppt169",
            "example_reference": "not_exists_example",
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": ["native_pptx", "svg_pptx"],
            "source_files": ["sample.md"],
            "image_files": [],
        }
        response = self.client.post("/api/v1/tasks", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Example not found", response.text)

    def test_create_task_accepts_multipart_with_real_source_file(self) -> None:
        data = {
            "source_mode": "upload",
            "project_name": "upload-demo",
            "canvas_format": "ppt169",
            "example_reference": self.client.get("/api/v1/examples").json()["examples"][0]["name"],
            "audience": "领导",
            "use_case": "汇报",
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": '["native_pptx","svg_pptx"]',
        }
        files = {
            "source_files": ("sample.docx", io.BytesIO(b"non-empty-doc"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        }
        with patch("service_api.main.run_task", lambda task_id: None):
            response = self.client.post("/api/v1/tasks", data=data, files=files)
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        try:
            uploaded = SETTINGS.uploads_root / task_id / "source_files" / "sample.docx"
            self.assertTrue(uploaded.exists())
            self.assertEqual(uploaded.read_bytes(), b"non-empty-doc")
        finally:
            shutil.rmtree(SETTINGS.jobs_root / task_id, ignore_errors=True)
            shutil.rmtree(SETTINGS.uploads_root / task_id, ignore_errors=True)

    def test_multipart_blank_project_name_is_auto_generated(self) -> None:
        data = {
            "source_mode": "upload",
            "project_name": "",
            "canvas_format": "ppt169",
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": '["native_pptx","svg_pptx"]',
        }
        files = {
            "source_files": ("sample.docx", io.BytesIO(b"non-empty-doc"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        }
        with patch("service_api.main.run_task", lambda task_id: None):
            response = self.client.post("/api/v1/tasks", data=data, files=files)
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        try:
            state_payload = self.client.get(f"/api/v1/tasks/{task_id}").json()
            self.assertTrue(state_payload["request"]["project_name"].startswith("ppt_task_"))
        finally:
            shutil.rmtree(SETTINGS.jobs_root / task_id, ignore_errors=True)
            shutil.rmtree(SETTINGS.uploads_root / task_id, ignore_errors=True)

    def test_create_task_rejects_zero_byte_multipart_source_file(self) -> None:
        data = {
            "source_mode": "upload",
            "project_name": "upload-demo-zero",
            "canvas_format": "ppt169",
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": '["native_pptx","svg_pptx"]',
        }
        files = {
            "source_files": ("empty.docx", io.BytesIO(b""), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        }
        response = self.client.post("/api/v1/tasks", data=data, files=files)
        self.assertEqual(response.status_code, 400)
        self.assertIn("No valid uploaded source files were received", response.text)

    def test_create_task_accepts_multipart_with_source_and_image_files(self) -> None:
        data = {
            "source_mode": "upload",
            "project_name": "upload-demo-assets",
            "canvas_format": "ppt169",
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": '["native_pptx","svg_pptx"]',
        }
        files = [
            ("source_files", ("sample.docx", io.BytesIO(b"doc-content"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
            ("image_files", ("cover.png", io.BytesIO(b"png-content"), "image/png")),
        ]
        with patch("service_api.main.run_task", lambda task_id: None):
            response = self.client.post("/api/v1/tasks", data=data, files=files)
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        try:
            source_uploaded = SETTINGS.uploads_root / task_id / "source_files" / "sample.docx"
            image_uploaded = SETTINGS.uploads_root / task_id / "image_files" / "cover.png"
            self.assertTrue(source_uploaded.exists())
            self.assertTrue(image_uploaded.exists())
        finally:
            shutil.rmtree(SETTINGS.jobs_root / task_id, ignore_errors=True)
            shutil.rmtree(SETTINGS.uploads_root / task_id, ignore_errors=True)

    def test_create_task_accepts_inline_json_source_text(self) -> None:
        payload = {
            "source_mode": "inline",
            "project_name": "inline-json-demo",
            "canvas_format": "ppt169",
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": ["native_pptx", "svg_pptx"],
            "source_text": "# Title\n\nDirect inline content",
            "image_files": [],
        }
        with patch("service_api.main.run_task", lambda task_id: None):
            response = self.client.post("/api/v1/tasks", json=payload)
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        try:
            state_payload = self.client.get(f"/api/v1/tasks/{task_id}").json()
            self.assertEqual(state_payload["request"]["source_mode"], "inline")
            self.assertIn("Direct inline content", state_payload["request"]["source_text"])
        finally:
            shutil.rmtree(SETTINGS.jobs_root / task_id, ignore_errors=True)
            shutil.rmtree(SETTINGS.uploads_root / task_id, ignore_errors=True)

    def test_create_task_rejects_blank_inline_json_source_text(self) -> None:
        payload = {
            "source_mode": "inline",
            "project_name": "inline-json-empty",
            "canvas_format": "ppt169",
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": ["native_pptx", "svg_pptx"],
            "source_text": "   ",
            "image_files": [],
        }
        response = self.client.post("/api/v1/tasks", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("source_text", response.text)

    def test_create_task_accepts_multipart_inline_source_text(self) -> None:
        data = {
            "source_mode": "inline",
            "project_name": "inline-multipart-demo",
            "canvas_format": "ppt169",
            "prefer_style": "auto",
            "notes_style": "formal",
            "output_formats": '["native_pptx","svg_pptx"]',
            "source_text": "# Inline\n\nMultipart text body",
        }
        files = [
            ("image_files", ("cover.png", io.BytesIO(b"png-content"), "image/png")),
        ]
        with patch("service_api.main.run_task", lambda task_id: None):
            response = self.client.post("/api/v1/tasks", data=data, files=files)
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        try:
            state_payload = self.client.get(f"/api/v1/tasks/{task_id}").json()
            self.assertEqual(state_payload["request"]["source_mode"], "inline")
            self.assertIn("Multipart text body", state_payload["request"]["source_text"])
            image_uploaded = SETTINGS.uploads_root / task_id / "image_files" / "cover.png"
            self.assertTrue(image_uploaded.exists())
        finally:
            shutil.rmtree(SETTINGS.jobs_root / task_id, ignore_errors=True)
            shutil.rmtree(SETTINGS.uploads_root / task_id, ignore_errors=True)

    def test_normalize_template_name_treats_auto_as_empty(self) -> None:
        self.assertEqual(_normalize_template_name("auto"), "")
        self.assertEqual(_normalize_template_name("AUTO"), "")
        self.assertEqual(_normalize_template_name("none"), "")
        self.assertEqual(_normalize_template_name("smart_red"), "smart_red")


if __name__ == "__main__":
    unittest.main()
