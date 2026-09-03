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
  - For gears, **NEVER** call `.edges().chamfer()` or `.edges().fillet()` across entire top/bottom faces — selecting all edges includes every tiny tooth profile edge and causes OpenCASCADE `StdFail_NotDone: BRep_API: command not done`! Only chamfer the central bore or plain outer circular rim using `.faces('>Z').edges('%CIRCLE').chamfer(...)`, or omit tooth chamfers entirely.
- **INTERNAL RING GEARS & HOUSINGS:**
  - An internal ring gear must have a continuous outer housing: $D_{\text{outer}} \ge D_{\text{pitch}} + 20\text{mm}$ (giving at least $8\text{mm}$ of solid rim beyond tooth roots).
  - Mounting holes must NEVER intersect tooth roots or breach the outer casing wall! Place mounting holes on an **external mounting flange** ($D_{\text{flange}} \ge D_{\text{outer}} + 20\text{mm}$) or ensure hole boundaries have $\ge 3\text{mm}$ solid clearance from both the teeth and outer rim.

## 6. Helical & Spur Gear Modeling Pattern
To create a **gear** (spur or helical) with clean parametric teeth in CadQuery, use multi-slice lofting (`cq.Solid.makeLoft`):
- **Outer Tip Diameter:** $D_{\text{outer}} = D_{\text{pitch}} + 2 \times \text{module}$. Note that the physical bounding box will be $D_{\text{outer}}$, not $D_{\text{pitch}}$!


```python
import cadquery as cq
import math

# Parameters
pitch_dia = 50.0
num_teeth = 18
face_width = 15.0
helix_angle_deg = 20.0  # Helix angle for twisted teeth
bore_dia = 10.0

module = pitch_dia / num_teeth
r_pitch = pitch_dia / 2.0
r_outer = r_pitch + (1.0 * module)
r_root = r_pitch - (1.25 * module)

# Multi-slice helical loft
num_slices = 8
total_twist_rad = math.radians(helix_angle_deg) * (face_width / pitch_dia)
wires = []

for i in range(num_slices + 1):
    z = (i / num_slices) * face_width
    angle_offset = (i / num_slices) * total_twist_rad
    pts = []
    for t in range(num_teeth):
        a_center = (2 * math.pi * t / num_teeth) + angle_offset
        a_half = math.pi / (2 * num_teeth)
        pts.append((r_root * math.cos(a_center - a_half), r_root * math.sin(a_center - a_half)))
        pts.append((r_outer * math.cos(a_center - a_half/2), r_outer * math.sin(a_center - a_half/2)))
        pts.append((r_outer * math.cos(a_center + a_half/2), r_outer * math.sin(a_center + a_half/2)))
        pts.append((r_root * math.cos(a_center + a_half), r_root * math.sin(a_center + a_half)))
    w = cq.Workplane("XY").workplane(offset=z).polyline(pts).close().val()
    wires.append(w)

gear_solid = cq.Solid.makeLoft(wires)
result = cq.Workplane(obj=gear_solid).faces(">Z").workplane().hole(bore_dia)
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
