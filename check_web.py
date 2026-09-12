"""Parse the portal JavaScript.

The three portals have no build step and no framework, which is deliberate, but it
means a syntax error in an inline <script> block reaches a browser with nothing in
between. This is the thing in between.

    .venv/bin/python check_web.py

Skips with a notice if node is unavailable, so it never blocks a local run. In CI,
node is installed, so it actually runs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("node not found, skipping portal syntax check")
        return 0

    targets: list[tuple[str, str]] = []
    for page in sorted(WEB.glob("*.html")):
        blocks = re.findall(r"<script>(.*?)</script>", page.read_text(), re.S)
        # A page whose inline script vanished means the extraction broke, not that
        # the page is clean. Silently checking nothing is the failure mode this
        # script exists to avoid.
        if not blocks:
            print(f"FAIL: no inline script found in {page.name}", file=sys.stderr)
            return 1
        for i, block in enumerate(blocks):
            targets.append((f"{page.stem}[{i}]", block))

    for js in sorted(WEB.glob("*.js")):
        targets.append((js.name, js.read_text()))

    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for label, source in targets:
            path = Path(tmp) / "check.js"
            path.write_text(source)
            proc = subprocess.run([node, "--check", str(path)],
                                  capture_output=True, text=True)
            if proc.returncode:
                failed += 1
                print(f"FAIL: {label}\n{proc.stderr.strip()}", file=sys.stderr)
            else:
                print(f"  ok  {label}")

    print(f"\n{len(targets)} script blocks checked, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
