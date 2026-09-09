---
name: kinematic_joints
description: Guidelines and mathematical definitions for kinematic joints, degrees of freedom, and collision-free swept volume verification in mechanical assemblies.
---

# Kinematic Joints & Motion Verification Skill

This skill defines the kinematic joint taxonomy and motion constraints used by ForgeAgent to model multi-body mechanical assemblies.

---

## 1. Joint Types & Degrees of Freedom (DoF)

| Joint Type | Degrees of Freedom | Relative Motion | Required Vector Parameters |
|---|---|---|---|
| **`rigid`** | 0 DoF | Fixed connection (bolted, glued, welded) | None (fixed relative pose) |
| **`revolute`** | 1 DoF (Rotational) | Rotation about a specified axis | `axis`: $[n_x, n_y, n_z]$ unit vector |
| **`prismatic`** | 1 DoF (Translational) | Sliding along a linear axis | `axis`: $[v_x, v_y, v_z]$ direction vector |
| **`cylindrical`**| 2 DoF (Rot + Trans) | Coaxial rotation and linear sliding | `axis`: $[n_x, n_y, n_z]$ axis of cylinder |
| **`planar`** | 3 DoF (2 Trans + 1 Rot) | Sliding on a plane and in-plane rotation | `normal`: $[n_x, n_y, n_z]$ plane normal |

---

## 2. Defining Joints in AssemblyGraph

Joints connect two parts (`part_a` and `part_b`) with an explicit axis of relative motion:

```json
{
  "id": "j_crank_pivot",
  "type": "revolute",
  "part_a": "frame",
  "part_b": "crank",
  "axis": [0.0, 0.0, 1.0]
}
```

```json
{
  "id": "j_slider_track",
  "type": "prismatic",
  "part_a": "frame",
  "part_b": "slider",
  "axis": [1.0, 0.0, 0.0]
}
```

---

## 3. Kinematic Sweep Verification Rules

1. **Revolute Joint Sweep:**
   - Evaluated by sweeping `part_b` through its full rotational travel (default $0^\circ$ to $360^\circ$, or defined range in steps of $30^\circ$ to $45^\circ$).
   - At each angle, the Boolean intersection volume between `part_b` and all static components must remain strictly $0.0\text{ mm}^3$.
2. **Prismatic Joint Sweep:**
   - Evaluated by translating `part_b` along `axis` through its defined stroke ($x_{\text{min}}$ to $x_{\text{max}}$).
   - The moving component must clear all guiding walls, stops, and neighboring links.
3. **Collision Avoidance Rule:**
   - If kinematic sweep fails (ASSY-03), check pivot center distances and link arm clearances. Increase crank offset or lengthen connecting rods to prevent self-collision.
