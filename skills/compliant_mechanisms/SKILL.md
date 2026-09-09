---
name: compliant_mechanisms
description: Engineering rules, formulas, and CadQuery modeling patterns for compliant, flexible, snap-fit, and strain wave (harmonic) mechanisms.
---

# Compliant & Flexible Mechanisms Skill

Guidelines for modeling compliant mechanisms where elastic deformation, compliance, or controlled interference is an intended functional feature rather than a CAD clash.

---

## 1. Scope of Compliant Mechanisms

| Mechanism Family | Typical Components | Deformation Principle | Allowable Elastic Strain / Deflection |
|---|---|---|---|
| **Strain Wave (Harmonic) Drives** | Flexspline cup, Wave generator cam, Circular spline | Pure bending of thin cup into ellipse | Radial deflection $\delta = w_0 \approx 0.0125 - 0.025 \times D_{\text{pitch}}$ |
| **Cantilever Snap-Fits & Clips** | Retention latch, cantilever beam, mating lug | Bending deflection during assembly | Peak strain $\epsilon = \frac{1.5 \cdot t \cdot y}{L^2} \le 1.5\%$ (Plastics) |
| **Living Hinges & Flexure Pivots** | Necked-down hinge section, parallel flexures | High-fatigue localized bending | Hinge thickness $t = 0.4\text{ mm} - 0.8\text{ mm}$ (PP / POM / Nylon) |
| **Press Fits & Interference Joints** | Bushing into bore, pin into hub | Radial hoop compression/expansion | Interference $\delta = 0.0005 - 0.0015 \times D_{\text{nominal}}$ |
| **Leaf Springs & Detents** | Curved spring blade, detent ball/pocket | Reversible beam deflection | Strain $\epsilon \le \frac{\sigma_{\text{yield}}}{E}$ |

---

## 2. Harmonic Drive (Strain Wave Gearing) Engineering Rules

A standard two-lobe Harmonic Drive consists of three concentric coaxial parts:

```
          ┌───────────────────────────────────────────────┐
          │ Circular Spline (Rigid outer internal ring)   │
          │   ┌───────────────────────────────────────┐   │
          │   │ Flexspline Cup (Thin elastic cup)     │   │
          │   │   ┌───────────────────────────────┐   │   │
          │   │   │ Wave Generator (Elliptical)   │   │   │
          │   │   └───────────────────────────────┘   │   │
          │   └───────────────────────────────────────┘   │
          └───────────────────────────────────────────────┘
```

### A. Kinematic Sizing Rules
1. **Tooth Count Condition**:
   $$\Delta Z = Z_{\text{circular}} - Z_{\text{flex}} = 2 \quad \text{(for 2-lobe wave generator)}$$
   Gear ratio $R$ (with wave generator input, flexspline output, circular spline fixed):
   $$R = -\frac{Z_{\text{flex}}}{\Delta Z} = -\frac{Z_{\text{flex}}}{2}$$
   *(Example: $Z_{\text{flex}} = 100, Z_{\text{circular}} = 102 \implies R = 50:1$)*

2. **Wave Generator Cam Sizing**:
   - The cam is an ellipse in the XY plane:
     - Major semi-axis: $a = \frac{D_{\text{pitch}}}{2} - t_{\text{wall}}$
     - Minor semi-axis: $b = a - 2 \cdot w_0$, where radial displacement $w_0 = m = \frac{D_{\text{pitch}}}{Z_{\text{flex}}}$ (module)
   - In CadQuery, model the cam using:
     ```python
     cam = cq.Workplane("XY").ellipse(major_radius, minor_radius).extrude(cam_width)
     ```

3. **Flexspline Cup Sizing**:
   - Must be thin-walled to flex elastically without yielding:
     $$t_{\text{wall}} \approx 0.010 \times D_{\text{pitch}} \quad \text{to} \quad 0.018 \times D_{\text{pitch}}$$
   - Cup depth / length $L_{\text{cup}} \ge 0.6 \times D_{\text{pitch}}$ to allow smooth torsional-to-radial deflection gradient.
   - Bore inner diameter in un-deformed free state:
     $$D_{\text{cup\_inner}} = 2 \times \left(\frac{D_{\text{pitch}}}{2} - t_{\text{wall}}\right)$$
   - **CRITICAL CAD PATTERN (Avoid Solid Cup Trap)**: When modeling the cup with external gear teeth or flanges, **ALWAYS cut the internal cavity LAST**:
     ```python
     # 1. Base outer cylinder
     cup_outer = cq.Workplane("XY").circle(r_pitch + module).extrude(cup_height)
     # 2. Union teeth to outer body FIRST
     body = cup_outer.union(teeth_solid)
     # 3. Cut internal cavity AFTER unioning (prevents solid teeth from filling the cup interior)
     cup_inner = cq.Workplane("XY").workplane(offset=base_thickness).circle(r_pitch - wall_thickness).extrude(cup_height)
     result = body.cut(cup_inner)
     ```

4. **Interface Export Convention**:
   The Designer MUST export the compliant interface so the assembly verifier recognizes allowable elastic deflection:
   ```python
   # INTERFACE: cam_interface=(0,0,15) dir=(0,0,1) type=compliant_fit d=77.0 max_deflection=1.5
   ```

---

## 3. Cantilever Snap-Fit & Latch Rules

When designing plastic or spring-metal cantilever snaps:

1. **Beam Proportions**:
   - Length $L \ge 5 \times t$ (thickness at root) to keep bending strain within the elastic limit.
   - Taper the beam from root ($t$) to tip ($0.5 \times t$) to distribute stress uniformly.
2. **Angles**:
   - Lead-in angle (insertion): $\alpha = 25^\circ - 35^\circ$ for smooth push-on assembly.
   - Retention angle (lock): $\beta = 45^\circ - 60^\circ$ for removable, or $90^\circ$ for permanent latch.
3. **Interface Export Convention**:
   ```python
   # INTERFACE: latch_clip=(20, 0, 10) dir=(1,0,0) type=snap_fit d=3.0 max_deflection=1.2
   ```

---

## 4. Press Fits & Precision Pins

1. **Interference Fit (FN / H7/p6 / H7/s6)**:
   - For an $8\text{ mm}$ pin in an $8\text{ mm}$ bore, nominal solid model should have either zero clearance (line-to-line) or explicit press-fit interface comment:
   ```python
   # INTERFACE: dowel_bore=(15, 20, 0) dir=(0,0,1) type=press_fit d=8.0 max_deflection=0.03
   ```

---

## 5. Verification & Assembly Guidelines for Compliant Models

1. **Do NOT Artificially Displace Parts**:
   - In assemblies with concentric wave generators, bushings, or snap fits, do NOT move them off-axis to avoid collision. They belong concentric at their physical mating location.
2. **Tag Compliant Interfaces**:
   - Always declare `type=compliant_fit`, `type=snap_fit`, or `type=press_fit` in the `# INTERFACE:` comment.
   - Always specify `max_deflection=<value>` (e.g. `1.5` mm for harmonic drives, `0.8` mm for snap clips, `0.05` mm for press pins).
3. **Kernel Collision Exemption**:
   - The Assembly Verifier uses this metadata to verify that interference penetration does not exceed `max_deflection`. Overlaps within the elastic limit will PASS with a compliant clearance verdict.
