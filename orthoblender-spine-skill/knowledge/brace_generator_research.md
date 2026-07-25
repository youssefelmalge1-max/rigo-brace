# Brace Generator and Trimline Redesign Research

Date: 2026-07-12
Status: first technical redesign implemented and tested; orthotist visual/clinical
validation and remaining manufacturing gates are pending.

## Executive finding

The current result cannot be repaired by increasing Smooth passes. It uses the wrong
geometric representation:

1. The scan is duplicated, offset and globally smoothed before clinical coverage is
   represented.
2. Top and bottom are separate cyclic curves rather than one physical perimeter.
3. Faces are kept/deleted from their center point. The cut can only follow existing
   triangle borders, producing stair steps and spikes.
4. When auto trim curves exist, `_trim_and_open()` returns before creating the designed
   opening.
5. Solidify closes the already-jagged edge; Corrective Smooth later moves a broad band
   but cannot reconstruct the intended curve or guarantee thickness.

The supplied A baseline confirms this is a structural failure, not styling:

| Metric | Current generated A | Clinic A reference |
|---|---:|---:|
| Vertices | 50,548 | 241,065 |
| Faces | 100,270 | 482,126 |
| Dimensions (mm) | 329.90 x 270.84 x 538.08 | 325.67 x 294.70 x 576.84 |
| Worst normalized triangle aspect | 21.79 | 11.53 |
| Surface RMS to reference | 14.098 mm | baseline |

The clinic `A type Brace.stl` is best treated as the clinic's corrected mold/reference
surface, not automatically assumed to be a final open shell. The diagnostic and render
are `tools/generatoraudit.py`, `generatoraudit_result.txt`, and `generatoraudit.png`.

## What LeoSpinal and Rodin4D establish publicly

