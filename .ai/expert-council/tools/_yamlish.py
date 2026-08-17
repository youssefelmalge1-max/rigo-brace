"""Tiny YAML-subset loader.

The council tooling must run anywhere (a plain CPython, a Codex sandbox, a
Blender bundled interpreter) without third-party packages. PyYAML is used when
it is importable; otherwise this fallback parses the restricted subset used by
REGISTRY.yaml: nested block mappings, block lists, inline flow lists, comments,
and plain scalars.

Deliberate limitations: no anchors, no multi-line scalars, no flow mappings, no
values containing ": ".
"""

from __future__ import annotations


def load(text: str):
    try:  # pragma: no cover - exercised only where PyYAML exists
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        return loads_fallback(text)


def loads_fallback(text: str):
    lines = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))
    if not lines:
        return {}
    value, _ = _parse(lines, 0, lines[0][0])
    return value


def _scalar(token: str):
    token = token.strip()
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part) for part in inner.split(",")]
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    if token in ("true", "True"):
        return True
    if token in ("false", "False"):
        return False
    if token in ("null", "~", ""):
        return None
    return token


def _parse(lines, i, indent):
    if lines[i][1].startswith("- "):
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_list(lines, i, indent):
    items = []
    while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
        content = lines[i][1][2:].strip()
        j = i + 1
        sub = [(indent + 2, content)]
        while j < len(lines) and lines[j][0] > indent:
            sub.append(lines[j])
            j += 1
        is_mapping = (":" in content) and not content.startswith("[")
        if is_mapping:
            value, _ = _parse(sub, 0, indent + 2)
        else:
            value = _scalar(content)
        items.append(value)
        i = j
    return items, i


def _parse_map(lines, i, indent):
    out = {}
    while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith("- "):
        key, _, rest = lines[i][1].partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            out[key] = _scalar(rest)
            i += 1
            continue
        j = i + 1
        if j < len(lines) and lines[j][0] > indent:
            child_indent = lines[j][0]
            sub = []
            while j < len(lines) and lines[j][0] >= child_indent:
                sub.append(lines[j])
                j += 1
            out[key], _ = _parse(sub, 0, child_indent)
            i = j
        else:
            out[key] = None
            i += 1
    return out, i


def parse_frontmatter(text: str):
    """Return (frontmatter_dict, error_message). Dict is empty on failure."""
    if not text.startswith("---"):
        return {}, "file does not start with YAML frontmatter ('---')"
    end = text.find("\n---", 3)
    if end == -1:
        return {}, "frontmatter is not terminated by a closing '---'"
    block = text[text.find("\n", 3) + 1 : end]
    data = {}
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith(" ") or raw.startswith("\t"):
            continue  # nested frontmatter keys are not used by this system
        key, sep, value = raw.partition(":")
        if not sep:
            return {}, "frontmatter line without a key: %r" % raw
        data[key.strip()] = _scalar(value)
    return data, ""
