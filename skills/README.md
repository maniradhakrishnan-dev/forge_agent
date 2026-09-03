# /skills — Markdown-as-Code Agent Skills

This directory contains modular Markdown-as-Code skill files (`SKILL.md`) injected into ForgeAgent agents to provide domain-specific knowledge and syntax idioms.

## Skills Directory Layout

- `cadquery_modeling/SKILL.md`: Best-practice CadQuery 2.x API patterns (`cq.Workplane`, workplanes, hole creation, fillets, assembly mates).
- `dfm_3d_printing/SKILL.md`: DFM constraints for 3D printing (FDM/SLA minimum wall thickness, hole tolerances, overhang angles).
- `dfm_cnc_machining/SKILL.md`: DFM constraints for 3-axis CNC milling & drilling (internal corner fillets, hole aspect ratios, pocket depth limits).
- `dfm_sheet_metal/SKILL.md`: DFM constraints for laser-cut and folded sheet metal (uniform sheet gauge, minimum bend radius, hole-to-bend distance).
- `fits_and_tolerances/SKILL.md`: ISO clearance fit tables (shaft vs bore tolerances, bolt hole clearance diameters).
- `kinematic_joints/SKILL.md`: Guidelines for defining revolute, slider, and planar assembly joints in CadQuery.
