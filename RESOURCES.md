# Brace Trimline Geometry Resources

## Knowledge

- [Blender Manual: Control Points](https://docs.blender.org/manual/en/3.2/modeling/curves/editing/control_points.html)
  Official explanation of Bezier handle behavior. Use for distinguishing automatic smooth tangents from Vector handles that intentionally create straight sections and corners.
- [Blender API: Shrinkwrap Modifier](https://docs.blender.org/api/blender_python_api_2_69_7/bpy.types.ShrinkwrapModifier.html)
  Official API description of nearest-surface projection and offset. Use for understanding why the editable curve follows the corrected body.
- [Blender Manual: Bevel Modifier](https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/bevel.html)
  Official reference for width, segments, profile, intersections, overlap clamping, and hardened normals. Use when designing the physical rim fillet.
- [Blender Manual: Shading](https://docs.blender.org/manual/vi/2.91/scene_layout/object/editing/shading.html)
  Explains that smooth shading interpolates normals but does not change geometry or a faceted silhouette.
- [Autodesk Fusion: Fillet Reference](https://help.autodesk.com/view/fusion360/ENU/?contextId=SLD-REF-FILLET)
  Official definition of constant versus variable radius and Tangent (G1) versus Curvature (G2) continuity. Use as the target vocabulary for “Fusion-style fillet.”

## Wisdom (Communities)

- [Blender Development Forum](https://devtalk.blender.org/)
  Use for implementation-level discussion of robust mesh topology, bevel behavior, and Blender API limitations.
- [Autodesk Fusion Design, Validate & Document Forum](https://forums.autodesk.com/t5/fusion-design-validate-document/bd-p/124)
  Use for comparing edge-fillet expectations and failure cases with experienced CAD users.

## Gaps

- The final fillet radius and continuity class must be chosen with the orthotist and fabrication process; software documentation cannot determine the prescription.
