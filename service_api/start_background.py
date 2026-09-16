"""Start the Windows service without inheriting the launcher's console/pipes."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    pid_file = Path(os.environ["PID_FILE"])
    stdout_path = Path(os.environ["STDOUT_LOG"])
    stderr_path = Path(os.environ["STDERR_LOG"])
    for path in (pid_file, stdout_path, stderr_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    command = [sys.executable, "-m", "uvicorn", "service_api.main:app",
               "--host", os.environ["HOST"], "--port", os.environ["PORT"]]
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            command, cwd=root, env=child_env,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    try:
        pid_file.write_text(str(process.pid) + "\n", encoding="ascii")
    except OSError:
        process.terminate()
        process.wait(timeout=10)
        raise
    # Report immediate startup failures (e.g. missing imports or occupied port).
    for _ in range(20):
        if process.poll() is not None:
            pid_file.unlink(missing_ok=True)
            print(f"[ERROR] Service exited with code {process.returncode}. See {stderr_path}")
            return 1
        time.sleep(0.1)
    print(f"[INFO] Service launched in background. PID: {process.pid}")
    print(f"[INFO] Stdout log: {stdout_path}")
    print(f"[INFO] Stderr log: {stderr_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
