"""Build a Blender-installable zip of the rigo_brace extension.

Run from the project root:  python build.py
Produces: rigo_brace.zip  (install via Preferences > Get Extensions >
Install from Disk).
"""

import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = "rigo_brace"
OUT = os.path.join(HERE, "rigo_brace.zip")


def main():
    src = os.path.join(HERE, PKG)
    if not os.path.isdir(src):
        raise SystemExit(f"Cannot find package folder: {src}")

    if os.path.exists(OUT):
        os.remove(OUT)

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src):
            if "__pycache__" in root:
                continue
            for name in files:
                if name.endswith(".pyc"):
                    continue
                full = os.path.join(root, name)
                arc = os.path.relpath(full, HERE)
                zf.write(full, arc)

    print(f"Created {OUT}")


if __name__ == "__main__":
    main()
