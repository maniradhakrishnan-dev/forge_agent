---
name: fits_and_tolerances
description: Engineering fits, ISO metric fastener clearance hole standards, and manufacturing tolerance allowances.
---

# Mechanical Fits & Tolerances Skill

This skill provides standardized mechanical engineering fit tables and tolerance rules for 3D printing, CNC machining, and mechanical assemblies.

---

## 1. ISO Metric Fastener Clearance Holes (ISO 273 / ASME B18.2.8)

When drilling clearance holes for metric bolts and fasteners, use standard clearance diameters:

| Thread Size | Nominal Major Dia ($d$) | Close Fit ($d_h$) | Normal Fit ($d_h$) [Standard] | Loose Fit ($d_h$) |
|:---:|:---:|:---:|:---:|:---:|
| **M2** | 2.0 mm | 2.2 mm | 2.4 mm | 2.6 mm |
| **M2.5** | 2.5 mm | 2.7 mm | 2.9 mm | 3.1 mm |
| **M3** | 3.0 mm | 3.2 mm | **3.4 mm** | 3.6 mm |
| **M4** | 4.0 mm | 4.3 mm | **4.5 mm** (or 4.3mm min) | 4.8 mm |
| **M5** | 5.0 mm | 5.3 mm | **5.5 mm** | 5.8 mm |
| **M6** | 6.0 mm | 6.4 mm | **6.6 mm** | 7.0 mm |
| **M8** | 8.0 mm | 8.4 mm | **9.0 mm** | 10.0 mm |
| **M10** | 10.0 mm | 10.5 mm | **11.0 mm** | 12.0 mm |
| **M12** | 12.0 mm | 13.0 mm | **13.5 mm** | 14.5 mm |

---

## 2. Cylindrical Fit Types & Radial Clearances

For shaft-in-bore pairs, clearances depend on relative motion:

| Fit Class | Application | Diameter Allowance ($D_{\text{bore}} - d_{\text{shaft}}$) | Manufacturing Process |
|---|---|---|---|
| **Free Running Fit (H8/f7)** | High-speed rotation, pulleys, gears | $+0.15\text{ mm}$ to $+0.35\text{ mm}$ | 3D Printing / CNC |
| **Close Running Fit (H7/g6)** | Accurate location, low-speed pivots, linkages | $+0.05\text{ mm}$ to $+0.15\text{ mm}$ | CNC Machining |
| **Locational Clearance (H7/h6)** | Snug fit, easily assembled/disassembled by hand | $+0.02\text{ mm}$ to $+0.08\text{ mm}$ | CNC Machining |
| **3D Printing Clearance** | FDM filament shrinkage / layer expansion | $+0.20\text{ mm}$ to $+0.40\text{ mm}$ | 3D Printing |
| **Light Press Fit (H7/p6)** | Retained pins, bushings (no rotation) | $-0.01\text{ mm}$ to $-0.03\text{ mm}$ | CNC Machining |

---

## 3. General Rules for Assembly Models

1. **Clearance Fit Requirement:** In any rotating or sliding joint, the bore diameter MUST be strictly larger than the shaft diameter ($D_{\text{bore}} > d_{\text{shaft}}$).
2. **Clearance Limits:**
   - Standard mechanical fit clearance: $0.10\text{ mm} \le c \le 0.50\text{ mm}$.
   - Clearances $< 0.05\text{ mm}$ risk binding / interference.
   - Clearances $> 0.60\text{ mm}$ cause excessive backlash or slop.
