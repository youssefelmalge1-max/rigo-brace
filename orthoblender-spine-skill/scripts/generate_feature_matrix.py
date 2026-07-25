"""Generate a Markdown feature matrix of all rigo_brace operators.

Static scan: for each operators/*.py, list bl_idname + bl_label + one-line docstring.
Run from repo root:
  python orthoblender-spine-skill/scripts/generate_feature_matrix.py > feature_matrix.md
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OPS = os.path.join(ROOT, "rigo_brace", "operators")

CLS_RE = re.compile(
    r'class\s+(\w+)\([^)]*\):\s*\n\s*("""(?P<doc>.*?)""")?', re.S
)
ID_RE = re.compile(r"bl_idname\s*=\s*[\"']([\w.]+)[\"']")
LABEL_RE = re.compile(r"bl_label\s*=\s*[\"'](.*?)[\"']")


def main():
    print("# rigo_brace Feature Matrix\n")
    print("| Module | idname | Label | Purpose |")
    print("|---|---|---|---|")
    for name in sorted(os.listdir(OPS)):
        if not name.endswith(".py") or name == "__init__.py":
            continue
        with open(os.path.join(OPS, name), "r", encoding="utf-8") as fh:
            src = fh.read()
        # split on class boundaries to pair idname/label/doc
        blocks = re.split(r"\nclass ", src)
        for blk in blocks:
            idm = ID_RE.search(blk)
            if not idm:
                continue
            lab = LABEL_RE.search(blk)
            docm = re.search(r'"""(.*?)"""', blk, re.S)
            doc = (docm.group(1).strip().splitlines()[0] if docm else "").strip()
            print(f"| {name} | {idm.group(1)} | {lab.group(1) if lab else ''} | {doc} |")


if __name__ == "__main__":
    main()
