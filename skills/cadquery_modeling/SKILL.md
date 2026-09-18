---
name: cadquery_modeling
description: Instructions and syntax idioms for writing clean, parametric CadQuery 2.x code.
---

# CadQuery Modeling Guidelines

When writing CadQuery Python scripts for **ForgeAgent**:

## 1. Output Requirements
- Scripts MUST define a top-level object named `result` of type `cq.Workplane` or `cq.Shape`.
- Always import `cadquery as cq`.
- Code must be self-contained and execute cleanly without external assets unless specified.

## 2. Standard Part Construction Pattern
```python
import cadquery as cq

# 1. Base solid creation
result = (
    cq.Workplane("XY")
    .box(40, 30, 10)  # length (X), width (Y), height (Z)
    
    # 2. Select face and create workplane for feature addition/subtraction
    .faces(">Z").workplane()
    
    # 3. Features (holes, cutouts, bosses)
    .hole(5.2)  # Central clearance hole
)
```

### CRITICAL: CadQuery `box()` Centering Behavior & Adding Features on Top
`cq.Workplane("XY").box(L, W, H)` centers the box at `(0, 0, 0)` by default.
- Z extends from `-H/2` to `+H/2`.
- The top face is at `Z = +H/2`, NOT `Z = H`!
- The bottom face is at `Z = -H/2`, NOT `Z = 0`!
- **NEVER create features on top of a box using `cq.Workplane("XY").workplane(offset=H)`** — this leaves an empty air gap of `H/2` between the base and features, creating **disconnected solid bodies (PHYS-01 failure)**!
- **CORRECT Idioms to build features (bosses, lugs, walls) on top of a base:**
  1. **Direct face selection (Recommended):**
     ```python
     result = cq.Workplane("XY").box(BASE_L, BASE_W, BASE_H)
     # Build lugs or bosses directly on the top face:
     result = (
         result.faces(">Z").workplane(centerOption="CenterOfMass")
         .pushPoints([(0, lug_offset), (0, -lug_offset)])
         .rect(lug_len, lug_width)
         .extrude(lug_height)
     )
     ```
  2. **Or start from Z=0 using `centered=(True, True, False)`:**
     `result = cq.Workplane("XY").box(BASE_L, BASE_W, BASE_H, centered=(True, True, False))` (Z is now 0 to H, so `offset=BASE_H` touches the top face).

### CRITICAL: CadQuery Workplane Local Coordinate System & Holes
When selecting a face with `.faces(...)`, CadQuery's default workplane mode is `"ProjectedOrigin"`, which projects the PREVIOUS workplane's origin onto the face.
- **For Centered / Symmetric solids (boxes, cylinders, symmetric blocks):**
  Use `.workplane(centerOption="CenterOfMass")` when placing centered holes or symmetric feature arrays.
  *(Note: when moving between faces like `>Z` then `>X`, without `CenterOfMass` CadQuery may offset the origin to the outer edge seam.)*
- **For Origin-Referenced or Asymmetric parts (L-brackets, bell-cranks, rocker arms where `(0, 0)` is the pivot/datum):**
  **DO NOT use `CenterOfMass`** — on an L-shape, lever, or offset arm, the center of mass is shifted diagonally (e.g. at (11.4, 11.4)), causing `.moveTo(0, 0)` to drill into empty air outside the part!
  Instead, use `centerOption="ProjectedOrigin"` (the default of `.workplane()`), which preserves the exact `(0, 0)` world datum on the face!
- **Holes Through a 3D Solid / Cube:**
  Calling `.hole(diameter)` cuts through the entire solid. E.g. drilling on `>Z` penetrates both +Z and -Z faces.
  Canonical pattern for a perforated cube (e.g. 100x100x100mm cube with centered holes on each face):
  ```python
  result = (
      cq.Workplane("XY")
      .box(100.0, 100.0, 100.0)
      .faces(">Z").workplane(centerOption="CenterOfMass").hole(5.0)
      .faces(">X").workplane(centerOption="CenterOfMass").hole(5.0)
      .faces(">Y").workplane(centerOption="CenterOfMass").hole(5.0)
  )
  ```
- **Global Interface Coordinates:** In `# INTERFACE: name=(x,y,z)...`, specify the exact GLOBAL world coordinate of the hole! For a box centered at `(0, 0, 0)` with height $H$, the top face is at $Z = +H/2$. So holes at local $(\pm 15, 0)$ have global coordinates `(±15, 0, H/2)`.
- **Brackets & Angle Plates (Extruded 2D Profile Idiom):**
  Always construct L-brackets, U-channels, and angle brackets by drawing a 2D polyline profile on the XZ plane and extruding along Y:
  ```python
  pts = [
      (0, 0),
      (length, 0),
      (length, thickness),
      (thickness, thickness),
      (thickness, height),
      (0, height)
  ]
  result = cq.Workplane("XZ").polyline(pts).close().extrude(width)
  # Mounting hole in base plate (centered on base leg):
  result = result.faces(">Z and <X").workplane(centerOption="CenterOfBoundBox").hole(hole_dia)
  # Mounting hole in upright leg:
  result = result.faces("<X").workplane(centerOption="CenterOfBoundBox").hole(hole_dia)
  ```
  *(Note: NEVER use `.extrude(width, both=True)` without halving width — `both=True` extrudes `width` in both directions, making total length $2 \times \text{width}$!)*

