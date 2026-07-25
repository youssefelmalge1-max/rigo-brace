# Clinical Safety Protocol

**The add-on guides design; the orthotist makes the clinical decision.** Nothing produced
here is an automatic prescription. Every correction template and generated brace must be
reviewed and approved by a qualified orthotist before fabrication or fitting.

## Non-negotiable rules
1. Every clinical template carries `status: requires_orthotist_review` until a human
   orthotist signs off for a specific patient.
2. The software must never claim a design is "clinically correct" or "safe to wear."
3. Corrections are bounded: expose ranges via sliders with sane min/max; warn on extreme
   values (e.g. bend/derotation beyond typical clinical range).
4. Pressure must not be applied over contraindicated structures (see below) without
   explicit orthotist intent.

## Contraindications / caution zones (flag, never auto-apply pressure)
- Bony prominences without padding: spinous processes, scapular spine, iliac crest edge,
  ASIS, ribs at risk of excessive compression.
- Soft/vulnerable: breast tissue, axillary neurovascular bundle, abdomen over viscera,
  areas of compromised skin integrity.
- Respiratory: never restrict thoracic expansion needed for breathing — pair every
  thoracic pressure with an opposing expansion (relief) room.

## Per-design safety checklist (gate before export)
- [ ] Orthotist has reviewed pressure zones, expansion rooms, and trimlines.
- [ ] Each pressure has a matching expansion room (3D corrective couple), not isolated.
- [ ] Pelvic anchor stable; no excessive point pressure on ASIS/iliac crest.
- [ ] Axilla, arm-holes and neckline trimlines clear of impingement; edges flared/smoothed.
- [ ] Breathing not over-restricted (anterior thoracic expansion present).
- [ ] Minimum wall thickness met everywhere (see manufacturing_constraints.md).
- [ ] No sharp edges; trim edges flared for comfort.
- [ ] Mesh is manifold, watertight, correct units (mm), correct orientation.
- [ ] Design compared against the original scan (deviation within intended correction).
- [ ] Patient-specific notes recorded; version saved in the design history.

## Data / privacy
Patient scans and X-rays are sensitive. Keep them local; do not upload to external
services without consent. The pad-shape library is non-patient geometry (safe to share).

## Escalation
If a requested correction looks clinically unsafe (e.g. crushing pressure, breathing
restriction, pressure on a contraindicated structure), surface the concern to the
orthotist rather than silently applying it.
