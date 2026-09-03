---
name: dfm_sheet_metal
description: DFM rules and CadQuery 2.x modeling idioms for Laser Cut and Bend sheet metal parts.
---

# DFM Skill: Sheet Metal (Laser Cutting & Bending)

Guidelines for generating manufacturable laser-cut and folded sheet metal CadQuery geometry.

---

## 1. Core Manufacturing Constraints

| Parameter | Rule | Reason |
|---|---|---|
| **Uniform Sheet Gauge** | Constant thickness $t$ throughout ($1.0\text{mm}$, $1.5\text{mm}$, $2.0\text{mm}$, $3.0\text{mm}$) | Sheet metal is cut from flat stock of uniform thickness. |
| **Minimum Bend Radius** | Internal bend radius $r_{\text{bend}} \ge 1.0 \times t$ | Tighter bends cause metal cracking or material stress tearing. |
| **Hole-to-Bend Distance** | Distance from hole edge to bend line $d \ge 2.0 \times t$ | Holes placed too close to a bend stretch and distort during folding. |
| **Minimum Laser Cut Hole Diameter** | Hole diameter $d_{\text{hole}} \ge 1.0 \times t$ | Laser beam heat distorts or burns holes smaller than sheet thickness. |
| **Corner Bend Relief** | Corner cutouts/notches at bend intersections | Prevents severe material bulging and tearing at folded flange corners. |

---

## 2. CadQuery Sheet Metal Modeling Patterns

### A. Flat Pattern & Flange Fold Pattern
In CadQuery, sheet metal brackets are modeled using uniform shell thickness and filleted bend radii:

```python
import cadquery as cq

thickness = 2.0  # 2mm Aluminum / Steel sheet
bend_radius = 2.0  # Internal bend radius r >= t

# L-Shaped Folded Sheet Metal Bracket
result = (
    cq.Workplane("XY")
    .box(50, 40, thickness)  # Base flange plate
    .faces(">Z").workplane()
    .pushPoints([(0, 0)])
    .hole(4.3)  # Laser-cut mounting hole (d >= t and distance from edge >= 2t)
)

# Vertical Flange addition with bent corner
flange = (
    cq.Workplane("YZ")
    .box(40, 30, thickness)
    .edges("|X").fillet(bend_radius)
)
```

### B. Hole Placement Rule Relative to Bends
Always place mounting holes at least $2 \times t + r_{\text{bend}}$ away from bend lines:

```python
# For 2mm sheet thickness and 2mm bend radius:
# Minimum hole edge distance from bend line = 2 * 2.0 + 2.0 = 6.0mm
hole_offset_from_bend = 10.0  # Safe clearance
```

---

## 3. Verification Checklist for Sheet Metal Parts

- [ ] All walls and flanges have identical, uniform sheet thickness $t$.
- [ ] Internal bend radii satisfy $r_{\text{bend}} \ge t$.
- [ ] All laser-cut hole diameters satisfy $d_{\text{hole}} \ge t$.
- [ ] Distance from hole edge to nearest bend line is $\ge 2t$.
- [ ] Flange corners have bend relief notches.
