---
name: dfm_cnc_machining
description: DFM rules and CadQuery 2.x modeling idioms for 3-axis CNC milling and drilling.
---

# DFM Skill: CNC Machining (Milling & Drilling)

Guidelines for generating 3-axis CNC machinable CadQuery geometry.

---

## 1. Core Manufacturing Constraints

| Parameter | Rule | Reason |
|---|---|---|
| **Internal Vertical Corner Fillets** | Radius $r \ge 1.5\text{mm}$ (or $\frac{1}{2}$ end-mill diameter) | Rotating round end-mills cannot cut sharp 90° internal vertical corners. |
| **Hole Aspect Ratio** | Depth / Diameter $L/D \le 5.0$ | Deep holes cause drill bit deflection, vibration, or tool breakage. |
| **Minimum Wall Thickness** | $t \ge 2.0\text{mm}$ | Thin aluminum/steel walls vibrate and deform under cutting tool forces. |
| **Pocket Depth-to-Width Ratio** | Depth / Width $\le 4.0$ | Deep narrow pockets require long, flexible end-mills prone to chatter. |
| **Undercuts & T-Slots** | Avoid internal undercuts inaccessible to 3-axis Z-down tools | Requires expensive 5-axis indexing or custom cutters. |

---

## 2. CadQuery CNC Modeling Patterns

### A. Pocketing with Internal Corner Fillets
When creating internal pockets, always add `.edges("|Z").fillet(2.0)` so a round end-mill tool can clear the corners:

```python
import cadquery as cq

# CNC Machined Block with Pocket and Filleted Internal Corners
result = (
    cq.Workplane("XY")
    .box(60, 40, 20)
    .faces(">Z").workplane()
    .rect(40, 20)
    .cutBlind(-12)  # Pocket depth
    .edges("|Z").fillet(2.5)  # Internal vertical corner fillet for 5mm end-mill tool clearance
)
```

### B. Standard CNC Drill Hole (Flat/V-Bottom)
Avoid non-standard hole sizes. Use ISO metric drill bit diameters (M3=3.3mm, M4=4.3mm, M5=5.3mm, M6=6.6mm):

```python
result = (
    cq.Workplane("XY")
    .box(50, 50, 15)
    .faces(">Z").workplane()
    .hole(4.3, depth=10.0)  # Standard M4 clearance drill
)
```

---

## 3. Verification Checklist for CNC Parts

- [ ] All internal vertical pocket corners have fillets ($r \ge 1.5\text{mm}$).
- [ ] No blind holes have depth $> 5 \times \text{diameter}$.
- [ ] Minimum wall thickness around pockets and holes is $\ge 2.0\text{mm}$.
- [ ] All features are accessible from top (+Z) or bottom (-Z) tool setup directions.
