"""Print the rigo_brace add-on structure: modules, operator classes, panels.

Plain Python (no bpy needed) — static scan of the source tree.
Run from the repo root:  python orthoblender-spine-skill/scripts/inspect_addon_structure.py
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
ADDON = os.path.join(ROOT, "rigo_brace")

OP_RE = re.compile(r"bl_idname\s*=\s*[\"']([\w.]+)[\"']")
CLS_RE = re.compile(r"^class\s+(\w+)\s*\(", re.M)


def main():
    if not os.path.isdir(ADDON):
        raise SystemExit(f"add-on not found: {ADDON}")
    for dirpath, _dirs, files in os.walk(ADDON):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT)
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            classes = CLS_RE.findall(src)
            idnames = OP_RE.findall(src)
            if classes or idnames:
                print(f"\n{rel}")
                for c in classes:
                    print(f"    class {c}")
                for i in idnames:
                    print(f"    idname {i}")


if __name__ == "__main__":
    main()