- **Clevis Brackets, Forks & U-Lugs (Slot-Cut or Extruded U-Profile Idiom):**
  When modeling a clevis bracket with a base plate and two parallel upright lugs spaced by `gap`:
  **DO NOT** create a wide base and union separate thin lugs with manual offsets — `faces(">X")` will select the outer base ends instead of the lugs, drilling the pivot hole into the base plate instead of through the lugs!
  
  **Canonical Pattern: Subtractive Slot-Cut (Recommended):**
  ```python
  # 1. Solid envelope: base length, width, total height (base thickness + lug height)
  result = cq.Workplane("XY").box(BASE_L, BASE_W, BASE_H + LUG_H, centered=(True, True, False))
  
  # 2. Cut central slot between the two upright lugs:
  result = (
      result.faces(">Z").workplane()
      .rect(LUG_GAP, BASE_W + 1.0)
      .cutBlind(-LUG_H)
  )
  
  # 3. Drill pivot pin hole through both upright lugs (faces('>X') is now the outer lug face!):
  result = (
      result.faces(">X").workplane(centerOption="CenterOfMass")
      .transformed(offset=(0, 0, LUG_H / 2))
      .hole(PIVOT_BORE_D)
  )
  
  # 4. Mounting holes in base plate:
  result = (
      result.faces("<Z").workplane(centerOption="CenterOfMass")
      .pushPoints([(-20, 0), (20, 0)])
      .hole(MOUNT_HOLE_D)
  )
  ```

- **Bell-Cranks, Rocker Arms & Linkage Levers (Center Pivot Idiom):**
  When modeling a bell-crank, rocker arm, or lever with a central pivot and extending arms:
  **ALWAYS place the central pivot hub at `(0, 0)`** so the pivot bore and interface port align at `(0, 0)`.
  ```python
  # 1. Central pivot hub with boss:
  pivot_hub = cq.Workplane("XY").circle(PIVOT_HUB_R).extrude(THICKNESS)
  
  # 2. Arm 1 extending to (L1, 0) with end boss:
  arm1 = cq.Workplane("XY").polyline([
      (0, -ARM_W/2), (L1, -ARM_W/2), (L1, ARM_W/2), (0, ARM_W/2)
  ]).close().extrude(THICKNESS)
  boss1 = cq.Workplane("XY").transformed(offset=(L1, 0, 0)).circle(END_BOSS_R).extrude(THICKNESS)
  
  # 3. Arm 2 extending to (0, L2) with end boss:
  arm2 = cq.Workplane("XY").polyline([
      (-ARM_W/2, 0), (-ARM_W/2, L2), (ARM_W/2, L2), (ARM_W/2, 0)
  ]).close().extrude(THICKNESS)
  boss2 = cq.Workplane("XY").transformed(offset=(0, L2, 0)).circle(END_BOSS_R).extrude(THICKNESS)
  
  # 4. Fuse body and drill all holes (use ProjectedOrigin to keep (0,0) at central pivot!):
  result = pivot_hub.union(arm1).union(boss1).union(arm2).union(boss2)
  result = (
      result.faces(">Z").workplane(centerOption="ProjectedOrigin")
      .hole(PIVOT_BORE_D) # Central pivot at (0, 0)
      .pushPoints([(L1, 0), (0, L2)])
      .hole(LINKAGE_PIN_D) # Linkage pin holes at (L1, 0) and (0, L2)
  )
  # INTERFACE: central_pivot=(0,0,0) dir=(0,0,1) type=hole d=PIVOT_BORE_D
  # INTERFACE: linkage_pin_1=(L1,0,0) dir=(0,0,1) type=hole d=LINKAGE_PIN_D
  # INTERFACE: linkage_pin_2=(0,L2,0) dir=(0,0,1) type=hole d=LINKAGE_PIN_D
  ```

- **Yokes, Slider Frames & Guide Rods (Frame Enclosure Idiom):**
  When modeling a yoke, slider frame, or scotch-yoke with an internal window and an extending guide rod:
  1. **Enclosure Size Sanity:** The outer frame width and length MUST be larger than the internal window to leave positive structural wall thickness ($W_{outer} > W_{window}$ and $L_{outer} > L_{window}$). If the outer frame is smaller than the window, cutting the window severs the frame!
  2. **Guide Rod Location:** An extending guide rod, plunger, or stem attaches to the **end face** of the frame (e.g. `faces(">X")`), NOT on the top face `>Z` where it would float over the empty window hole!
  ```python
  # 1. Outer frame (ensure outer width > window width!)
  result = cq.Workplane("XY").box(FRAME_L, FRAME_W, THICKNESS)
  # 2. Cut internal window through all:
  result = result.faces(">Z").workplane().rect(WIN_L, WIN_W).cutThruAll()
  # 3. Guide rod extending from the end face (>X):
  result = result.faces(">X").workplane(centerOption="CenterOfMass").circle(ROD_D / 2.0).extrude(ROD_L)
  # INTERFACE: guide_rod=(FRAME_L/2 + ROD_L, 0, 0) dir=(1,0,0) type=shaft d=ROD_D
  # INTERFACE: yoke_window=(0, 0, 0) dir=(0,0,1) type=face
  ```

