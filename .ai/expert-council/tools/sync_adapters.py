#!/usr/bin/env python3
"""Regenerate the thin provider adapters from the canonical skills.

Canonical skills live in `.ai/expert-council/skills/`. `.claude/skills/` and
`.codex/skills/` contain pointers only — never expert knowledge — so they are
generated, not maintained by hand.

Usage:  python .ai/expert-council/tools/sync_adapters.py [--check]
        --check exits 1 if any adapter is missing or stale (CI-friendly).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _yamlish  # noqa: E402

TOOLS = Path(__file__).resolve().parent
COUNCIL = TOOLS.parent
REPO = COUNCIL.parent.parent
SKILLS = COUNCIL / "skills"
PROVIDERS = {"claude": REPO / ".claude" / "skills", "codex": REPO / ".codex" / "skills"}

TEMPLATE = """---
name: {name}
description: {description}
---

# {title}

Canonical skill:

`{pointer}`

Read and follow the canonical skill above. Load its linked `references/` files only
when that skill says the task needs them.

This file is a generated adapter — do not add expert content here. Edit the canonical
skill instead, then run `python .ai/expert-council/tools/sync_adapters.py`.
"""


def title_of(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def main(check_only: bool = False) -> int:
    stale: list[str] = []
    written = 0
    for folder in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            print(f"skip {folder.name}: no SKILL.md")
            continue
        text = skill_md.read_text(encoding="utf-8")
        fm, err = _yamlish.parse_frontmatter(text)
        if err:
            print(f"skip {folder.name}: {err}")
            continue
        name = fm.get("name") or folder.name
        description = fm.get("description") or ""
        title = title_of(text, name)

        for provider, root in PROVIDERS.items():
            target = root / name / "SKILL.md"
            pointer = "../../../.ai/expert-council/skills/%s/SKILL.md" % name
            content = TEMPLATE.format(name=name, description=description, title=title, pointer=pointer)
            current = target.read_text(encoding="utf-8") if target.is_file() else None
            if current == content:
                continue
            if check_only:
                stale.append(str(target.relative_to(REPO)).replace("\\", "/"))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written += 1

    if check_only:
        for path in stale:
            print(f"STALE {path}")
        if stale:
            print(f"\nsync_adapters: {len(stale)} adapter(s) out of date")
            return 1
        print("sync_adapters: all adapters current")
        return 0

    print(f"sync_adapters: wrote {written} adapter file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(check_only="--check" in sys.argv))
