---
name: cycloidal_drive
description: Engineering kinematics, formulas, and CadQuery modeling patterns for cycloidal speed reducers.
---

# Cycloidal Speed Reducer Mechanism Skill

Guidelines and mathematical formulas for modeling high-reduction, high-torque cycloidal drive mechanisms.

## 1. Kinematic Invariants & Parameter Formulas

For a desired reduction ratio $R$ (where input is high-speed eccentric shaft, output is constant-velocity pin carrier, and ring pin housing is stationary):

| Parameter | Formula / Guideline | Typical Range / Example |
|---|---|---|
| **Reduction Ratio ($R$)** | $R = \frac{N_{\text{lobes}}}{N_{\text{pins}} - N_{\text{lobes}}}$ | e.g. 10:1 reduction |
| **Number of Lobes ($N_{\text{lobes}}$)** | $N_{\text{lobes}} = R$ | 10 lobes for 10:1 ratio |
| **Number of Ring Pins ($N_{\text{pins}}$)** | $N_{\text{pins}} = N_{\text{lobes}} + 1$ | 11 stationary pins for 10:1 ratio |
| **Eccentricity ($e$)** | $e = 1.5\text{mm} - 3.0\text{mm}$ | e.g. 2.0mm offset on input shaft lobe |
| **Ring Pin PCD ($D_{\text{pin\_pcd}}$)** | Pitch circle diameter of housing ring pins | e.g. 100.0mm - 140.0mm |
| **Ring Pin Diameter ($d_{\text{pin}}$)** | Stationary pin roller diameter | 6.0mm - 10.0mm (e.g. 8.0mm) |
| **Carrier Drive Pin PCD ($D_{\text{carrier\_pcd}}$)** | Output pin pitch circle diameter | Must be identical on disc and carrier (e.g. 60.0mm) |
| **Carrier Drive Pin Diameter ($d_{\text{carrier\_pin}}$)** | Drive pin outer diameter | 5.0mm - 8.0mm (e.g. 6.0mm) |
| **Disc Carrier Hole Diameter ($D_{\text{disc\_hole}}$)** | $D_{\text{disc\_hole}} = d_{\text{carrier\_pin}} + (2 \cdot e) + \text{clearance}$ | Sized to allow orbital motion: $6.0 + 2(2.0) + 0.5 = 10.5\text{mm}$ |

---

## 2. Component Decomposition

A complete cycloidal drive consists of 4 core coaxial parts:

1. **Stationary Pin Housing (`geometry_form: "annular_flanged_casing"`)**:
   - Annular outer casing with external bolt flange for mounting.
   - Internal circular bore with $N_{\text{pins}}$ cylindrical pocket recesses or pressed roller pins distributed evenly on $D_{\text{pin\_pcd}}$.
2. **Input Eccentric Shaft (`geometry_form: "stepped_shaft"`)**:
   - Input motor coupling journal at one end.
   - Central eccentric cylinder offset radially by $e$ to drive the cycloid disc.
   - Counterbalance lobe 180° opposite to cancel orbital vibrations.
3. **Cycloid Disc (`geometry_form: "cycloid_disc"`)**:
   - Central bore matching eccentric bearing journal ($D = \text{bearing\_od}$).
   - Outer epicycloidal/hypocycloidal lobe profile with $N_{\text{lobes}}$ teeth.
   - Inner pattern of circular drive pin holes (diameter $D_{\text{disc\_hole}}$) distributed on $D_{\text{carrier\_pcd}}$.
4. **Output Pin Carrier (`geometry_form: "pin_carrier_flange"`)**:
   - Circular carrier flange with output shaft journal.
   - Extruded cylindrical drive pins ($d_{\text{carrier\_pin}}$) on $D_{\text{carrier\_pcd}}$ that engage the oversized disc holes to transmit pure rotation.

---

## 3. CadQuery Modeling Patterns

### A. Oversized Disc Carrier Holes
```python
# Sizing: disc hole must equal carrier pin diameter + 2 * eccentricity + running clearance
disc_carrier_hole_dia = carrier_pin_dia + (2.0 * eccentricity) + 0.5

disc = (
    cq.Workplane("XY")
    .circle(outer_disc_radius)
    .extrude(disc_thickness)
    .faces(">Z")
    .workplane(centerOption="CenterOfMass")
    # Central eccentric bearing bore
    .hole(bearing_bore_dia)
    # Circular array of oversized drive holes
    .faces(">Z")
    .workplane(centerOption="CenterOfMass")
    .polarArray(radius=carrier_pin_pcd / 2.0, startAngle=0, angle=360, count=num_carrier_pins)
    .hole(disc_carrier_hole_dia)
)
```

### B. Input Eccentric Shaft
```python
# Main shaft axis along global Z
shaft = cq.Workplane("XY").circle(journal_dia / 2.0).extrude(total_length)
# Eccentric lobe offset along X by eccentricity
eccentric_lobe = (
    cq.Workplane("XY")
    .transformed(offset=(eccentricity, 0, lobe_z_start))
    .circle(lobe_dia / 2.0)
    .extrude(lobe_width)
)
result = shaft.union(eccentric_lobe)
```
