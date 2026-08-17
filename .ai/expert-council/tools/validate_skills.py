#!/usr/bin/env python3
"""Validate the Expert Council skill architecture.

Checks, in order:
  1.  every canonical skill folder has a SKILL.md
  2.  every SKILL.md has parseable YAML frontmatter
  3.  frontmatter `name` exists and matches the folder name
  4.  frontmatter `description` exists and is specific enough to route on
  5.  skill names are unique
  6.  every file referenced from a SKILL.md exists
  7.  every REGISTRY.yaml path exists, and registry/filesystem agree both ways
  8.  a Claude adapter exists for every canonical skill
  9.  a Codex adapter exists for every canonical skill
 10.  no adapter embeds expert context (adapters stay thin)
 11.  no broken relative paths in adapters, and no always-loaded file tells an
      agent to load the archival combined bundles

Usage:  python .ai/expert-council/tools/validate_skills.py [--verbose]
Exit code 0 = pass, 1 = failures.
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
REGISTRY = COUNCIL / "REGISTRY.yaml"
ADAPTER_ROOTS = {"claude": REPO / ".claude" / "skills", "codex": REPO / ".codex" / "skills"}

ADAPTER_MAX_BYTES = 2000
COMBINED_BUNDLES = ("ALL_EXPERT_CONTEXT_COMBINED.md", "EXPERT_SKILLS_01_15_COMBINED.md")
MIN_DESCRIPTION_CHARS = 80

errors: list[str] = []
warnings: list[str] = []
notes: list[str] = []


def fail(check: str, message: str) -> None:
    errors.append(f"[{check}] {message}")


def warn(check: str, message: str) -> None:
    warnings.append(f"[{check}] {message}")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def referenced_paths(text: str) -> set[str]:
    """Backtick-quoted references/... paths mentioned in a SKILL.md."""
    found = set()
    for chunk in text.split("`")[1::2]:
        chunk = chunk.strip()
        if chunk.startswith("references/") and chunk.endswith((".md", ".yaml", ".json")):
            found.add(chunk)
    return found


def main(verbose: bool = False) -> int:
    if not SKILLS.is_dir():
        fail("layout", f"canonical skills directory missing: {rel(SKILLS)}")
        return report()

    skill_dirs = sorted(p for p in SKILLS.iterdir() if p.is_dir())
    if not skill_dirs:
        fail("layout", "no canonical skills found")
        return report()

    names: dict[str, Path] = {}
    canonical: dict[str, dict] = {}

    for folder in skill_dirs:
        skill_md = folder / "SKILL.md"

        # 1. SKILL.md exists
        if not skill_md.is_file():
            fail("1-skill-md", f"{rel(folder)} has no SKILL.md")
            continue
        text = read(skill_md)

        # 2. frontmatter parses
        fm, err = _yamlish.parse_frontmatter(text)
        if err:
            fail("2-frontmatter", f"{rel(skill_md)}: {err}")
            continue

        # 3. name
        name = fm.get("name")
        if not name:
            fail("3-name", f"{rel(skill_md)}: frontmatter has no `name`")
        elif name != folder.name:
            fail("3-name", f"{rel(skill_md)}: name '{name}' != folder '{folder.name}'")

        # 4. description
        desc = fm.get("description")
        if not desc:
            fail("4-description", f"{rel(skill_md)}: frontmatter has no `description`")
        elif len(str(desc)) < MIN_DESCRIPTION_CHARS:
            warn(
                "4-description",
                f"{rel(skill_md)}: description is only {len(str(desc))} chars; "
                "descriptions are the primary routing signal",
            )

        # 5. uniqueness
        if name:
            if name in names:
                fail("5-unique", f"duplicate skill name '{name}' in {rel(folder)} and {rel(names[name])}")
            names[name] = folder
            canonical[name] = {"folder": folder, "text": text, "fm": fm}

        # 6. references resolve
        refs_dir = folder / "references"
        if not refs_dir.is_dir():
            warn("6-references", f"{rel(folder)} has no references/ directory")
        for ref in sorted(referenced_paths(text)):
            if not (folder / ref).is_file():
                fail("6-references", f"{rel(skill_md)} references missing file '{ref}'")
        # a reference file that nothing points at is dead weight
        if refs_dir.is_dir():
            mentioned = referenced_paths(text)
            for ref_file in sorted(refs_dir.iterdir()):
                if ref_file.is_file() and f"references/{ref_file.name}" not in mentioned:
                    warn("6-references", f"{rel(ref_file)} is not referenced from SKILL.md")

        # 11b. canonical skills must not tell agents to load the combined bundles
        for bundle in COMBINED_BUNDLES:
            if bundle in text and "Never load" not in text and "never load" not in text.lower():
                warn("11-context", f"{rel(skill_md)} mentions {bundle} without a do-not-load warning")

    # 7. registry
    if not REGISTRY.is_file():
        fail("7-registry", f"missing {rel(REGISTRY)}")
        registry = {}
    else:
        registry = _yamlish.load(read(REGISTRY)) or {}

    reg_skills = registry.get("skills") or {}
    if not isinstance(reg_skills, dict) or not reg_skills:
        fail("7-registry", "REGISTRY.yaml has no `skills:` mapping")
    else:
        for name, meta in reg_skills.items():
            meta = meta or {}
            path = meta.get("path")
            if not path:
                fail("7-registry", f"registry entry '{name}' has no `path`")
            elif not (COUNCIL / path).is_file():
                fail("7-registry", f"registry path for '{name}' does not exist: {path}")
            for ref in meta.get("references") or []:
                if not (COUNCIL / ref).is_file():
                    fail("7-registry", f"registry reference for '{name}' does not exist: {ref}")
            for src in meta.get("source") or []:
                if not (COUNCIL / "source" / "original-v3" / src).is_file():
                    warn("7-registry", f"archived source for '{name}' not found: {src}")
            if name not in names:
                fail("7-registry", f"registry lists '{name}' but no canonical skill folder exists")
        for name in names:
            if name not in reg_skills:
                fail("7-registry", f"canonical skill '{name}' is missing from REGISTRY.yaml")

    # 8/9/10/11. adapters
    for provider, root in ADAPTER_ROOTS.items():
        check_id = {"claude": "8-claude-adapter", "codex": "9-codex-adapter"}[provider]
        if not root.is_dir():
            fail(check_id, f"adapter root missing: {rel(root)}")
            continue
        for name, info in sorted(canonical.items()):
            adapter = root / name / "SKILL.md"
            if not adapter.is_file():
                fail(check_id, f"missing {provider} adapter: {rel(adapter)}")
                continue
            atext = read(adapter)
            afm, aerr = _yamlish.parse_frontmatter(atext)
            if aerr:
                fail(check_id, f"{rel(adapter)}: {aerr}")
                continue
            if afm.get("name") != name:
                fail(check_id, f"{rel(adapter)}: name '{afm.get('name')}' != '{name}'")
            if not afm.get("description"):
                fail(check_id, f"{rel(adapter)}: no description")

            # 10. thin adapters only
            size = len(atext.encode("utf-8"))
            if size > ADAPTER_MAX_BYTES:
                fail("10-thin-adapter", f"{rel(adapter)} is {size} bytes (max {ADAPTER_MAX_BYTES}); adapters must not embed context")
            for bundle in COMBINED_BUNDLES:
                if bundle in atext:
                    fail("10-thin-adapter", f"{rel(adapter)} references the archival bundle {bundle}")

            # 11. the pointer must resolve
            pointers = [
                c.strip()
                for c in atext.split("`")[1::2]
                if c.strip().endswith("SKILL.md")
            ]
            if not pointers:
                fail("11-paths", f"{rel(adapter)} contains no canonical SKILL.md pointer")
            for pointer in pointers:
                target = (adapter.parent / pointer).resolve()
                if not target.is_file():
                    fail("11-paths", f"{rel(adapter)} pointer does not resolve: {pointer}")
                elif target != (canonical[name]["folder"] / "SKILL.md").resolve():
                    fail("11-paths", f"{rel(adapter)} pointer resolves to the wrong skill: {pointer}")

        for extra in sorted(p for p in root.iterdir() if p.is_dir()):
            if extra.name not in canonical:
                warn(check_id, f"{rel(extra)} has no canonical counterpart")

    # 11c. always-loaded root files must not pull in the archival bundles
    for root_file in (REPO / "CLAUDE.md", REPO / "AGENTS.md"):
        if root_file.is_file():
            rtext = read(root_file)
            for bundle in COMBINED_BUNDLES:
                if bundle in rtext and "never" not in rtext.lower():
                    fail("11-context", f"{rel(root_file)} references {bundle} without forbidding it")
            size_kb = len(rtext.encode("utf-8")) / 1024
            if size_kb > 24:
                warn("11-context", f"{rel(root_file)} is {size_kb:.1f} KB; control-tower files should stay small")
        else:
            fail("11-context", f"missing root instruction file: {rel(root_file)}")

    # informational: has an expert context diverged from its archived original?
    for name, info in sorted(canonical.items()):
        meta = (reg_skills or {}).get(name) or {}
        sources = meta.get("source") or []
        refs = meta.get("references") or []
        if len(sources) == 1 and len(refs) == 1:
            archived = COUNCIL / "source" / "original-v3" / sources[0]
            copy = COUNCIL / refs[0]
            if archived.is_file() and copy.is_file():
                if read(archived) != read(copy):
                    notes.append(f"{name}: references/ copy differs from archived {sources[0]} (intentional edits are fine)")

    if verbose:
        print(f"canonical skills : {len(canonical)}")
        print(f"registry entries : {len(reg_skills)}")
        for provider, root in ADAPTER_ROOTS.items():
            count = len([p for p in root.iterdir() if p.is_dir()]) if root.is_dir() else 0
            print(f"{provider} adapters  : {count}")

    return report()


def report() -> int:
    for note in notes:
        print(f"NOTE  {note}")
    for message in warnings:
        print(f"WARN  {message}")
    for message in errors:
        print(f"FAIL  {message}")
    print()
    if errors:
        print(f"validate_skills: FAILED ({len(errors)} error(s), {len(warnings)} warning(s))")
        return 1
    print(f"validate_skills: PASS (0 errors, {len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(verbose="--verbose" in sys.argv or "-v" in sys.argv))
