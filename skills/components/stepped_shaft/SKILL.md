---
name: stepped_shaft
description: Design principles, bearing shoulder proportions, journal tolerances, and CadQuery modeling patterns for stepped transmission shafts.
---

# Stepped Transmission Shaft Skill

Engineering rules and parametric modeling conventions for rotating mechanical shafts with bearing journals, shoulders, and drive features.

## 1. Dimensional Proportions & Shoulder Ratios

To prevent stress concentrations and provide positive axial location for bearings, gears, and pulleys:

| Feature | Standard Proportion | Design Rationale |
|---|---|---|
| **Shoulder Height Ratio** | $$D_{\text{shoulder}} \ge 1.15 \times D_{\text{journal}}$$ | Ensures adequate bearing inner-ring abutment height |
| **Fillet Radius ($R_{\text{fillet}}$)** | $$R \approx 0.05 - 0.10 \times D_{\text{journal}}$$ | Relieves notch stress concentration without fouling bearing chamfer |
| **Bearing Chamfer Clearance** | $$R_{\text{fillet}} < r_{\text{bearing\_chamfer}}$$ | Prevents bearing from seating cocked or tilted against shoulder |
| **Journal Length / Diameter** | $$L / D \approx 0.8 - 1.5$$ | Standard commercial needle / deep groove ball bearing width |
| **Retaining Ring / Circlip Groove** | Width $\approx 1.1\text{mm} - 1.6\text{mm}$, depth $\approx 0.5\text{mm} - 1.0\text{mm}$ | Provides axial retention on free end |

---

## 2. Modeling Patterns (Axisymmetric Construction)

Shafts should be modeled axisymmetrically along the global Z axis:

```python
import cadquery as cq

d_bearing = 12.0
d_shoulder = 16.0
d_input = 10.0

l_input = 15.0
l_bearing = 10.0
l_center = 25.0

# Build stepped shaft via stacked cylinders along Z or revolving a 2D profile
shaft = (
    cq.Workplane("XY")
    .circle(d_input / 2.0).extrude(l_input)
    .faces(">Z").workplane()
    .circle(d_shoulder / 2.0).extrude(l_center)
    .faces(">Z").workplane()
    .circle(d_bearing / 2.0).extrude(l_bearing)
)

# Export mating interfaces for bearings and couplings
# INTERFACE: name=bearing_seat_1=(0,0,l_input) dir=(0,0,1) type=shaft d=12.0
# INTERFACE: name=input_coupling=(0,0,0) dir=(0,0,-1) type=shaft d=10.0
```
