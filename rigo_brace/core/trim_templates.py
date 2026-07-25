"""Rigo trim-line templates — extracted from the clinic's reference braces.

Each template is a JSON in ``rigo_brace/templates/`` holding the brace's outer
trim boundary as two angular profiles (top edge, bottom edge) in normalized
body coordinates:

- theta: 72 bins around the body axis, 0 = anterior, increasing toward the
  patient's left (+X in the front view);
- z normalized piecewise-linearly to three anatomical anchors:
  bottom (trochanter level) = -1 … waist (WAISTLINE) = 0 … top (shoulder) = +1.

Provenance: the A/B profiles were extracted 2026-07-08 from the user's own
reference pairs. The Rigo-Cheneau Reference is an independently authored compact
profile informed by clinical rules and internal visual comparison. Every profile carries
``requires_orthotist_review`` — the generated trim lines are a STARTING POINT
the orthotist refines, never a prescription. Subtype calibration will follow
the user's Rigo classification graphics.
"""

import json
import os

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

_CACHE = {}
_ENUM_CACHE = []


def _expand_knots(data):
    """Expand a compact, independently authored clinical profile to 72 bins."""
    knots = data.get("profile_knots") or []
    if len(knots) < 4:
        return None
    knots = sorted(knots, key=lambda knot: float(knot[0]))
    count = int(data.get("theta_bins", 72))
    top = []
    bottom = []
    for index in range(count):
        theta = -180.0 + (index + 0.5) * 360.0 / count
        first = knots[0]
        second = knots[-1]
        for lower, upper in zip(knots, knots[1:]):
            if float(lower[0]) <= theta <= float(upper[0]):
                first, second = lower, upper
                break
        span = float(second[0]) - float(first[0])
        fraction = 0.0 if abs(span) < 1.0e-9 else (theta - float(first[0])) / span
        # Smooth interpolation avoids visible corners while the explicit opening
        # joins remain VECTOR handles in trimline_ops.
        fraction = fraction * fraction * (3.0 - 2.0 * fraction)
        top.append(float(first[1]) + (float(second[1]) - float(first[1])) * fraction)
        bottom.append(float(first[2]) + (float(second[2]) - float(first[2])) * fraction)
    expanded = dict(data)
    expanded["schema"] = 1
    expanded["z_top_norm"] = top
    expanded["z_bot_norm"] = bottom
    expanded["covered"] = [True] * count
    return expanded


def template_path(type_id):
    return os.path.join(_TEMPLATE_DIR, f"trimline_{type_id}.json")


def load_template(type_id):
    """Load (and cache) one template; returns the dict or None."""
    if type_id in _CACHE:
        return _CACHE[type_id]
    try:
        with open(template_path(type_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("schema") == 2:
            data = _expand_knots(data)
        if data and data.get("schema") == 1 and data.get("z_top_norm"):
            _CACHE[type_id] = data
            return data
    except Exception:
        pass
    return None


def available_types():
    """Type ids that have a template file on disk."""
    out = []
    try:
        names = sorted(os.listdir(_TEMPLATE_DIR))
        names.sort(key=lambda name: (name != "trimline_RIGO_CHENEAU.json", name))
        for name in names:
            if name.startswith("trimline_") and name.endswith(".json"):
                out.append(name[len("trimline_"):-len(".json")])
    except Exception:
        pass
    return out


def type_enum_items(_self, _context):
    """Dynamic EnumProperty items (cached list — string-lifetime gotcha)."""
    if not _ENUM_CACHE:
        for tid in available_types():
            data = load_template(tid) or {}
            _ENUM_CACHE.append(
                (
                    tid,
                    data.get("display_name", f"Rigo Type {tid}"),
                    data.get("description", f"Trim-line template '{tid}'"),
                )
            )
        if not _ENUM_CACHE:
            _ENUM_CACHE.append(("NONE", "No templates found", ""))
    return _ENUM_CACHE
