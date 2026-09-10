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

### CRITICAL: CadQuery Workplane Local Coordinate System & Holes
When selecting a face with `.faces(...)`, CadQuery's default workplane mode is `"ProjectedOrigin"`, which projects the PREVIOUS workplane's origin onto the face.
- **ALWAYS use `.workplane(centerOption="CenterOfMass")` or `.workplane(centerOption="CenterOfBoundBox")` when placing holes or features on faces!**
  If you do not specify `centerOption="CenterOfMass"`, moving between faces (e.g. drilling `>Z` then `>X`) causes CadQuery to offset the origin onto the outer edge seam `(50, 0, 50)`, drilling a slot/groove into the corner rather than a centered hole!
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

- **Attached Features & Rings (Union Overlap Idiom):**
  When adding external rings, collars, handles, lugs, or bosses to an existing body using `.union(feature)`:
  The added feature MUST physically embed/overlap into the parent body (embed by $\ge 0.5\text{mm}$).
  For example, for a ring or collar around a tapered vessel/cylinder with outer radius $R(z)$ at height $z$:
  - The ring's inner radius MUST be slightly smaller than the outer radius of the parent wall (e.g. $R_{\text{inner}} = R(z) - 1.0\text{mm}$).
  - The ring's outer radius MUST be larger (e.g. $R_{\text{outer}} = R(z) + 10.0\text{mm}$).
  - If $R_{\text{inner}} \ge R(z)$, the ring floats in midair with a gap, producing 2 disconnected solid bodies and failing manifold verification (`PHYS-01`).

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