- **Bolts, Screws & Threaded Fasteners (Monolithic Single-Part Idiom):**
  A bolt or screw is always modeled as ONE single part with the head and shank unioned:
  ```python
  # Hexagonal head (extending in +Z)
  head = cq.Workplane("XY").polygon(6, head_dia, circumscribed=False).extrude(head_height)
  # Concentric shank (extending in -Z)
  shaft = cq.Workplane("XY").circle(nominal_dia / 2.0).extrude(-shaft_length)
  result = head.union(shaft)
  # Lead-in chamfers at tip:
  result = result.faces("<Z").edges("%CIRCLE").chamfer(1.0)
  # INTERFACE: bolt_shank=(0,0,0) dir=(0,0,-1) type=shaft d=nominal_dia
  ```
  **CRITICAL THREADING RULE**:
  CadQuery Workplane has **NO `.helix()` method**! NEVER call `cq.Workplane().helix(...)` (causes fatal `AttributeError`).
  In mechanical CAD kernels, 3D helical sweeps for standard fasteners are avoided because OpenCASCADE helical boolean operations frequently fail with `BRep_API: command not done`.
  Fastener threads must be modeled as a nominal cylinder diameter with standard 45°/60° lead-in chamfer at `<Z`. If cosmetic threads are desired, use annular cuts. NEVER call `.helix()` on a Workplane!

- **Plates, Dishes, Bowls & Revolved Parts (Revolve 360 Idiom):**
  Construct dining plates, shallow bowls, bushings, and pulleys using a single 2D closed polygon cross-section on the XZ plane revolved 360° around the Z axis (all X coordinates must be $\ge 0$):
  ```python
  pts = [
      (0, 0),
      (base_dia / 2.0, 0),
      (rim_dia / 2.0, height),
      (rim_dia / 2.0 - rim_lip_width, height),
      (base_dia / 2.0 - wall_thickness, base_thickness),
      (0, base_thickness)
  ]
  # Simply call .revolve() without arguments on 'XZ' workplane (rotates around global Z axis):
  result = cq.Workplane("XZ").polyline(pts).close().revolve()
  ```
  *(CRITICAL: On a `Workplane("XZ")`, calling `.revolve()` with default arguments rotates around the global Z axis. NEVER pass `axisEnd=(0, 0, 1)` because `(0, 0, 1)` is the workplane normal, which rotates the sketch in-plane and creates a 0-volume sheet!)*

- **Flat Blades, Wings, Fins & Slender Parts (Box + Chamfer Idiom):**
  Fan blades, propeller wings, fins, and flat slender parts must be modeled using `.box()` or `.extrude()`, **NEVER** using `.loft()` or `.sweep()`. Loft/sweep operations frequently crash with `ValueError: Nothing to loft` because CadQuery requires multiple sketch sections on different workplanes.
  ```python
  length = 400.0    # blade span (X)
  width = 50.0      # chord (Y)
  thickness = 5.0   # blade thickness (Z)

  # Simple flat blade: box with optional leading/trailing edge chamfers
  result = cq.Workplane("XY").box(length, width, thickness)

  # Optional: taper the tip by chamfering the far-X edges
  # result = result.faces(">X").edges("|Y").chamfer(thickness * 0.4)

  # Mounting boss at root end (attach to motor hub)
  boss_dia = 10.0
  boss_height = 5.0
  boss = cq.Workplane("XY").transformed(offset=(-length/2 + boss_dia/2, 0, thickness/2)).circle(boss_dia/2).extrude(boss_height)
  result = result.union(boss)
  # INTERFACE: root_mount=(-length/2, 0, 0) dir=(-1,0,0) type=shaft d=boss_dia
  ```
  **NEVER use `.loft()` for simple blades!** Loft is only safe when you have exactly 2+ sketches placed on distinct parallel workplanes. For slender flat geometry, always use `.box()` + optional `.chamfer()`.

- **Attached Features & Rings (Union Overlap Idiom):**
  When adding external rings, collars, handles, lugs, or bosses to an existing body using `.union(feature)`:
  The added feature MUST physically embed/overlap into the parent body (embed by $\ge 0.5\text{mm}$).
  For example, for a ring or collar around a tapered vessel/cylinder with outer radius $R(z)$ at height $z$:
  - The ring's inner radius MUST be slightly smaller than the outer radius of the parent wall (e.g. $R_{\text{inner}} = R(z) - 1.0\text{mm}$).
  - The ring's outer radius MUST be larger (e.g. $R_{\text{outer}} = R(z) + 10.0\text{mm}$).
- **Pockets, Cavities, and Blind Cuts (Pocket Cut Idiom):**
  When creating a cavity, pocket, or blind recess in a solid block, ALWAYS chain the cut on the solid using `.faces(">Z").workplane(centerOption="CenterOfMass").rect(pocket_l, pocket_w).cutBlind(-pocket_depth)`:
  ```python
  # Base solid
  result = cq.Workplane("XY").box(outer_l, outer_w, outer_h)
  # Cut centered cavity
  result = (
      result.faces(">Z")
      .workplane(centerOption="CenterOfMass")
      .rect(cavity_l, cavity_w)
      .cutBlind(-cavity_d)
  )
  # INTERFACE: cavity_floor=(0, 0, (outer_h/2.0) - cavity_d) dir=(0, 0, 1) type=face
  ```
  **CRITICAL RULES FOR POCKETS & CUTS:**
  1. **NEVER call `.edges().fillet()` on a 2D sketch!** Calling `.rect(...).edges("|Z").fillet(...)` raises `ValueError: Fillets requires that edges be selected` because a 2D sketch has no vertical edges. Fillets apply ONLY to 3D solid edges AFTER `.cutBlind()` or `.extrude()`.
  2. **Do NOT add corner fillets to internal cuts unless explicitly requested in the prompt or spec.** If the user asks for a 50x50x5 cut and a 50x50x5 block to fit in it, adding fillets to the cut corners causes physical collision/interference with the sharp-cornered insert block!
  3. **Cavity Floor Interface Coordinate:** For a box centered at Z=0 (extending from $-H/2$ to $+H/2$), the top face is at $+H/2$. A blind cut of depth $D$ places the cavity floor at $Z = +H/2 - D$.

