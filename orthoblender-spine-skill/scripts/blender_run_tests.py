"""Run all rigo_brace GUI tests and collect their result files.

Driver script (plain Python) — launches Blender once per tools/*test.py, then
reads each <name>_result.txt and prints a PASS/FAIL summary.

Run from the repo root:  python orthoblender-spine-skill/scripts/blender_run_tests.py
(Re-run ../install.ps1 first so the tests exercise the latest installed add-on.)
"""

import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
TOOLS = os.path.join(ROOT, "tools")
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"

# Functional tests (skip the headless *exp.py probes and screenshot scripts).
TESTS = [
    "selftest", "selecttest", "paintkeeptest", "painttooltest", "applyunitstest",
    "bendtest", "stretchtest", "planestest", "padtest", "padshapetest",
    "viewtest", "historytest",
]


def main():
    if not os.path.exists(BLENDER):
        raise SystemExit(f"Blender not found: {BLENDER}")
    summary = []
    for name in TESTS:
        script = os.path.join(TOOLS, f"{name}.py")
        if not os.path.exists(script):
            summary.append((name, "MISSING"))
            continue
        subprocess.run(
            [BLENDER, "--app-template", "rigo_brace", "--python", script],
            cwd=ROOT, capture_output=True,
        )
        result = os.path.join(ROOT, f"{name}_result.txt")
        verdict = "NO RESULT"
        if os.path.exists(result):
            text = open(result, encoding="utf-8").read()
            m = re.search(r"(ALL_)?PASS=(True|False)", text)
            verdict = m.group(0) if m else "?"
        summary.append((name, verdict))
        print(f"{name:16s} {verdict}")
    print("\n=== summary ===")
    for name, verdict in summary:
        print(f"{name:16s} {verdict}")


if __name__ == "__main__":
    main()
