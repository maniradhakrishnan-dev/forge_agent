---
name: planetary_gearbox
description: Kinematic formulas, gear teeth invariants, module sizing, and CadQuery modeling patterns for epicyclic planetary gearboxes.
---

# Planetary Gearbox Mechanism Skill

Engineering guidelines and mathematical invariants for epicyclic planetary gear systems.

## 1. Kinematic Invariants & Teeth Sizing

In standard epicyclic gearing with stationary internal ring gear, central sun gear input, and planet carrier output:

| Parameter | Mathematical Formula | Notes |
|---|---|---|
| **Teeth Invariant (Fundamental)** | $$Z_{\text{ring}} = Z_{\text{sun}} + 2 \cdot Z_{\text{planet}}$$ | Must hold strictly for concentric assembly |
| **Planetary Assembly Condition** | $$\frac{Z_{\text{sun}} + Z_{\text{ring}}}{N_{\text{planets}}} = \text{integer}$$ | Allows equally spaced symmetrical planet gears |
| **Gear Ratio ($R$)** | $$R = 1 + \frac{Z_{\text{ring}}}{Z_{\text{sun}}}$$ | Output speed reduction ratio |
| **Gear Module ($m$)** | $$m = 1.0\text{mm} - 3.0\text{mm}$$ | Shared across Sun, Planet, and Ring |
| **Pitch Diameters ($D_p$)** | $$D_{p} = m \cdot Z$$ | $D_{\text{sun}} = m \cdot Z_{\text{sun}}$, etc. |
| **Center Distance ($C$)** | $$C = \frac{m \cdot (Z_{\text{sun}} + Z_{\text{planet}})}{2}$$ | Radius of planet pin pitch circle on carrier |
| **Number of Planets ($N_{\text{planets}}$)** | 3 (standard) or 4 (high torque) | Distributed symmetrically at $\frac{360^\circ}{N}$ |

---

## 2. Component Decomposition

A planetary gearbox decomposes into 4 core coaxial parts:

1. **Stationary Ring Gear (`geometry_form: "annular_flanged_casing"` or `"internal_ring_gear"`)**:
   - Outer cylindrical housing with circular mounting flange.
   - Internal gear bore with pitch diameter $D_{\text{ring}} = m \cdot Z_{\text{ring}}$.
2. **Central Sun Gear (`geometry_form: "spur_gear"`)**:
   - Input shaft or motor bore.
   - External gear teeth with pitch diameter $D_{\text{sun}} = m \cdot Z_{\text{sun}}$.
3. **Planet Gears ($N_{\text{planets}}$ identical gears) (`geometry_form: "spur_gear"`)**:
   - External teeth with pitch diameter $D_{\text{planet}} = m \cdot Z_{\text{planet}}$.
   - Central needle/journal bearing bore to rotate freely on carrier pins.
4. **Planet Carrier (`geometry_form: "pin_carrier_flange"`)**:
   - Rigid carrier flange with integral output shaft journal.
   - $N_{\text{planets}}$ precision ground cylindrical pins located at radius $R = C$ (center distance).

---

## 3. CadQuery Modeling Patterns

```python
# Sun and Planet gears modeled with pitch circle reference
pitch_radius_sun = (module * num_teeth_sun) / 2.0
pitch_radius_planet = (module * num_teeth_planet) / 2.0
center_distance = pitch_radius_sun + pitch_radius_planet

# Carrier flange with pins placed at exact center_distance
carrier = (
    cq.Workplane("XY")
    .circle(flange_radius)
    .extrude(flange_thickness)
    .faces(">Z")
    .workplane(centerOption="CenterOfMass")
    .polarArray(radius=center_distance, startAngle=0, angle=360, count=num_planets)
    .circle(planet_pin_dia / 2.0)
    .extrude(planet_face_width)
)
```
