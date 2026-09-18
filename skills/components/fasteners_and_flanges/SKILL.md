---
name: fasteners_and_flanges
description: Standard ISO metric fastener sizing, clearance hole standards (ISO 273), counterbores, bolt circle patterns (PCD), and flanged casing modeling patterns.
---

# Fasteners, Clearance Holes & Mounting Flanges Skill

Standard dimensional practices and CadQuery modeling conventions for bolted connections and flanged interfaces.

## 1. ISO Metric Clearance Hole Standards (ISO 273)

When drilling clearance holes for standard ISO metric fasteners:

| Fastener Thread Size | Fine Fit Hole ($D_{\text{fine}}$) | Medium Fit Hole ($D_{\text{med}}$ - Standard) | Coarse / Free Fit Hole ($D_{\text{coarse}}$) |
|---|---|---|---|
| **M2** | 2.2 mm | 2.4 mm | 2.6 mm |
| **M2.5** | 2.7 mm | 2.9 mm | 3.1 mm |
| **M3** | 3.2 mm | 3.4 mm | 3.6 mm |
| **M4** | 4.3 mm | 4.5 mm | 4.8 mm |
| **M5** | 5.3 mm | 5.5 mm | 5.8 mm |
| **M6** | 6.4 mm | 6.6 mm | 7.0 mm |
| **M8** | 8.4 mm | 9.0 mm | 10.0 mm |
| **M10** | 10.5 mm | 11.0 mm | 12.0 mm |

---

## 2. Counterbore & Socket Head Dimensions (DIN 912 / ISO 4762)

For recessed socket head cap screws (SHCS):

| Fastener Size | Head Diameter ($D_k$) | Head Height ($k$) | Recommended C'Bore Dia ($D_{cb}$) | Recommended C'Bore Depth ($H_{cb}$) |
|---|---|---|---|---|
| **M3** | 5.5 mm | 3.0 mm | 6.5 mm | 3.5 mm |
| **M4** | 7.0 mm | 4.0 mm | 8.0 mm | 4.5 mm |
| **M5** | 8.5 mm | 5.0 mm | 10.0 mm | 5.5 mm |
| **M6** | 10.0 mm | 6.0 mm | 11.5 mm | 6.5 mm |
| **M8** | 13.0 mm | 8.0 mm | 15.0 mm | 8.5 mm |

---

## 3. Circular Bolt Flange PCD Patterns

When placing mounting bolt holes on an annular casing flange:

```python
import cadquery as cq

flange_od = 140.0
flange_id = 90.0
flange_thickness = 10.0
pcd = 120.0
num_bolts = 6
hole_dia = 4.3  # M4 clearance hole

flange = (
    cq.Workplane("XY")
    .circle(flange_od / 2.0)
    .circle(flange_id / 2.0)
    .extrude(flange_thickness)
    .faces(">Z")
    .workplane(centerOption="CenterOfMass")
    .polarArray(radius=pcd / 2.0, startAngle=0, angle=360, count=num_bolts)
    .hole(hole_dia)
)
```
