from __future__ import annotations

import io
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from service_api.main import app  # noqa: E402
from service_api.config import SETTINGS  # noqa: E402


class ServiceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        (SETTINGS.materials_docs_root / "sample.md").write_text("# Sample\n\nHello", encoding="utf-8")
        (SETTINGS.materials_images_root / "sample.png").write_bytes(b"fake")

    @classmethod
    def tearDownClass(cls) -> None:
        for path in [
            SETTINGS.materials_docs_root / "sample.md",
            SETTINGS.materials_images_root / "sample.png",
        ]:
            if path.exists():
                path.unlink()

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

    def test_example_detail_and_download_are_available(self) -> None:
        list_response = self.client.get("/api/v1/examples")
        example_name = list_response.json()["examples"][0]["name"]

        detail_response = self.client.get(f"/api/v1/examples/{example_name}")
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["example"]["name"], example_name)
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
        finally:
            shutil.rmtree(SETTINGS.jobs_root / task_id, ignore_errors=True)

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


if __name__ == "__main__":
    unittest.main()
