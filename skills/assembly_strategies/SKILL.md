---
name: assembly_strategies
description: Deterministic assembly rules for base part selection, port mating, coaxial mechanism alignment, shaft/bore insertion, and fastener snapping.
---

# Assembly Strategies & Mating Rules

This skill provides deterministic assembly procedures to position and mate verified CAD components into a single multi-part assembly.

---

## 1. Base Part Selection Strategy

The base (grounded) component serves as the coordinate frame anchor $(0, 0, 0)$.

1. **Explicit Ground / Rigid Anchor:**
   - Any part with `part_type` in `["base", "frame", "housing", "casing", "chassis", "stator"]` or `geometry_form` in `["housing", "casing", "box_enclosure", "base_plate"]`.
   - Any part associated with a `rigid` or `ground` joint to the world frame.
2. **Maximum Constraint Degree:**
   - If no designated base exists, select the component with the highest number of defined `mates` (topological center).
3. **Fallback:**
   - The first component declared in the `AssemblyGraph.parts` sequence.

---

## 2. Port Matching & Mating Key Contract

Ports connect parts deterministically via typed contracts:

1. **Direct `mate_port_id` Lookup:**
   - If `MatingContext.mate_port_id` is declared, look for an exact port name or `mate_key` matching that ID on the partner.
2. **Complementary Feature Pairing:**
   - Shaft/Pin/Bolt features (`shaft`, `pin`, `bolt`, `fastener`) mate with Bore/Hole features (`hole`, `bore`).
   - Planar features (`face`) mate with planar features.
   - Compliant features (`compliant_fit`, `snap_fit`) mate with corresponding compliant features.
3. **Diameter Compatibility:**
   - Diameters must match within tolerance ($|\Delta d| \le \text{clearance} + 0.5\text{ mm}$).
   - Direct matching against declared `MatingContext.my_feature_diameter`.

---

## 3. Coaxial & Nested Mechanism Strategy

1. **Shaft into Bore Insertion (`hole_shaft`, `shaft_hole`):**
   - The cylindrical axis of the shaft aligns with the cylindrical axis of the bore.
   - Translation along X and Y snaps the shaft center to the bore center: $\Delta x = x_{\text{bore}} - x_{\text{shaft}}$, $\Delta y = y_{\text{bore}} - y_{\text{shaft}}$.
   - Translation along Z aligns the shaft mating face (tip or shoulder) to the bore reference face.
   - Shaft into bore is an intended **nested mating** — coaxial stacking collision rules do NOT apply to nested features.

2. **Coaxial Rotation Axis Alignment:**
   - If both components are specified as coaxial (`revolute` joint or `concentric` mate with zero center distance), their rotational axes coincide on $(0, 0)$.
   - For offset holes or multi-spindle assemblies, preserve the explicit port offset $(x, y)$.

3. **Tooth and Gear Meshing:**
   - Center distance $a = r_1 + r_2$ or explicit `center_distance` in kinematic parameters.
   - Clocking angle sweep (0° to 360°) to find minimum Boolean interference at tooth engagement.