## 3. Key CadQuery Operations

- **Box:** `cq.Workplane("XY").box(length_x, width_y, height_z)`
- **Cylinder:** `cq.Workplane("XY").cylinder(height, radius)`
- **Hole:** `.hole(diameter)` or `.cboreHole(diameter, cboreDiameter, cboreDepth)`
- **Pattern Holes (Rectangular):** `.rectArray(xSpacing, ySpacing, xCount, yCount).hole(diameter)`
- **Pattern Holes (Circular/Polar):** `.polarArray(radius, startAngle, angle, count).hole(diameter)` (NOTE: first argument is `radius`, NEVER `startRadius`!)
- **Fillet Edges:** `.edges("|Z").fillet(radius)` (Fillet vertical edges)
- **Chamfer Edges:** `.faces(">Z").edges("%CIRCLE").chamfer(distance)`

## 4. Design & Safety Guidelines
- Ensure all clearance holes match standard bolt clearance diameters (e.g. M4 clearance = $4.3\text{mm}$, M5 clearance = $5.3\text{mm}$, M6 clearance = $6.5\text{mm}$).
- Maintain wall thickness $\ge 1.5\text{mm}$ between holes and outer boundaries.
- **Filleting / Chamfering Safety:** 
  * Never call `.edges().fillet()` or `.edges().chamfer()` blindly on an entire solid after boolean union/cut operations. OpenCascade will crash with `Standard_ConstructionError: ChFi3d_Builder:only 2 faces` or `Fillets requires that edges be selected`.
  * Select specific circular edges via `.faces(">Z").edges("%CIRCLE").fillet(...)` or omit cosmetic edge fillets if not strictly required.

## 5. Coding Safety & Execution Rules
- **Variable Scope:** Define ALL mathematical variables (e.g. `pitch_dia`, `r_outer`, `module`, `num_teeth`, `twist_angle`) AT THE TOP of the script before using them in expressions.
- **Imports:** Always write `import math` and `import cadquery as cq` at the very top.
- **Safe Selectors:** 
  - Use standard face selectors (`.faces(">Z")`, `.faces("<Z")`, `.faces(">X")`).
  - **NEVER** use the English words `"and"` or `"or"` inside selector strings (e.g., `.edges("|Z and <bore_dia")` is INVALID and causes ParseException).
  - **NEVER** put Python variable names inside string literals (e.g., `"<bore_dia"` is INVALID).
  - **NEVER** call `.filterBy(...)` — CadQuery `Workplane` does NOT have a `filterBy` method! Use standard selectors like `.faces(">Z").edges("%CIRCLE")` or omit edge filtering.
  - To select bore edges, select the face first: `.faces(">Z").edges("%CIRCLE")` or filter using Python list comprehensions.
  - **NEVER** call `.edges("|Z").fillet(...)` on a gear body! A gear has 40+ closely spaced vertical tooth edges. Filleting them causes geometry self-intersections and crashes OpenCascade with `Standard_Failure: There are no suitable edges for chamfer or fillet`.
- **Housings, Rings, and Casings Z-Datum Rule:** ALWAYS start base casings with `cq.Workplane("XY").rect(W, L).extrude(H)` or `.circle(R).extrude(H)` starting from $Z=0$. **NEVER** use `cq.Workplane("XY").box(W, L, H)` for hollow casings, because `.box()` centers at $Z=0$ ($Z \in [-H/2, H/2]$). When you subsequently call `.extrude(H)` to cut the cavity, `.extrude()` only cuts $Z > 0$, leaving the bottom half ($Z < 0$) as an un-cut solid obstruction that causes gross assembly collisions!
  - For gears, **NEVER** call `.edges().chamfer()` or `.edges().fillet()` across entire top/bottom faces — selecting all edges includes every tiny tooth profile edge and causes OpenCASCADE `StdFail_NotDone: BRep_API: command not done`! Only chamfer the central bore or plain outer circular rim using `.faces('>Z').edges('%CIRCLE').chamfer(...)`, or omit tooth chamfers entirely.
- **INTERNAL RING GEARS & HOUSINGS:**
  - An internal ring gear must have a continuous outer housing: $D_{\text{outer}} \ge D_{\text{pitch}} + 20\text{mm}$ (giving at least $8\text{mm}$ of solid rim beyond tooth roots).
  - Mounting holes must NEVER intersect tooth roots or breach the outer casing wall! Place mounting holes on an **external mounting flange** ($D_{\text{flange}} \ge D_{\text{outer}} + 20\text{mm}$) or ensure hole boundaries have $\ge 3\text{mm}$ solid clearance from both the teeth and outer rim.

