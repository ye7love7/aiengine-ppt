"""Exercise cmd -> launcher -> detached child without running a real API server."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows launcher")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fails", [False, True])
def test_background_launcher_returns_and_tracks_child(tmp_path, fails):
    # Stand in for uvicorn so no network or API calls are required.
    package = tmp_path / "uvicorn"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    source = "raise RuntimeError('simulated startup failure')" if fails else (
        "import time\nprint('中文 Ŀ', flush=True)\ntime.sleep(60)"
    )
    (package / "__main__.py").write_text(source, encoding="utf-8")
    log_dir = tmp_path / "中文 logs"
    pid_file = log_dir / "service.pid"
    out_file = log_dir / "out.log"
    err_file = log_dir / "err.log"
    env = os.environ.copy()
    env.update({
        "PATH": str(Path(sys.executable).parent) + os.pathsep + env["PATH"],
        "PYTHONPATH": str(tmp_path),
        "PPT_SERVICE_LOG_DIR": str(log_dir),
        "PPT_SERVICE_PID_FILE": str(pid_file),
        "PPT_SERVICE_STDOUT_LOG": str(out_file),
        "PPT_SERVICE_STDERR_LOG": str(err_file),
    })
    try:
        result = subprocess.run(
            ["cmd", "/d", "/c", str(ROOT / "start_windows.bat")],
            env=env, capture_output=True, timeout=15,
        )
        if fails:
            assert result.returncode == 1
            assert not pid_file.exists()
            assert "simulated startup failure" in err_file.read_text(encoding="utf-8")
        else:
            assert result.returncode == 0, repr(result.stdout + result.stderr)
            assert pid_file.read_text(encoding="ascii").strip().isdigit()
            assert "中文 Ŀ" in out_file.read_text(encoding="utf-8")
            # The launcher has exited, while the detached child remains alive.
            pid = pid_file.read_text(encoding="ascii").strip()
            status = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"], capture_output=True)
            assert f'"{pid}"'.encode() in status.stdout
    finally:
        if pid_file.exists():
            pid = pid_file.read_text(encoding="ascii").strip()
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
