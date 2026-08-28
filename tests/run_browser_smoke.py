#!/usr/bin/env python3
"""Stage the static site and run Playwright smoke tests."""
from __future__ import annotations

import functools
import http.server
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rate-window-smoke-") as temporary:
        stage = Path(temporary)
        shutil.copytree(PROJECT / "frontend", stage, dirs_exist_ok=True)
        (stage / "data").mkdir()
        shutil.copy2(PROJECT / "data" / "rates.json", stage / "data" / "rates.json")
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=stage)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            environment = os.environ.copy()
            environment["SMOKE_BASE"] = f"http://127.0.0.1:{server.server_port}/"
            subprocess.run(
                ["node", str(PROJECT / "tests" / "browser_smoke.js")],
                check=True,
                timeout=120,
                env=environment,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
