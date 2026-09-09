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
When you select a face with `.faces(">Z").workplane()`, the local origin `(0, 0)` is at the **center of the selected face**, NOT at global `(0, 0, 0)`.
- If you want a hole at the center of the face, simply call `.hole(diameter)`.
- If you want multiple holes symmetrically spaced, use `.pushPoints([(-spacing/2, 0), (spacing/2, 0)]).hole(diameter)`.
- **Global Interface Coordinates:** In `# INTERFACE: name=(x,y,z)...`, specify the exact GLOBAL world coordinate of the hole! For a box centered at `(0, 0, 0)` with height $H$, the top face is at $Z = +H/2$. So holes at local $(\pm 15, 0)$ have global coordinates `(±15, 0, H/2)`.
- **Brackets & Plates:** Always start with `cq.Workplane("XY").box(length, width, thickness)` so the part is cleanly centered. For an L-bracket, union two centered boxes:
  ```python
  base = cq.Workplane("XY").box(length, width, thickness).translate((0, 0, thickness / 2))
  upright = cq.Workplane("XY").box(thickness, width, height).translate((-length / 2 + thickness / 2, 0, height / 2))
  result = base.union(upright)
  # Drill hole through base:
  result = result.faces(">Z and <X").workplane().hole(hole_dia)
  ```
- **Bolts & Fasteners:** Construct with head on XY plane extending in $+Z$ and shaft extending in $-Z$:
  ```python
  head = cq.Workplane("XY").polygon(6, width_across_flats, circumscribed=False).extrude(head_height)
  shaft = cq.Workplane("XY").circle(nominal_diameter / 2.0).extrude(-shaft_length)
  result = head.union(shaft)
  # INTERFACE: bolt_shank=(0,0,0) dir=(0,0,-1) type=shaft d=5.0
  ```

## 3. Key CadQuery Operations
- **Box:** `cq.Workplane("XY").box(length_x, width_y, height_z)`
- **Cylinder:** `cq.Workplane("XY").cylinder(height, radius)`
- **Hole:** `.hole(diameter)` or `.cboreHole(diameter, cboreDiameter, cboreDepth)`
- **Pattern Holes (Rectangular):** `.rectArray(xSpacing, ySpacing, xCount, yCount).hole(diameter)`
- **Pattern Holes (Circular/Polar):** `.polarArray(radius, startAngle, angle, count).hole(diameter)` (NOTE: first argument is `radius`, NEVER `startRadius`!)
- **Fillet Edges:** `.edges("|Z").fillet(radius)` (Fillet vertical edges)
- **Chamfer Edges:** `.edges(">Z").chamfer(distance)`

## 4. Design Guidelines
- Ensure all clearance holes match standard bolt clearance diameters (e.g. M4 clearance = $4.3\text{mm}$, M5 clearance = $5.3\text{mm}$).
- Maintain wall thickness $\ge 1.5\text{mm}$ between holes and outer boundaries.

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

### A. Cycloid Disk (Multi-Lobe Cam Profile)
To create a watertight, smooth cycloid disk with $N$ lobes (e.g. 29, 39, or 49 lobes) that avoids self-intersecting root loops:
```python
import cadquery as cq
import math

# Parameters
pitch_dia = 70.0
eccentricity = 1.2
num_lobes = 29  # For 30:1 or 50:1 cycloidal gear drive
disk_thickness = 8.0
center_bore_dia = 15.0  # Bearing fit for eccentric input shaft
pin_circle_dia = 42.0
num_pin_holes = 6
pin_hole_dia = 10.0  # Oversized: pin_dia + 2*eccentricity

r_base = pitch_dia / 2.0

# 1. Generate smooth, non-self-intersecting multi-lobe profile
num_pts = max(360, num_lobes * 12)
pts = []
for i in range(num_pts):
    theta = 2.0 * math.pi * i / num_pts
    r = r_base + eccentricity * math.cos(num_lobes * theta)
    pts.append((r * math.cos(theta), r * math.sin(theta)))

result = cq.Workplane("XY").polyline(pts).close().extrude(disk_thickness)

# 2. Central bearing bore for eccentric shaft
result = result.faces(">Z").workplane().hole(center_bore_dia)

# 3. Carrier pin drive holes
result = (
    result.faces(">Z").workplane()
    .polarArray(pin_circle_dia / 2.0, 0, 360, num_pin_holes)
    .hole(pin_hole_dia)
)

# INTERFACE: disk_bore=(0,0,disk_thickness/2) dir=(0,0,1) type=hole d=15.0
# INTERFACE: pin_holes=(21.0,0,disk_thickness/2) dir=(0,0,1) type=hole d=10.0
# INTERFACE: lobe_profile=(0,0,disk_thickness/2) dir=(0,0,1) type=gear_mesh d=70.0
```

### B. Stationary Ring Housing with Outer Pin Rollers
To create the cycloidal ring housing:
```python
import cadquery as cq
import math

outer_dia = 100.0
pin_ring_dia = 72.0
pin_dia = 5.0
num_pins = 30  # num_lobes + 1
housing_height = 16.0

# 1. Outer cylindrical casing
casing = cq.Workplane("XY").circle(outer_dia / 2.0).extrude(housing_height)

# 2. Inner cavity for cycloid disk:
# Bore radius MUST be cut at pin_ring_dia / 2.0 (the center circle of the pins).
# This ensures the outer half of each pin embeds solidly into the outer casing wall,
# creating a single watertight manifold without disconnected solids or non-manifold edges.
cavity = cq.Workplane("XY").circle(pin_ring_dia / 2.0).extrude(housing_height)
result = casing.cut(cavity)

# 3. Stationary pin rollers arrayed along internal circumference
pins = (
    cq.Workplane("XY")
    .polarArray(pin_ring_dia / 2.0, 0, 360, num_pins)
    .circle(pin_dia / 2.0)
    .extrude(housing_height)
)
result = result.union(pins)

# 4. Mounting holes on outer flange (optional)
# Place mounting holes on PCD > (pin_ring_dia + pin_dia + 6.0) to maintain solid wall thickness
mounting_pcd = outer_dia - 12.0
result = (
    result.faces(">Z").workplane()
    .polarArray(mounting_pcd / 2.0, 0, 360, 6)
    .hole(4.3)
)

# INTERFACE: ring_pins=(0,0,housing_height/2) dir=(0,0,1) type=gear_mesh d=72.0
# INTERFACE: mounting_flange=(0,0,housing_height) dir=(0,0,1) type=face d=100.0
```


