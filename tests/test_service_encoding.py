from __future__ import annotations

import io
import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

from service_api.pipeline import _check_export_dependencies, _run_script
from service_api.storage import STORE


def test_task_log_preserves_unicode_with_gbk_console() -> None:
    message = "中文目录 Ŀ 😀"
    buffer = io.BytesIO()
    console = io.TextIOWrapper(buffer, encoding="gbk", errors="strict")
    with tempfile.TemporaryDirectory() as directory:
        log_path = Path(directory) / "run.log"
        with patch.object(STORE, "log_path", return_value=log_path), patch("sys.stdout", console):
            STORE.append_log("encoding-test", message)
        assert message in log_path.read_text(encoding="utf-8")
        output = buffer.getvalue().decode("gbk")
        assert "中文目录" in output
        assert "\\u013f" in output
        assert "\\U0001f600" in output
    console.close()


def test_export_dependency_error_identifies_service_python() -> None:
    with patch("service_api.pipeline.importlib.import_module", side_effect=ModuleNotFoundError("No module named 'pptx'")):
        with pytest.raises(RuntimeError) as error:
            _check_export_dependencies()
    assert "No module named 'pptx'" in str(error.value)
    assert sys.executable in str(error.value)
    assert "api_requirements.txt" in str(error.value)


def test_script_failure_reports_underlying_error() -> None:
    command = [sys.executable, "-c", "raise ModuleNotFoundError(\"No module named 'pptx'\")"]
    with patch.object(STORE, "append_log"):
        with pytest.raises(RuntimeError) as error:
            _run_script("failed-export", command)
    assert "Command failed (1)" in str(error.value)
    assert "ModuleNotFoundError: No module named 'pptx'" in str(error.value)


def test_script_output_round_trips_unicode_under_gbk_environment() -> None:
    message = "02_目录 Ŀ 😀"
    buffer = io.BytesIO()
    console = io.TextIOWrapper(buffer, encoding="gbk", errors="strict")
    # Use ASCII source so this also exercises redirected child output on Windows.
    command = [sys.executable, "-c", f"print({ascii(message)})"]
    with tempfile.TemporaryDirectory() as directory:
        log_path = Path(directory) / "run.log"
        with (
            patch.dict(os.environ, {"PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"}),
            patch.object(STORE, "log_path", return_value=log_path),
            patch("sys.stdout", console),
        ):
            _run_script("encoding-test", command)
        output = log_path.read_text(encoding="utf-8")
        assert message in output
        assert "\ufffd" not in output
    console.close()
