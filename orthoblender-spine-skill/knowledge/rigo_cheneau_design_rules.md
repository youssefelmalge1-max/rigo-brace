# Rigo-Chêneau Design Rules (reference)

Clinical principles that drive the brace tools. **Reference only — not a prescription;**
the orthotist classifies the curve and validates every correction (see
clinical_safety_protocol.md). Sources: Rigo classification / Chêneau principles, Wood,
and the LeoSpinal workflow we model.

## Core principle: 3D correction by force couples
A Chêneau-type brace corrects in three planes simultaneously using **pressure +
expansion couples**:
- **Pressure** on convexities / prominences (pushes the body in).
- **Expansion (relief) rooms** in the concavities, opposite each pressure, giving the
  tissue and curve somewhere to move into. **A pressure without an opposing expansion is
  wrong** — it just compresses.
- Add **derotation** (transverse plane) and **elongation** (axial) on top of the coronal
  push/pull.

## Anatomy the tools key off (our LANDMARKS)
C7 · acromion L/R · inferior scapular angle L/R · axilla L/R · thoracic apex · lumbar
apex · iliac crest L/R · ASIS L/R · PSIS L/R · greater trochanter L/R · waistline.
These define pressure/expansion placement, circumference levels, and trimlines.

## Curve patterns (Rigo, simplified)
- **Thoracic (main right)**: right thoracic pressure (posterolateral → anteromedial,
  derotating), left thoracic expansion; left lumbar pressure with right lumbar expansion;
  pelvic stabilization. Axillary extension / trapezius support as indicated.
- **Thoracolumbar / lumbar**: lumbar pressure over the apex convexity with contralateral
  expansion; strong pelvic anchor.
- **Double major**: balanced thoracic + lumbar couples, opposite sides.
- Always include a stable **pelvic base** (anchor) so corrective forces have a reaction
  point; without it the brace just shifts on the body.

## Standard correction moves → our tools
- Coronal side-correction → **Bend** (deform_ops, axis Y).
- Transverse derotation → **Twist** (deform_ops) / multi-section **lattice rotate**
  (WASP port, planned).
- Axial elongation → **Stretch** (deform_ops, Z-only).
- Local pressure/relief → **pad shape library** (pressure=in, expansion=out) + Guided
  measurable push/pull (planned Stage 6).
- Breathing/relief volume → expansion rooms (blue pads) over concavities.

## Trimlines (comfort + function)
- Clear the axilla and arm-holes; avoid impingement at the neckline.
- Pelvic and abdominal trimlines per pattern; abdominal cutout optional.
- Flare/round all edges for skin safety (planned flare-% edge).

## Thickness / reinforcement
- Uniform printable wall as a base; **reinforce** pelvic anchor and major thoracic
  pressure zones; keep expansion rooms thinner. (Variable thickness via WASP weight port.)

## What the software must NOT decide
Curve classification, magnitude of correction, in-brace correction targets, wear schedule.
Those are clinical judgments — the tools only execute and measure what the orthotist sets.

## Rigo 2010 classification → brace design correlation (from the user's PDF)
Source: Rigo MD, Villagrasa M, Gallo D. "A specific scoliosis classification correlating
with brace treatment: description and reliability." Scoliosis 2010, 5:1 (Open Access;
PDF in the project root). Five radiological curve families, six brace-design categories:

| Type | Curve pattern (radiological) | Brace design (paper Fig. 1-4) |
|---|---|---|
| A1 | 3-curve; long thoracic rib hump going into the lumbar region; L4 horizontal/tilted to convex | 3C — **open pelvis on the CONVEX thoracic side** |
| A2 | 3-curve; single thoracic, no/minimal functional lumbar; L4 horizontal | 3C 'Classical' |
| A3 | 3-curve; major thoracic + minor lumbar; L4 tilted to concave side, negative L5-4 counter-tilt | 3C 'Classical' |
| B1 | 4-curve; double thoracic + lumbar/thoracolumbar; positive L5-4 counter-tilt | 4C 'Classical', **eventually pelvis open at the CONCAVE thoracic side** |
| B2 | 4-curve; major thoracolumbar + minor thoracic | 4C 'Classical' |
| C1 | balanced single thoracic, no lumbar (TP and T1 on CSL) | **Neutral pelvis** |
| C2 | false double (thoracic major + lumbar minor), negative L5-4 counter-tilt | **Neutral pelvis** |
| E1 | single lumbar | **Short lumbar brace** |
| E2 | single thoracolumbar | **Short thoracolumbar brace** |

Modifier: 'D' (upper structural / triple structural — upper rib hump in forward bending)
alters the upper brace design.

**Template calibration (2026-07-08):** the user's reference pairs both close the pelvis
full-circle (coverage 72/72 θ-bins) ⇒ "A type" = 3C Classical (A2+A3 family),
"B type" = 4C Classical (B2-like). Missing subtype references (to add when the user
provides them): A1 open-pelvis, B1 open-pelvis, C neutral-pelvis, E1/E2 short braces.
Clinical rule: classification comes from radiographs/clinical exam — the software only
offers the matching template; the orthotist chooses the type and refines the lines.