LeoShape publicly describes LeoSpinal as a spinal-brace customizer with automatic spinal
curve adjustment/correction and manufacturing-ready output. Its wider workflow emphasizes
reference-point posture correction, preset pressure/relief points, reusable recipes and
real-time fit/pressure validation. It does not publish its algorithms; no exact parity can
be claimed. [LeoShape official product page](https://leopoly.com/leoshape/)

Rodin4D publicly describes importing scans, libraries of pre-rectified forms, professional
scan cleanup, change history, more than 25 rectification tools, drawing trim lines/forms
for machining, and shell thickening. It likewise does not expose implementation details.
[Rodin4D official product brochure](https://www.rodin4d.com/app/uploads/2021/05/Rodin4D-product-flipbook-EN.pdf)

These products support the workflow requirements; they are not source-code references.
Our implementation must be independently derived in Blender.

## Clinical model: why the design exists

A Rigo-System-Cheneau brace is a prescribed 3D force system, not a generic torso shell.
The local Rigo paper states that correction combines translation and three-point systems
in the frontal plane, force pairs for transverse derotation, and physiological sagittal
profile/alignment. Pressure/contact areas require specific shape, level and direction.
Brace design correlates with curve pattern; the paper documents a treatment failure from
using the wrong brace design and improvement after classification/design correction.
[Rigo et al. open-access article](https://pmc.ncbi.nlm.nih.gov/articles/PMC2825498/)

SOSORT states that every prescription must specify where to push, where to leave space,
and how trunk action should affect the spine; an experienced CPO must execute the agreed
prescription. Brace checks must verify fit and correction in frontal, sagittal and
horizontal planes, tolerability and movement, followed by clinical and/or radiographic
review. [2016 SOSORT guidelines](https://link.springer.com/article/10.1186/s13013-017-0145-8)

Therefore software may enforce completeness, geometry and traceability; it may not infer
or approve the treatment prescription from the skin scan alone.

## What landmarks can and cannot do

### Surface landmarks that are critical

- ASIS/PSIS and iliac crests: pelvic coordinate frame, anterior direction, pelvic
  containment/relief and lower trim safety.
- Trochanters: asymmetric inferior coverage and sitting/hip-clearance reference.
- Waistline: stable normalized height and shell registration.
- Axilla/acromion/C7/scapular angles: upper coverage and arm/neck clearance.
- Thoracic/lumbar surface apex marks: local correction placement aids only.

### Missing prescription data

Rigo classification uses clinical and radiographic criteria including curve family,
transitional point relative to the central sacral line, T1 balance, L4/L5 behavior and
the D modifier. Vertebral apex/end levels, convexity, flexibility, sagittal objectives
and intended force pairs cannot be recovered reliably from surface landmarks. They must
be orthotist-entered or derived from explicitly registered X-rays and then confirmed.

Landmark guardrails:

- Require units/orientation before placement.
- Require left/right pairs and anatomical height ordering.
- Store landmark source (`surface`, `xray`, `manual prescription`) and confidence.
- Never silently fall back to the scan bounding box for clinical generation. Estimation
  may create a preview only, visibly marked `NOT APPROVED`.

## Target geometry pipeline

1. **Validate input:** millimetres, upright axes, one clean scan, consistent normals,
   usable topology and complete prescription.
2. **Freeze corrected inner mold:** committed Bend/Twist/Stretch and pressure/expansion;
   retain a signed deviation map from the original scan.
3. **Create one perimeter:** a single editable, closed surface curve containing upper
   trim, opening side A, lower trim and opening side B. Joins use explicit fillets and
   tangent continuity. Do not maintain independent closed top/bottom rings.
4. **Insert the contour exactly:** split every crossed mesh edge at the continuous
   contour's zero crossing (marching-triangle/scalar clipping) or use a validated
   watertight cutter. Do not classify whole faces by their centers.
5. **Regularize locally:** remesh/densify the contour neighborhood to a controlled edge
   length; preserve the clinical surface outside a narrow finishing band.
6. **Build shell explicitly:** derive outer vertices from the inner surface with
   collision-aware offsets, then connect corresponding perimeter loops with a rim strip.
   This provides controlled topology and thickness instead of hoping Solidify repairs it.
7. **Round/flare the rim:** operate on the explicit rim curve/strip with measured fillet
   radius and flare, projected away from the inner surface. Preserve wall thickness.
8. **Validate and report:** only after all geometry gates pass can export be enabled.

The 2024 automated nighttime-brace study independently supports several geometry
principles: superior/inferior limits were manually fitted as splines on the patient STL;
the superior limit covered to the axilla on the thoracic-convex side, while the inferior
limit covered the ipsilateral trochanter and left the contralateral iliac crest free.
Its shape optimization used cylindrical surface patches, bounded radial pressure/relief
offsets, smoothing to remove topographic asperities, an explicit opening, constant 4 mm
HDPE, orthotist approval and final edge flaring/sanding. Its numeric clinical settings
are study-specific and must not become Rigo defaults.
[Automated brace study](https://www.nature.com/articles/s41598-024-53586-z)

## Guardrails and success criteria

### Blocking clinical gates

- Rigo subtype/side and D modifier explicitly confirmed.
- Pressure and expansion regions paired and approved.
- Pelvic behavior, sagittal objective, opening side and trim coverage approved.
- No clinical fallback values hidden from the orthotist.
- Final design receives orthotist review; software never labels it clinically correct.

### Blocking geometric gates

- Exactly one intended shell component.
- Watertight final manufacturing mesh; zero unintended boundary/non-manifold edges.
- No self-intersections, zero-area faces or inverted wall regions.
- One continuous perimeter definition before wall construction; no duplicate branches.
- All contour samples lie on the corrected inner surface within the chosen discretization
  tolerance (prototype target <= 0.5 mm).
- G1 tangent continuity at the four perimeter joins; no single-sample spikes. Prototype
  target: sampled turning angle <= 15 degrees at 2 mm spacing, to be visually calibrated.
- Controlled trim-band density (prototype target <= 2 mm edge length) and triangle aspect
  target <= 5 near the rim.
- Measured wall thickness within manufacturing tolerance everywhere. The exact tolerance,
  minimum radius and material limits must be validated for the clinic's process/printer.
- Pressure/relief signed-deviation maps survive generation within numeric tolerance.
- Opening width/side and anatomical coverage match the approved perimeter.

### Comparison gates

- Front/back/left/right/section overlays against clinic A and B references.
- Symmetric surface-distance report (RMS, 95th percentile and max), interpreted by region;
  a low whole-surface RMS alone cannot prove clinical correctness.
- Visual inspection at the axilla, iliac crest, trochanter, opening corners and all rims.
- Physical fit and clinical/radiographic validation remain outside automated Blender QA.

## Evidence limitations

- LeoSpinal/Rodin4D algorithms are proprietary; only observable/public workflows were
  analyzed and no code/assets were copied.
- The A/B clinic reference files are valuable ground truth but do not cover every Rigo
  subtype or D modifier.
- A surface scan does not contain sufficient information to prescribe internal spinal
  correction automatically.
- Published material/manufacturing numbers are not universal printer settings.

## Next implementation frontier

Run the user visual check on the A model and confirm the clinical prescription/reference
meaning. Thickness and self-intersection reports now block export; the next technical
gate is signed-deviation preservation, followed by B-fixture visual validation. The
technical perimeter/exact-cut prototype is integrated in `trimline_ops.py` and
`design_ops.py`; it is not clinical approval.