## 6. Helical & Spur Gear Modeling Pattern
- **Outer Tip Diameter:** $D_{\text{outer}} = D_{\text{pitch}} + 2 \times \text{module}$. Note that the physical bounding box will be $D_{\text{outer}}$, not $D_{\text{pitch}}$!
- **Z-Coordinate Convention:** All gears, pinions, splines, and rotating solids must be constructed starting at $Z=0$ and extending along $+Z$ ($Z \in [0, \text{face\_width}]$). **NEVER** center the gear on $Z$ using `.translate((0, 0, -face_width / 2))` — doing so misaligns tooth contact planes and penetrates bottom carrier plates!
- **Spur Gears & Straight Splines (Default & Robust):** ALWAYS generate a single 2D polyline and `.extrude(face_width)`. This is instantaneous, mathematically watertight, and avoids OpenCascade loft crashes.
- **Helical Gears (Twisted Teeth Only):** When helix twist is strictly required, use `cq.Solid.makeLoft(wires)` with at most 4 to 6 slices.

```python
import cadquery as cq
import math

# Parameters
pitch_dia = 50.0
num_teeth = 20
face_width = 15.0
bore_dia = 10.0

module = pitch_dia / num_teeth
r_pitch = pitch_dia / 2.0
r_outer = r_pitch + (1.0 * module)
r_root = r_pitch - (1.25 * module)

# 1. Straight Spur Gear / Spline: Extrude 2D polygon directly
pts = []
for t in range(num_teeth):
    a_center = (2 * math.pi * t / num_teeth)
    a_half = math.pi / (2 * num_teeth)
    pts.append((r_root * math.cos(a_center - a_half), r_root * math.sin(a_center - a_half)))
    pts.append((r_outer * math.cos(a_center - a_half/2), r_outer * math.sin(a_center - a_half/2)))
    pts.append((r_outer * math.cos(a_center + a_half/2), r_outer * math.sin(a_center + a_half/2)))
    pts.append((r_root * math.cos(a_center + a_half), r_root * math.sin(a_center + a_half)))

result = cq.Workplane("XY").polyline(pts).close().extrude(face_width)
result = result.faces(">Z").workplane().hole(bore_dia)
```


## 7. Internal Ring Gear Modeling Pattern
To create an **internal ring gear** in CadQuery, generate the 2D polygon of all internal teeth in a single polyline, extrude it, and cut it from an outer cylindrical casing:

```python
import cadquery as cq
import math

# Parameters
pitch_dia = 90.0
num_teeth = 60
face_width = 25.0
module = pitch_dia / num_teeth
outer_dia = pitch_dia + 30.0  # Outer casing diameter

r_pitch = pitch_dia / 2.0
r_root = r_pitch + (1.25 * module)  # Internal teeth: root is at larger radius
r_tip = r_pitch - (1.0 * module)    # Tip is towards center

# 1. Single closed polyline containing all internal teeth
pts = []
for t in range(num_teeth):
    a_center = 2 * math.pi * t / num_teeth
    a_half = math.pi / (2 * num_teeth)
    pts.append((r_root * math.cos(a_center - a_half), r_root * math.sin(a_center - a_half)))
    pts.append((r_tip * math.cos(a_center - a_half / 2), r_tip * math.sin(a_center - a_half / 2)))
    pts.append((r_tip * math.cos(a_center + a_half / 2), r_tip * math.sin(a_center + a_half / 2)))
    pts.append((r_root * math.cos(a_center + a_half), r_root * math.sin(a_center + a_half)))

tooth_wire = cq.Workplane("XY").polyline(pts).close()
inner_cut = tooth_wire.extrude(face_width)

# 2. Outer housing cylinder cut with internal teeth
casing = cq.Workplane("XY").circle(outer_dia / 2.0).extrude(face_width)
result = casing.cut(inner_cut)

# 3. Optional mounting holes on outer flange
mounting_pcd = (outer_dia + r_root * 2.0) / 2.0
result = result.faces(">Z").workplane().polarArray(mounting_pcd / 2.0, 0, 360, 4).hole(5.3)
```

## 8. Fastener Modeling Pattern (Hex Bolts, Nuts, Washers)
When creating hex bolts, nuts, or fasteners:
- **`polygon()` API Warning:** `cq.Workplane.polygon(nSides, diameter, circumscribed=False)` expects the **FULL DIAMETER / WIDTH ACROSS FLATS**, **NEVER RADIUS**!
- If an M4 bolt has width across flats $s = 7.0\text{mm}$, write `.polygon(6, 7.0, circumscribed=False)`. Passing `7.0 / 2 = 3.5` will make the hex head smaller than the shaft!
- **Standard ISO Metric Proportions:**
  - **M3:** Shaft $\varnothing 3.0\text{mm}$, Hex flats $5.5\text{mm}$, Head height $2.0\text{mm}$
  - **M4:** Shaft $\varnothing 4.0\text{mm}$, Hex flats $7.0\text{mm}$, Head height $2.8\text{mm}$
  - **M5:** Shaft $\varnothing 5.0\text{mm}$, Hex flats $8.0\text{mm}$, Head height $3.5\text{mm}$
  - **M6:** Shaft $\varnothing 6.0\text{mm}$, Hex flats $10.0\text{mm}$, Head height $4.0\text{mm}$

```python
import cadquery as cq

# Standard M4 Hex Bolt
shaft_diameter = 4.0
shaft_length = 12.0
hex_width_across_flats = 7.0  # FULL width across flats (diameter)
head_height = 2.8

# Hex head sitting on XY plane
head = (
    cq.Workplane("XY")
    .polygon(6, hex_width_across_flats, circumscribed=False)
    .extrude(head_height)
)

# Shaft extending downwards below head
shaft = (
    cq.Workplane("XY")
    .circle(shaft_diameter / 2.0)
    .extrude(-shaft_length)
)

result = head.union(shaft).edges("<Z").chamfer(0.4)
```

