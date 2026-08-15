"""Single source of truth for #48 quality-gate thresholds.

Parses the fenced ```json block out of
orthoblender-spine-skill/knowledge/region_quality_contract.md so the written
contract and the executable gates can never diverge (hardening Wave 0,
DEC-0042).  bpy-free: importable from GUI test scripts and from plain Python
(tools/contractcheck.py).
"""

import json
import os
import re

_MD = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "orthoblender-spine-skill", "knowledge",
    "region_quality_contract.md",
)

REQUIRED = {
    "validity": ("selfx", "inverted", "degenerate", "holes",
                 "nonmanifold_delta", "count_change"),
    "smooth": ("osc_floor_mm", "osc_profile_coeff", "osc_cap"),
    "amount": ("core_lo", "core_hi"),
    "feather": ("outside_max_mm", "rev_tol_mm", "decile_rev_tol_mm"),
    "parity": ("osc_factor", "osc_slack_mm", "spike_slack", "iou_min",
               "rms_max_mm", "core_maxdd_mm", "rim_shift_edges"),
    "resolution": ("core_med_min_frac",),
    "perf": ("import_commit_max_s",),
    "wall": ("clearance_mm", "cross_sheet_new"),
    "fold": ("dot", "pre_dot", "new_folds", "oracle_post_deg",
             "oracle_pre_deg"),
    "size": ("surface_tolerance_frac",),
    "quality": ("enforced", "wall_sampling_margin", "wall_sampling_violations",
                "aspect_p95_factor", "min_rows_across_feather",
                "growth_max_faces_factor", "smooth_new_spikes"),
}


def load(path=_MD):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if match is None:
        raise ValueError(f"no fenced json threshold block in {path}")
    thresholds = json.loads(match.group(1))
    missing = [
        f"{section}.{key}"
        for section, keys in REQUIRED.items()
        for key in keys
        if key not in thresholds.get(section, {})
    ]
    if missing:
        raise ValueError(f"contract block incomplete, missing: {missing}")
    return thresholds
