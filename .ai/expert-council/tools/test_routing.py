#!/usr/bin/env python3
"""Deterministic routing fixture for the Expert Council.

This does NOT replace semantic LLM routing — an agent still classifies the real
root problem. It asserts the machine-checkable parts:

  * registry integrity (every routed skill exists, no dangling names)
  * expected domain mappings (each expert owns the domains it claims)
  * obvious trigger -> expert mappings
  * required expert combinations (pressure/expansion council, P0/P1 reliability)
  * the six worked scenarios from ROUTING.md

Usage:  python .ai/expert-council/tools/test_routing.py [--verbose]
Exit code 0 = pass, 1 = failures.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _yamlish  # noqa: E402

TOOLS = Path(__file__).resolve().parent
COUNCIL = TOOLS.parent
REGISTRY = COUNCIL / "REGISTRY.yaml"
ROUTING_DOC = COUNCIL / "ROUTING.md"

failures: list[str] = []
checks = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(f"{label}{(' — ' + detail) if detail else ''}")


# --------------------------------------------------------------------------
# Expected mappings. These are the contract; edit them deliberately.
# --------------------------------------------------------------------------

EXPECTED_DOMAINS = {
    "expert-ryan-schmidt": ["interactive_geometry", "mesh_editing", "remeshing", "geometry_kernels"],
    "expert-howard-trickey": ["boolean", "coplanar_overlap", "solid_topology"],
    "expert-jacques-lucke": ["procedural_architecture", "dependency_graph", "template_vs_instance", "caching_invalidation"],
    "expert-keenan-crane": ["geodesic", "intrinsic_geometry", "tangent_frames", "parallel_transport", "curvature", "laplacian"],
    "expert-alec-jacobson": ["self_intersection", "inside_outside", "winding_number", "mesh_validation"],
    "expert-campbell-barton": ["bpy", "bmesh", "context", "depsgraph", "undo", "registration_lifecycle"],
    "expert-mark-pauly": ["optimization", "manufacturability", "fabrication_constraints"],
    "expert-carl-eric-aubin": ["biomechanics", "fem", "predicted_pressure"],
    "expert-manuel-rigo": ["rigo_cheneau", "pressure_areas", "expansion_areas", "sagittal", "curve_pattern"],
    "expert-jonathan-shewchuk": ["geometric_predicates", "degeneracy", "epsilon_misuse", "mesh_quality", "scale_dependence"],
    "expert-olga-sorkine-hornung": ["deformation", "arap", "handles", "smooth_transitions", "deformation_energy"],
    "expert-bruno-levy": ["parameterization", "lscm", "local_2d_charts", "distortion"],
    "expert-mario-botsch": ["halfedge", "adjacency", "decimation", "remeshing_quality", "mesh_health"],
    "expert-sybren-stuvel": ["addon_architecture", "module_boundaries", "registration_reload", "exception_paths"],
    "geometry-reliability": ["regression_testing", "benchmark_corpus", "determinism", "p50_p95", "release_gates"],
    "pressure-expansion-system": ["pressure_region", "expansion_region", "correction_template", "correction_instance", "surface_attachment"],
    "repo-audit": ["repository_audit", "architecture_map", "source_of_truth"],
    "implementation-gate": ["implementation_protocol", "minimal_patch", "regression_test"],
}

EXPECTED_TRIGGERS = {
    "boolean": "expert-howard-trickey",
    "coplanar_overlap": "expert-howard-trickey",
    "geodesic": "expert-keenan-crane",
    "parallel_transport": "expert-keenan-crane",
    "arap": "expert-olga-sorkine-hornung",
    "ring": "expert-olga-sorkine-hornung",
    "epsilon": "expert-jonathan-shewchuk",
    "degenerate": "expert-jonathan-shewchuk",
    "self_intersection": "expert-alec-jacobson",
    "bmesh": "expert-campbell-barton",
    "undo": "expert-campbell-barton",
    "depsgraph": "expert-campbell-barton",
    "halfedge": "expert-mario-botsch",
    "lscm": "expert-bruno-levy",
    "correction_stack": "expert-jacques-lucke",
    "evaluator": "expert-jacques-lucke",
    "rigo": "expert-manuel-rigo",
    "sagittal": "expert-manuel-rigo",
    "fem": "expert-carl-eric-aubin",
    "predicted_pressure": "expert-carl-eric-aubin",
    "fabrication": "expert-mark-pauly",
    "reload": "expert-sybren-stuvel",
    "p95": "geometry-reliability",
    "correction_template": "pressure-expansion-system",
    "reusable_region": "pressure-expansion-system",
}

PRESSURE_EXPANSION_REQUIRED = {
    "expert-jacques-lucke",
    "expert-ryan-schmidt",
    "expert-keenan-crane",
    "expert-olga-sorkine-hornung",
    "expert-manuel-rigo",
    "geometry-reliability",
}

EXPECTED_VETOES = {
    "clinical": "expert-manuel-rigo",
    "biomechanical_claim": "expert-carl-eric-aubin",
    "numerical_topology": "expert-jonathan-shewchuk",
    "blender_state": "expert-campbell-barton",
}

# The six scenarios from ROUTING.md, as (scenario id -> everyone who must be routed).
EXPECTED_SCENARIOS = {
    "ring-after-move": {
        "primary": "expert-olga-sorkine-hornung",
        "must_include": {"expert-keenan-crane", "expert-ryan-schmidt", "expert-manuel-rigo", "geometry-reliability"},
    },
    "correction-misplaced-after-remesh": {
        "primary": "expert-ryan-schmidt",
        "must_include": {"expert-mario-botsch", "expert-keenan-crane", "expert-jacques-lucke", "geometry-reliability"},
    },
    "boolean-shards-some-scans": {
        "primary": "expert-howard-trickey",
        "must_include": {"expert-alec-jacobson", "expert-jonathan-shewchuk", "expert-ryan-schmidt", "geometry-reliability"},
    },
    "modal-tool-selection-dependent": {
        "primary": "expert-campbell-barton",
        "must_include": {"expert-sybren-stuvel", "expert-ryan-schmidt"},
    },
    "reusable-oval-templates": {
        "primary": "pressure-expansion-system",
        "must_include": {
            "expert-jacques-lucke",
            "expert-ryan-schmidt",
            "expert-keenan-crane",
            "expert-olga-sorkine-hornung",
            "expert-bruno-levy",
            "expert-manuel-rigo",
            "geometry-reliability",
        },
    },
    "increase-pressure-20-to-25": {
        "primary": "expert-manuel-rigo",
        "must_include": {"expert-carl-eric-aubin"},
    },
}


def scenario_members(scenario: dict) -> set[str]:
    members = set()
    for key in ("secondary", "clinical", "verification"):
        value = scenario.get(key) or []
        if isinstance(value, str):
            value = [value]
        members.update(value)
    return members


def main(verbose: bool = False) -> int:
    if not REGISTRY.is_file():
        print(f"FAIL  missing {REGISTRY}")
        return 1
    registry = _yamlish.load(REGISTRY.read_text(encoding="utf-8")) or {}
    skills = registry.get("skills") or {}
    routing = registry.get("routing") or {}
    scenarios = {s.get("id"): s for s in (registry.get("scenarios") or [])}

    # --- registry integrity -------------------------------------------------
    check(bool(skills), "registry has skills")
    check(bool(routing), "registry has routing")
    check(len(scenarios) >= 6, "registry has at least six scenarios", f"found {len(scenarios)}")

    for topic, rule in routing.items():
        rule = rule or {}
        for key in ("primary", "secondary", "required"):
            value = rule.get(key)
            if value is None:
                continue
            for skill in [value] if isinstance(value, str) else value:
                check(skill in skills, f"routing.{topic}.{key} -> known skill", skill)
        check(bool(rule.get("triggers")), f"routing.{topic} has triggers")

    # --- domain mappings ----------------------------------------------------
    for name, expected in EXPECTED_DOMAINS.items():
        meta = skills.get(name) or {}
        domains = set(meta.get("domain") or [])
        check(bool(meta), f"skill '{name}' exists in registry")
        for domain in expected:
            check(domain in domains, f"{name} owns domain '{domain}'")

    # --- trigger mappings ---------------------------------------------------
    trigger_index: dict[str, set[str]] = {}
    for topic, rule in routing.items():
        rule = rule or {}
        for trigger in rule.get("triggers") or []:
            trigger_index.setdefault(trigger, set()).add(rule.get("primary"))
    for trigger, expected_primary in EXPECTED_TRIGGERS.items():
        owners = trigger_index.get(trigger, set())
        check(expected_primary in owners, f"trigger '{trigger}' routes to {expected_primary}", f"got {sorted(owners) or 'nothing'}")

    # --- required combinations ---------------------------------------------
    pe = skills.get("pressure-expansion-system") or {}
    default_council = set(pe.get("default_council") or [])
    check(
        PRESSURE_EXPANSION_REQUIRED <= default_council,
        "pressure-expansion default council is complete",
        f"missing {sorted(PRESSURE_EXPANSION_REQUIRED - default_council)}",
    )
    conditional = pe.get("conditional_council") or {}
    for key in ("local_2d_parameterization", "topology_change_or_local_remesh", "blender_modal_or_undo", "biomechanical_claim", "boolean"):
        check(key in conditional, f"pressure-expansion conditional council covers '{key}'")

    pe_routing = routing.get("pressure_expansion_library") or {}
    required = set(pe_routing.get("required") or [])
    check(
        PRESSURE_EXPANSION_REQUIRED <= required,
        "routing.pressure_expansion_library requires the full council",
        f"missing {sorted(PRESSURE_EXPANSION_REQUIRED - required)}",
    )

    reliability = skills.get("geometry-reliability") or {}
    auto = set(reliability.get("auto_activate_for") or [])
    check({"P0", "P1"} <= auto, "geometry-reliability auto-activates for P0/P1", f"got {sorted(auto)}")

    vetoes = ((registry.get("decision_policy") or {}).get("vetoes")) or {}
    for kind, owner in EXPECTED_VETOES.items():
        check(vetoes.get(kind) == owner, f"veto '{kind}' held by {owner}", f"got {vetoes.get(kind)}")
        meta = skills.get(owner) or {}
        check(meta.get("veto") == kind or kind == "clinical" and meta.get("veto") == "clinical",
              f"skill '{owner}' declares veto '{kind}'", f"got {meta.get('veto')}")

    # --- worked scenarios ---------------------------------------------------
    for scenario_id, expectation in EXPECTED_SCENARIOS.items():
        scenario = scenarios.get(scenario_id)
        check(scenario is not None, f"scenario '{scenario_id}' exists in registry")
        if not scenario:
            continue
        check(
            scenario.get("primary") == expectation["primary"],
            f"scenario '{scenario_id}' primary is {expectation['primary']}",
            f"got {scenario.get('primary')}",
        )
        members = scenario_members(scenario)
        missing = expectation["must_include"] - members
        check(not missing, f"scenario '{scenario_id}' routes the full set", f"missing {sorted(missing)}")
        for skill in members | {scenario.get("primary")}:
            check(skill in skills, f"scenario '{scenario_id}' names a known skill", skill)
        check(bool(scenario.get("input")), f"scenario '{scenario_id}' records its input phrasing")

    # --- documentation agreement -------------------------------------------
    if ROUTING_DOC.is_file():
        doc = ROUTING_DOC.read_text(encoding="utf-8")
        for scenario_id, scenario in scenarios.items():
            phrase = (scenario.get("input") or "").rstrip(".")
            check(phrase in doc, f"ROUTING.md documents scenario '{scenario_id}'")
    else:
        check(False, "ROUTING.md exists")

    # --- report -------------------------------------------------------------
    for message in failures:
        print(f"FAIL  {message}")
    print()
    if failures:
        print(f"test_routing: FAILED ({len(failures)} of {checks} checks)")
        return 1
    print(f"test_routing: PASS ({checks} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main(verbose="--verbose" in sys.argv or "-v" in sys.argv))