## 9. Planet & Output Carrier Modeling Pattern
When creating a **carrier plate** (planet carrier, spider, or cycloidal output carrier):
- Model as a single, clean circular base plate with central bore and polar array pin mounting holes.
- Avoid unnecessary weight-reduction pockets or complex indexed selectors (`>Z[-2]`) which fail in CadQuery.
- **CRITICAL FILLET RULE:** ALWAYS fillet outer circular edges (`.edges(">Z").edges("%CIRCLE").fillet(...)`) **BEFORE** drilling holes! If you call `.edges("%CIRCLE").fillet()` after drilling holes, CadQuery selects the edges of all holes and crashes OpenCascade with `StdFail_NotDone: BRep_API: command not done`.

```python
import cadquery as cq

# Parameters
plate_diameter = 80.0
plate_thickness = 10.0
center_bore_dia = 8.0
center_to_center_distance = 27.0
num_planets = 3
pin_hole_dia = 5.3
fillet_radius = 2.0

# 1. Base plate
result = cq.Workplane("XY").circle(plate_diameter / 2.0).extrude(plate_thickness)

# 2. Outer rim fillets (MUST BE APPLIED BEFORE DRILLING HOLES!)
result = (
    result.edges(">Z").edges("%CIRCLE").fillet(fillet_radius)
    .edges("<Z").edges("%CIRCLE").fillet(fillet_radius)
)

# 3. Central output bore (drilled after filleting)
result = result.faces(">Z").workplane().hole(center_bore_dia)

# 4. Planet pin mounting holes (drilled after filleting)
result = result.faces(">Z").workplane().polarArray(center_to_center_distance, 0, 360, num_planets).hole(pin_hole_dia)
```

## 10. Cycloidal Drive Modeling Pattern

### A. True Analytical Cycloid Disc (Equidistant Epitrochoid Math)
To create a mathematically conjugate, smooth cycloidal disc profile that rolls seamlessly against stationary ring pins with conjugate action:

```python
import cadquery as cq
import math

# Shared Kinematic Invariants
num_lobes = 10          # Z lobes for 10:1 reduction
num_ring_pins = 11      # N = Z + 1
pin_ring_dia = 120.0    # Pin ring pitch diameter (2 * Rp)
pin_dia = 8.0           # Stationary pin roller diameter (2 * Rr)
eccentricity = 2.0      # Eccentric shaft offset (e)
carrier_pin_pcd = 60.0  # Shared PCD for carrier drive pins
output_pin_dia = 6.0    # Diameter of carrier drive studs
disc_thickness = 15.0

# Mathematical constants
Rp = pin_ring_dia / 2.0
Rr = (pin_dia / 2.0) + 0.05  # slight clearance offset for smooth rolling
e = eccentricity
Z = num_lobes

# 1. Generate exact analytical equidistant curve of epitrochoid
num_pts = 720
pts = []
for i in range(num_pts):
    theta = 2.0 * math.pi * i / num_pts
    denom = (Rp / (e * (Z + 1))) - math.cos(Z * theta)
    numer = math.sin(Z * theta)
    psi = math.atan2(numer, denom)
    x = Rp * math.cos(theta) - e * math.cos((Z + 1) * theta) - Rr * math.cos(theta + psi)
    y = Rp * math.sin(theta) - e * math.sin((Z + 1) * theta) - Rr * math.sin(theta + psi)
    pts.append((x, y))

result = cq.Workplane("XY").polyline(pts).close().extrude(disc_thickness)

# 2. Central bearing bore for eccentric input lobe
center_bore_dia = 25.1
result = result.faces(">Z").workplane().hole(center_bore_dia)

# 3. Carrier drive pin holes (oversized to allow orbiting motion: D = d_pin + 2*e + 0.5)
carrier_hole_dia = output_pin_dia + (2.0 * eccentricity) + 0.5
result = (
    result.faces(">Z").workplane()
    .polarArray(carrier_pin_pcd / 2.0, 0, 360, 6)
    .hole(carrier_hole_dia)
)

# INTERFACE: center_bore=(0,0,disc_thickness/2) dir=(0,0,1) type=hole d=25.1
# INTERFACE: cycloid_profile=(0,0,disc_thickness/2) dir=(0,0,1) type=gear_mesh d=120.0
# INTERFACE: drive_holes=(30.0,0,disc_thickness/2) dir=(0,0,1) type=hole d=10.5
```

### B. Stationary Ring Housing with Circular Bolt Flange (Annular Flanged Casing)
Always model gearbox casings as axisymmetric annular bodies with circular mounting flanges:

