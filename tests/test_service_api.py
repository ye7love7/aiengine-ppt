from __future__ import annotations

import io
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from service_api.config import SETTINGS  # noqa: E402
from service_api.examples import extract_example_style_profile, resolve_example_dir  # noqa: E402
from service_api.main import app  # noqa: E402
from service_api.pipeline import _normalize_template_name  # noqa: E402
from service_api.rendering import render_slide_svg  # noqa: E402


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

    def test_normalize_template_name_treats_auto_as_empty(self) -> None:
        self.assertEqual(_normalize_template_name("auto"), "")
        self.assertEqual(_normalize_template_name("AUTO"), "")
        self.assertEqual(_normalize_template_name("none"), "")
        self.assertEqual(_normalize_template_name("smart_red"), "smart_red")


if __name__ == "__main__":
    unittest.main()