```python
import cadquery as cq
import math

pin_ring_dia = 120.0
pin_dia = 8.0
num_pins = 11
housing_od = 136.0
flange_dia = 160.0
flange_thickness = 8.0
housing_height = 30.0
mounting_pcd = 148.0
mounting_hole_dia = 5.3

# 1. Outer cylindrical casing body
casing = cq.Workplane("XY").circle(housing_od / 2.0).extrude(housing_height)

# 2. Outer circular mounting flange
flange = cq.Workplane("XY").circle(flange_dia / 2.0).extrude(flange_thickness)
result = casing.union(flange)

# 3. Inner cavity cut (bore cut at pin center circle)
cavity = cq.Workplane("XY").circle(pin_ring_dia / 2.0).extrude(housing_height)
result = result.cut(cavity)

# 4. Stationary pin rollers embedded into inner wall
pins = (
    cq.Workplane("XY")
    .polarArray(pin_ring_dia / 2.0, 0, 360, num_pins)
    .circle(pin_dia / 2.0)
    .extrude(housing_height)
)
result = result.union(pins)

# 5. Mounting holes on circular flange
result = (
    result.faces(">Z").workplane()
    .polarArray(mounting_pcd / 2.0, 0, 360, 6)
    .hole(mounting_hole_dia)
)

# INTERFACE: ring_pins=(0,0,housing_height/2) dir=(0,0,1) type=gear_mesh d=120.0
# INTERFACE: mounting_flange=(0,0,0) dir=(0,0,-1) type=face d=160.0
```

### C. Output Pin Carrier Flange with Extruded Drive Studs
```python
import cadquery as cq

plate_dia = 100.0
plate_thickness = 8.0
carrier_pin_pcd = 60.0
output_pin_dia = 6.0
pin_height = 17.0  # disc_thickness + 2mm
center_shaft_dia = 15.0

# 1. Base circular carrier plate
plate = cq.Workplane("XY").circle(plate_dia / 2.0).extrude(plate_thickness)

# 2. Extruded drive studs that capture the cycloid disc
studs = (
    cq.Workplane("XY")
    .workplane(offset=plate_thickness)
    .polarArray(carrier_pin_pcd / 2.0, 0, 360, 6)
    .circle(output_pin_dia / 2.0)
    .extrude(pin_height)
)
result = plate.union(studs)

# 3. Output shaft / bearing bore
result = result.faces("<Z").workplane().hole(center_shaft_dia)

# INTERFACE: drive_studs=(30.0,0,plate_thickness + pin_height/2) dir=(0,0,1) type=pin d=6.0
# INTERFACE: output_bore=(0,0,plate_thickness/2) dir=(0,0,-1) type=shaft d=15.0
```

### D. Stepped Input Shaft with Eccentric Lobe
```python
import cadquery as cq

eccentricity = 2.0
main_shaft_dia = 12.0
lobe_dia = 25.0
lobe_thickness = 15.0
total_length = 60.0
lobe_z_start = 10.0

# 1. Main concentric shaft
shaft = cq.Workplane("XY").circle(main_shaft_dia / 2.0).extrude(total_length)

# 2. Eccentric driving lobe offset along X
lobe = (
    cq.Workplane("XY")
    .workplane(offset=lobe_z_start)
    .moveTo(eccentricity, 0)
    .circle(lobe_dia / 2.0)
    .extrude(lobe_thickness)
)
result = shaft.union(lobe)

# INTERFACE: eccentric_lobe=(2.0,0,lobe_z_start + lobe_thickness/2) dir=(0,0,1) type=shaft d=25.0
# INTERFACE: input_shaft=(0,0,0) dir=(0,0,-1) type=shaft d=12.0
```

## 11. Hinge Knuckles & Interleaved Barrel Hinges (Piano / Butt Hinges)
When creating interleaved hinge knuckles for boxes, enclosures, doors, or folding linkages:
- **Hinge Axis Orientation:** The hinge pin axis runs parallel to the hinge edge (e.g. parallel to Y if along the width edge, or parallel to X if along the length edge).
- **Knuckle Sizing & Minimum Wall:** Knuckle outer diameter MUST satisfy $OD \ge d_{\text{pin\_hole}} + 2 \times t_{\text{min\_wall}}$. For a $3.2\text{mm}$ bore in 3D printing (min wall $2.0\text{mm}$), $OD \ge 3.2 + 4.0 = 7.2\text{mm}$ (use $8.0\text{mm}$ or $10.0\text{mm}$). NEVER use an OD $< 7.2\text{mm}$ for a $3.2\text{mm}$ pin hole!
- **Knuckle Center Placement:** Place the knuckle center $(c_x, c_z)$ tangent to the outer box wall (e.g. $c_x = -L/2 - OD/2$, $c_z = H/2$ at the top seam) with solid connecting leaf tabs to the wall.
- **Robust Construction Sequence:**
  1. Extrude knuckles as solid cylinders along the hinge axis.
  2. Union solid leaf tabs connecting the box wall to the knuckle cylinders.
  3. Drill the continuous pin bore straight through ALL knuckles in one clean cut using `.cut()` along the axis. This guarantees zero interference and perfect coaxial alignment!
- **Interleaving Pattern:**
  If base has $N=2$ knuckles of width $W_k$ at $Y = [-20, 0]$, the matching lid has interleaved knuckles at $Y = [-10, 10]$!
- **Pin:**
  Model the pin as a simple cylinder of nominal diameter ($3.0\text{mm}$), extruded along the hinge axis to span all 4 knuckles plus retention overhang (e.g. $40\text{mm} + 4\text{mm} = 44\text{mm}$).
- **Interface Ports:** Coaxial ports with matching direction vectors:
  `# INTERFACE: hinge_knuckle_bore=(cx, 0.0, cz) dir=(0, 1, 0) type=hole d=3.2`
  `# INTERFACE: pin_surface=(cx, 0.0, cz) dir=(0, 1, 0) type=shaft d=3.0`

```python
import cadquery as cq

# Base box 120 x 80 x 40 with hinge knuckles along 80mm edge (Y-axis)
length = 120.0
width = 80.0
height = 40.0
wall_thickness = 3.0
knuckle_width = 10.0
knuckle_od = 8.0
pin_hole_dia = 3.2

# 1. Base hollow shell
box = cq.Workplane("XY").box(length, width, height, centered=(True, True, True)).faces(">Z").shell(-wall_thickness)

# 2. Hinge axis along Y at top edge of back wall (X = -length/2)
cx = -length / 2.0 - knuckle_od / 2.0
cz = height / 2.0  # Top edge

# Solid connecting tabs (full knuckle_od height to guarantee >= 2mm wall around bore) and knuckle cylinders
tab1 = cq.Workplane("XY").workplane(offset=cz - knuckle_od / 2.0).transformed(offset=(cx + knuckle_od / 4.0, -15.0, 0)).box(knuckle_od / 2.0, knuckle_width, knuckle_od, centered=(True, True, False))
tab2 = cq.Workplane("XY").workplane(offset=cz - knuckle_od / 2.0).transformed(offset=(cx + knuckle_od / 4.0, 5.0, 0)).box(knuckle_od / 2.0, knuckle_width, knuckle_od, centered=(True, True, False))

k1 = cq.Workplane("XZ").workplane(offset=-20.0).transformed(offset=(cx, cz)).circle(knuckle_od / 2.0).extrude(knuckle_width)
k2 = cq.Workplane("XZ").workplane(offset=0.0).transformed(offset=(cx, cz)).circle(knuckle_od / 2.0).extrude(knuckle_width)

result = box.union(tab1).union(tab2).union(k1).union(k2)

# 3. Continuous pin bore through all knuckles
bore = cq.Workplane("XZ").workplane(offset=-50.0).transformed(offset=(cx, cz)).circle(pin_hole_dia / 2.0).extrude(100.0)
result = result.cut(bore)

# INTERFACE: hinge_knuckle_bore=(cx, 0.0, cz) dir=(0, 1, 0) type=hole d=3.2
```

## 12. Storage Box & Matching Fitted Lid with Rim Lip
When modeling a matching lid for an open-top box:
- **Overall Lid Dimensions:** The lid outer dimensions ($L \times W \times H_{\text{lid}}$) MUST match the specified spec dimensions (e.g. $120 \times 80 \times 15$). Start with `cq.Workplane("XY").box(length, width, height, centered=(True, True, False))` ($Z \in [0, \text{height}]$). NEVER substitute `wall_thickness` for `height` when `height` is given!
- **Rim Lip (Sliding Fit):** The rim lip extends from the bottom face ($<Z$, at $Z=0$) of the lid downward into the open box interior.
  To slide inside the base opening $(L - 2t) \times (W - 2t)$ with clearance $c$ (e.g. $0.3\text{mm}$):
  `lip_l = (length - 2 * wall_thickness) - 2 * sliding_clearance`
  `lip_w = (width - 2 * wall_thickness) - 2 * sliding_clearance`
- **Robust Monolithic Construction Sequence:**
  NEVER shell a lid from $<Z$ and then try to union a floating lip ring into the empty open air (causes PHYS-01 disconnected solids)!
  Instead, extrude the lip downward from the solid bottom face, then hollow out the center from $<Z$:
  ```python
  # 1. Solid lid block (Z from 0 to height)
  lid = cq.Workplane("XY").box(length, width, height, centered=(True, True, False))

  # 2. Extrude rim lip downward from bottom face (Z=0)
  lid = (
      lid.faces("<Z")
      .workplane(centerOption="CenterOfMass")
      .rect(lip_l, lip_w)
      .extrude(-rim_lip_overlap)
  )

  # 3. Hollow out the center cavity from <Z (leaving solid ceiling of wall_thickness)
  lid = (
      lid.faces("<Z")
      .workplane(centerOption="CenterOfMass")
      .rect(lip_l - 2 * wall_thickness, lip_w - 2 * wall_thickness)
      .cutBlind(rim_lip_overlap + (height - wall_thickness))
  )

  # 4. Hinge knuckles at back edge (X = -length/2) at bottom seam (Z = 0)
  cx = -length / 2.0 - knuckle_od / 2.0
  cz = 0.0
  k1 = cq.Workplane("XZ").workplane(offset=-10.0).transformed(offset=(cx, cz)).circle(knuckle_od / 2.0).extrude(knuckle_width)
  k2 = cq.Workplane("XZ").workplane(offset=10.0).transformed(offset=(cx, cz)).circle(knuckle_od / 2.0).extrude(knuckle_width)
  tab1 = cq.Workplane("XY").workplane(offset=cz - knuckle_od / 2.0).transformed(offset=(cx + knuckle_od / 4.0, -5.0, 0)).box(knuckle_od / 2.0, knuckle_width, knuckle_od, centered=(True, True, False))
  tab2 = cq.Workplane("XY").workplane(offset=cz - knuckle_od / 2.0).transformed(offset=(cx + knuckle_od / 4.0, 15.0, 0)).box(knuckle_od / 2.0, knuckle_width, knuckle_od, centered=(True, True, False))
  lid = lid.union(k1).union(k2).union(tab1).union(tab2)

  # 5. Continuous pin bore
  bore = cq.Workplane("XZ").workplane(offset=-50.0).transformed(offset=(cx, cz)).circle(bore_diameter / 2.0).extrude(100.0)
  result = lid.cut(bore)
  # INTERFACE: hinge_knuckle_bore=(cx, 0.0, 0.0) dir=(0, 1, 0) type=hole d=3.2
  ```




