"""
50 Single-Part Defect Test Cases for ForgeAgent Stress-Test Benchmark.
Covers:
1. Wall Thickness Violations (STRUCT-01)
2. Small Hole & Aspect Ratio Violations (DFM-3D-02, DFM-CNC-01)
3. Bounding Box & Critical Dimensions (SPEC-01, CRIT-01)
4. CadQuery Syntax, Topology & BRep Exceptions (PHYS-01, PHYS-02)
5. Process & Feature Checks (FEAT-01, DFM-3D-01, DFM-CNC-02, DFM-SM-01, DFM-SM-02, FAST-01)
6. Structural & Mating Compliance (STRUCT-02, MATE-01)
"""

from typing import List, Optional
from pydantic import BaseModel
from orchestrator.models import PartSpec, MatingContext


class SinglePartTestCase(BaseModel):
    id: str
    name: str
    category: str
    expected_rule_fail: str
    spec: PartSpec
    defective_code: str
    description: str


def get_50_single_part_cases() -> List[SinglePartTestCase]:
    cases: List[SinglePartTestCase] = []

    # =========================================================================
    # Category 1: Wall Thickness Violations (STRUCT-01) - 8 Cases
    # =========================================================================
    cases.append(SinglePartTestCase(
        id="SP-01",
        name="bracket_thin_wall",
        category="wall_thickness",
        expected_rule_fail="STRUCT-01",
        spec=PartSpec(id="sp_01", name="mounting_bracket", length=40.0, width=30.0, height=10.0, wall_thickness=2.0),
        defective_code="""import cadquery as cq

wall_thickness = 0.8
length = 40.0
width = 30.0
height = 10.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .hole(20.0, depth=height - wall_thickness)
)
""",
        description="Bracket pocket leaves only 0.8mm floor/wall thickness (< 1.5mm required)."
    ))

    cases.append(SinglePartTestCase(
        id="SP-02",
        name="cylinder_thin_wall",
        category="wall_thickness",
        expected_rule_fail="STRUCT-01",
        spec=PartSpec(id="sp_02", name="bush_housing", length=30.0, width=30.0, height=25.0, wall_thickness=2.5),
        defective_code="""import cadquery as cq

outer_dia = 30.0
height = 25.0
wall = 0.9

inner_dia = outer_dia - (2 * wall)
result = (
    cq.Workplane("XY")
    .circle(outer_dia / 2.0)
    .extrude(height)
    .faces(">Z").workplane()
    .circle(inner_dia / 2.0)
    .cutThruAll()
)
""",
        description="Cylindrical bushing with 0.9mm wall thickness (< 1.5mm)."
    ))

    cases.append(SinglePartTestCase(
        id="SP-03",
        name="hollow_tube_shell",
        category="wall_thickness",
        expected_rule_fail="STRUCT-01",
        spec=PartSpec(id="sp_03", name="tube_sleeve", length=25.0, width=25.0, height=30.0, wall_thickness=2.0),
        defective_code="""import cadquery as cq

shell_thickness = 0.7
length = 25.0
width = 25.0
height = 30.0

result = (
    cq.Workplane("XY")
    .rect(length, width)
    .extrude(height)
    .faces(">Z").shell(-shell_thickness)
)
""",
        description="Shelled tube with 0.7mm shell thickness."
    ))

    cases.append(SinglePartTestCase(
        id="SP-04",
        name="casing_thin_wall",
        category="wall_thickness",
        expected_rule_fail="STRUCT-01",
        spec=PartSpec(id="sp_04", name="sensor_casing", length=35.0, width=25.0, height=15.0, wall_thickness=2.0),
        defective_code="""import cadquery as cq

casing_wall = 1.0
length = 35.0
width = 25.0
height = 15.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .rect(length - 2*casing_wall, width - 2*casing_wall)
    .cutBlind(-(height - casing_wall))
)
""",
        description="Rectangular casing with 1.0mm walls and floor."
    ))

    cases.append(SinglePartTestCase(
        id="SP-05",
        name="housing_thin_annulus",
        category="wall_thickness",
        expected_rule_fail="STRUCT-01",
        spec=PartSpec(id="sp_05", name="bearing_housing", geometry_form="annular_flanged_casing", length=40.0, width=40.0, height=20.0, wall_thickness=3.0),
        defective_code="""import cadquery as cq

housing_wall = 0.6
od = 40.0
height = 20.0
bore = od - (2 * housing_wall)

result = (
    cq.Workplane("XY")
    .circle(od / 2.0)
    .extrude(height)
    .faces(">Z").workplane()
    .hole(bore)
)
""",
        description="Bearing housing ring with 0.6mm annular wall."
    ))

    cases.append(SinglePartTestCase(
        id="SP-06",
        name="u_channel_thin_flange",
        category="wall_thickness",
        expected_rule_fail="STRUCT-01",
        spec=PartSpec(id="sp_06", name="u_channel", length=50.0, width=20.0, height=15.0, wall_thickness=2.0),
        defective_code="""import cadquery as cq

wall_t = 0.8
length = 50.0
width = 20.0
height = 15.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .rect(length - 2*wall_t, width)
    .cutBlind(-(height - wall_t))
)
""",
        description="U-channel profile with 0.8mm web thickness."
    ))

    cases.append(SinglePartTestCase(
        id="SP-07",
        name="pocket_thin_floor",
        category="wall_thickness",
        expected_rule_fail="STRUCT-01",
        spec=PartSpec(id="sp_07", name="milled_cavity", manufacturing_process="cnc_machining", length=60.0, width=40.0, height=12.0, wall_thickness=2.5),
        defective_code="""import cadquery as cq

min_wall = 0.75
length = 60.0
width = 40.0
height = 12.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .rect(40.0, 25.0)
    .cutBlind(-(height - min_wall))
)
""",
        description="CNC milled pocket with 0.75mm bottom floor thickness."
    ))

    cases.append(SinglePartTestCase(
        id="SP-08",
        name="ribbed_plate_thin_web",
        category="wall_thickness",
        expected_rule_fail="STRUCT-01",
        spec=PartSpec(id="sp_08", name="ribbed_base", length=50.0, width=50.0, height=10.0, wall_thickness=2.0),
        defective_code="""import cadquery as cq

t_wall = 0.9
length = 50.0
width = 50.0
height = 10.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .rarray(20.0, 20.0, 2, 2)
    .rect(15.0, 15.0)
    .cutBlind(-(height - t_wall))
)
""",
        description="Grid-pocketed plate leaving 0.9mm walls between pockets."
    ))

    # =========================================================================
    # Category 2: Small Hole & Aspect Ratio (DFM-3D-02, DFM-CNC-01) - 8 Cases
    # =========================================================================
    cases.append(SinglePartTestCase(
        id="SP-09",
        name="plate_micro_hole",
        category="hole_diameter",
        expected_rule_fail="DFM-3D-02",
        spec=PartSpec(id="sp_09", name="orifice_plate", length=30.0, width=30.0, height=5.0, hole_diameter=2.5),
        defective_code="""import cadquery as cq

hole_dia = 1.0
length = 30.0
width = 30.0
height = 5.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .hole(hole_dia)
)
""",
        description="3D printed plate with 1.0mm hole (< 2.0mm min printable limit)."
    ))

    cases.append(SinglePartTestCase(
        id="SP-10",
        name="bracket_submini_hole",
        category="hole_diameter",
        expected_rule_fail="DFM-3D-02",
        spec=PartSpec(id="sp_10", name="sensor_mount", length=40.0, width=20.0, height=8.0, hole_diameter=3.0),
        defective_code="""import cadquery as cq

hole_diameter = 1.4
length = 40.0
width = 20.0
height = 8.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .hole(hole_diameter)
)
""",
        description="Mounting bracket with 1.4mm hole (< 2.0mm)."
    ))

    cases.append(SinglePartTestCase(
        id="SP-11",
        name="pin_hole_sub_threshold",
        category="hole_diameter",
        expected_rule_fail="DFM-3D-02",
        spec=PartSpec(id="sp_11", name="locator_block", length=35.0, width=25.0, height=10.0, hole_diameter=2.5),
        defective_code="""import cadquery as cq

pin_hole_dia = 0.8
length = 35.0
width = 25.0
height = 10.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .hole(pin_hole_dia)
)
""",
        description="Locator block with tiny 0.8mm pin hole."
    ))

    cases.append(SinglePartTestCase(
        id="SP-12",
        name="mounting_hole_undersized",
        category="hole_diameter",
        expected_rule_fail="DFM-3D-02",
        spec=PartSpec(id="sp_12", name="terminal_bracket", length=30.0, width=20.0, height=6.0, hole_diameter=2.2),
        defective_code="""import cadquery as cq

mounting_hole_dia = 1.2
length = 30.0
width = 20.0
height = 6.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .hole(mounting_hole_dia)
)
""",
        description="Terminal bracket with 1.2mm mounting hole."
    ))

    cases.append(SinglePartTestCase(
        id="SP-13",
        name="bearing_bore_undersized",
        category="hole_diameter",
        expected_rule_fail="DFM-3D-02",
        spec=PartSpec(id="sp_13", name="mini_bushing", length=20.0, width=20.0, height=12.0, hole_diameter=3.0),
        defective_code="""import cadquery as cq

bore_dia = 1.5
length = 20.0
width = 20.0
height = 12.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .hole(bore_dia)
)
""",
        description="Miniature bushing with 1.5mm center bore."
    ))

    cases.append(SinglePartTestCase(
        id="SP-14",
        name="shaft_hole_pinhole",
        category="hole_diameter",
        expected_rule_fail="DFM-3D-02",
        spec=PartSpec(id="sp_14", name="axle_carrier", length=25.0, width=25.0, height=15.0, hole_diameter=2.5),
        defective_code="""import cadquery as cq

shaft_hole_dia = 1.7
length = 25.0
width = 25.0
height = 15.0

result = (
    cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").workplane()
    .hole(shaft_hole_dia)
)
""",
        description="Axle carrier with 1.7mm bore hole."
    ))

    cases.append(SinglePartTestCase(
        id="SP-15",
        name="cnc_deep_hole_ratio_10",
        category="hole_diameter",
        expected_rule_fail="DFM-CNC-01",
        spec=PartSpec(id="sp_15", name="manifold_block", manufacturing_process="cnc_machining", length=40.0, width=40.0, height=55.0),
        defective_code="""import cadquery as cq

hole_dia = 5.0
depth = 50.0

result = (
    cq.Workplane("XY")
    .box(40.0, 40.0, 55.0)
    .faces(">Z").workplane()
    .hole(hole_dia, depth=depth)
)
""",
        description="CNC machined deep hole with L/D = 50/5 = 10.0 (> 5.0 max)."
    ))

    cases.append(SinglePartTestCase(
        id="SP-16",
        name="cnc_deep_hole_ratio_8",
        category="hole_diameter",
        expected_rule_fail="DFM-CNC-01",
        spec=PartSpec(id="sp_16", name="hydraulic_body", manufacturing_process="cnc_machining", length=30.0, width=30.0, height=40.0),
        defective_code="""import cadquery as cq

hole_dia = 4.0
depth = 32.0

result = (
    cq.Workplane("XY")
    .box(30.0, 30.0, 40.0)
    .faces(">Z").workplane()
    .hole(hole_dia, depth=depth)
)
""",
        description="CNC machined small hole with L/D = 32/4 = 8.0 (> 5.0 max)."
    ))

    # =========================================================================
    # Category 3: Bounding Box & Critical Dimensions (SPEC-01, CRIT-01) - 10 Cases
    # =========================================================================
    cases.append(SinglePartTestCase(
        id="SP-17",
        name="bracket_length_deviates",
        category="bounding_box",
        expected_rule_fail="SPEC-01",
        spec=PartSpec(id="sp_17", name="long_bracket", length=60.0, width=30.0, height=10.0),
        defective_code="""import cadquery as cq

length = 40.0
width = 30.0
height = 10.0

result = cq.Workplane("XY").box(length, width, height)
""",
        description="Length modeled as 40.0mm vs required 60.0mm in spec."
    ))

    cases.append(SinglePartTestCase(
        id="SP-18",
        name="bracket_width_oversized",
        category="bounding_box",
        expected_rule_fail="SPEC-01",
        spec=PartSpec(id="sp_18", name="narrow_plate", length=50.0, width=25.0, height=8.0),
        defective_code="""import cadquery as cq

length = 50.0
width = 45.0
height = 8.0

result = cq.Workplane("XY").box(length, width, height)
""",
        description="Width modeled as 45.0mm vs required 25.0mm."
    ))

    cases.append(SinglePartTestCase(
        id="SP-19",
        name="block_height_mismatch",
        category="bounding_box",
        expected_rule_fail="SPEC-01",
        spec=PartSpec(id="sp_19", name="shim_block", length=40.0, width=40.0, height=5.0),
        defective_code="""import cadquery as cq

length = 40.0
width = 40.0
height = 15.0

result = cq.Workplane("XY").box(length, width, height)
""",
        description="Height modeled as 15.0mm vs required 5.0mm."
    ))

    cases.append(SinglePartTestCase(
        id="SP-20",
        name="shaft_outer_dia_deviates",
        category="bounding_box",
        expected_rule_fail="CRIT-01",
        spec=PartSpec(
            id="sp_20",
            name="drive_shaft",
            part_type="shaft",
            geometry_form="stepped_shaft",
            length=80.0,
            width=20.0,
            height=20.0,
            critical_dimensions={"outer_diameter": 20.0, "length": 80.0}
        ),
        defective_code="""import cadquery as cq

outer_dia = 14.0
length = 80.0

result = cq.Workplane("XY").circle(outer_dia / 2.0).extrude(length)
""",
        description="Shaft diameter is 14.0mm vs critical_dimensions requirement of 20.0mm."
    ))

    cases.append(SinglePartTestCase(
        id="SP-21",
        name="shaft_length_deviates",
        category="bounding_box",
        expected_rule_fail="CRIT-01",
        spec=PartSpec(
            id="sp_21",
            name="pivot_axle",
            part_type="shaft",
            geometry_form="stepped_shaft",
            length=100.0,
            width=15.0,
            height=15.0,
            critical_dimensions={"outer_diameter": 15.0, "length": 100.0}
        ),
        defective_code="""import cadquery as cq

outer_dia = 15.0
total_length = 60.0

result = cq.Workplane("XY").circle(outer_dia / 2.0).extrude(total_length)
""",
        description="Shaft length is 60.0mm vs critical_dimensions requirement of 100.0mm."
    ))

    cases.append(SinglePartTestCase(
        id="SP-22",
        name="bushing_od_mismatch",
        category="bounding_box",
        expected_rule_fail="CRIT-01",
        spec=PartSpec(
            id="sp_22",
            name="sleeve_bushing",
            geometry_form="annular_flanged_casing",
            length=35.0,
            width=35.0,
            height=20.0,
            critical_dimensions={"outer_diameter": 35.0, "bore_diameter": 20.0}
        ),
        defective_code="""import cadquery as cq

od = 28.0
bore_dia = 20.0
height = 20.0

result = (
    cq.Workplane("XY")
    .circle(od / 2.0)
    .extrude(height)
    .faces(">Z").workplane()
    .hole(bore_dia)
)
""",
        description="Bushing outer diameter is 28.0mm vs required 35.0mm."
    ))

    cases.append(SinglePartTestCase(
        id="SP-23",
        name="housing_pitch_dia_deviates",
        category="bounding_box",
        expected_rule_fail="SPEC-01",
        spec=PartSpec(id="sp_23", name="gear_carrier", length=50.0, width=50.0, height=15.0),
        defective_code="""import cadquery as cq

pitch_dia = 35.0
height = 15.0

result = cq.Workplane("XY").circle(pitch_dia / 2.0).extrude(height)
""",
        description="Circular carrier diameter is 35.0mm vs required 50.0mm."
    ))

    cases.append(SinglePartTestCase(
        id="SP-24",
        name="casing_dia_deviates",
        category="bounding_box",
        expected_rule_fail="SPEC-01",
        spec=PartSpec(id="sp_24", name="circular_case", length=60.0, width=60.0, height=20.0),
        defective_code="""import cadquery as cq

casing_dia = 40.0
height = 20.0

result = cq.Workplane("XY").circle(casing_dia / 2.0).extrude(height)
""",
        description="Casing diameter is 40.0mm vs required 60.0mm."
    ))

    cases.append(SinglePartTestCase(
        id="SP-25",
        name="pin_body_length_deviates",
        category="bounding_box",
        expected_rule_fail="CRIT-01",
        spec=PartSpec(
            id="sp_25",
            name="locating_pin",
            part_type="pin",
            geometry_form="stepped_shaft",
            length=35.0,
            width=8.0,
            height=8.0,
            critical_dimensions={"outer_diameter": 8.0, "length": 35.0}
        ),
        defective_code="""import cadquery as cq

od = 8.0
body_length = 20.0

result = cq.Workplane("XY").circle(od / 2.0).extrude(body_length)
""",
        description="Locating pin length is 20.0mm vs required 35.0mm."
    ))

    cases.append(SinglePartTestCase(
        id="SP-26",
        name="plate_total_width_deviates",
        category="bounding_box",
        expected_rule_fail="SPEC-01",
        spec=PartSpec(id="sp_26", name="base_plate", length=50.0, width=50.0, height=10.0),
        defective_code="""import cadquery as cq

total_length = 50.0
total_width = 30.0
height = 10.0

result = cq.Workplane("XY").box(total_length, total_width, height)
""",
        description="Base plate width is 30.0mm vs required 50.0mm."
    ))

    # =========================================================================
    # Category 4: CadQuery Syntax, Topology & BRep Exceptions (PHYS-01, PHYS-02) - 10 Cases
    # =========================================================================
    cases.append(SinglePartTestCase(
        id="SP-27",
        name="fillet_no_edges_selected",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_27", name="filleted_block", length=40.0, width=40.0, height=15.0),
        defective_code="""import cadquery as cq

result = (
    cq.Workplane("XY")
    .box(40.0, 40.0, 15.0)
    .faces(">Z")
    .edges("|X and |Y")  # No edges can be simultaneously parallel to X and parallel to Y!
    .fillet(2.0)
)
""",
        description="Fillet called on an empty edge selection throwing CadQuery ValueError."
    ))

    cases.append(SinglePartTestCase(
        id="SP-28",
        name="chamfer_oversized_radius",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_28", name="chamfered_block", length=20.0, width=20.0, height=10.0),
        defective_code="""import cadquery as cq

# Chamfer of 15.0mm on a 10.0mm tall block causes OpenCascade BRep failure
result = (
    cq.Workplane("XY")
    .box(20.0, 20.0, 10.0)
    .edges()
    .chamfer(15.0)
)
""",
        description="Chamfer radius (15mm) larger than body thickness (10mm) causing BRep exception."
    ))

    cases.append(SinglePartTestCase(
        id="SP-29",
        name="missing_result_variable",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_29", name="unnamed_part", length=40.0, width=30.0, height=10.0),
        defective_code="""import cadquery as cq

# Defines my_model instead of standard result variable
my_model = cq.Workplane("XY").box(40.0, 30.0, 10.0)
""",
        description="Script defines my_model instead of required top-level result variable."
    ))

    cases.append(SinglePartTestCase(
        id="SP-30",
        name="unextruded_2d_sketch",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_30", name="flat_sketch", length=30.0, width=30.0, height=10.0),
        defective_code="""import cadquery as cq

# 2D sketch not extruded into a 3D solid
result = cq.Workplane("XY").rect(30.0, 30.0)
""",
        description="Result contains only 2D sketch wires, zero 3D solid bodies."
    ))

    cases.append(SinglePartTestCase(
        id="SP-31",
        name="zero_volume_subtraction",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_31", name="empty_solid", length=20.0, width=20.0, height=20.0),
        defective_code="""import cadquery as cq

# Completely hollowed out body with 0 volume
result = (
    cq.Workplane("XY")
    .box(20.0, 20.0, 20.0)
    .cut(cq.Workplane("XY").box(30.0, 30.0, 30.0))
)
""",
        description="Cut operation completely deletes the solid, leaving zero volume."
    ))

    cases.append(SinglePartTestCase(
        id="SP-32",
        name="disconnected_multi_body",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_32", name="split_block", length=50.0, width=20.0, height=10.0),
        defective_code="""import cadquery as cq

# Two disconnected solids 50mm apart
b1 = cq.Workplane("XY").center(-30, 0).box(15, 20, 10)
b2 = cq.Workplane("XY").center(30, 0).box(15, 20, 10)
result = b1.union(b2)
""",
        description="Produces two disjoint solid bodies severed into separate pieces."
    ))

    cases.append(SinglePartTestCase(
        id="SP-33",
        name="python_syntax_error",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_33", name="syntax_broken", length=40.0, width=30.0, height=10.0),
        defective_code="""import cadquery as cq

# Unclosed parenthesis and syntax error
result = cq.Workplane("XY").box(40.0, 30.0, 10.0
""",
        description="Python syntax error with unclosed parenthesis."
    ))

    cases.append(SinglePartTestCase(
        id="SP-34",
        name="severing_slot_cut",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_34", name="severed_plate", length=50.0, width=40.0, height=10.0),
        defective_code="""import cadquery as cq

# Cut slot cuts right through the entire middle, bisecting the plate
result = (
    cq.Workplane("XY")
    .box(50.0, 40.0, 10.0)
    .faces(">Z").workplane()
    .rect(10.0, 60.0)
    .cutThruAll()
)
""",
        description="Slot cut severs plate into 2 separate disconnected solid bodies."
    ))

    cases.append(SinglePartTestCase(
        id="SP-35",
        name="invalid_cadquery_method",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_35", name="bad_method", length=30.0, width=30.0, height=10.0),
        defective_code="""import cadquery as cq

result = cq.Workplane("XY").create_cube_solid(30.0, 30.0, 10.0)
""",
        description="Calls non-existent create_cube_solid method throwing AttributeError."
    ))

    cases.append(SinglePartTestCase(
        id="SP-36",
        name="negative_extrude_failure",
        category="syntax_brep",
        expected_rule_fail="PHYS-01",
        spec=PartSpec(id="sp_36", name="zero_extrude", length=30.0, width=30.0, height=10.0),
        defective_code="""import cadquery as cq

# Extruding 0.0mm height
result = cq.Workplane("XY").rect(30.0, 30.0).extrude(0.0)
""",
        description="Extrudes 0.0mm height producing zero volume solid."
    ))

    # =========================================================================
    # Category 5: Process & Feature Checks (FEAT-01, DFM-3D-01, DFM-CNC-02, DFM-SM) - 10 Cases
    # =========================================================================
    cases.append(SinglePartTestCase(
        id="SP-37",
        name="bracket_missing_required_hole",
        category="features_dfm",
        expected_rule_fail="FEAT-01",
        spec=PartSpec(id="sp_37", name="bolt_bracket", length=40.0, width=30.0, height=10.0, hole_diameter=4.3, features=[{"name": "clearance_hole"}]),
        defective_code="""import cadquery as cq

# Bracket modeled as a plain rectangular block with NO hole
result = cq.Workplane("XY").box(40.0, 30.0, 10.0)
""",
        description="Solid completely omits the required clearance hole specified in PartSpec."
    ))

    cases.append(SinglePartTestCase(
        id="SP-38",
        name="overhang_horizontal_cantilever",
        category="features_dfm",
        expected_rule_fail="DFM-3D-01",
        spec=PartSpec(id="sp_38", name="t_bracket", manufacturing_process="3d_printing", verification_depth="manufacturing", length=40.0, width=40.0, height=30.0),
        defective_code="""import cadquery as cq

# T-bracket with large 90 degree downward-facing overhang without chamfer/fillet
base = cq.Workplane("XY").box(15.0, 15.0, 30.0)
flange = cq.Workplane("XY").center(0, 0).workplane(offset=25.0).box(40.0, 40.0, 5.0)
result = base.union(flange)
""",
        description="90° horizontal cantilever overhang requiring support structures."
    ))

    cases.append(SinglePartTestCase(
        id="SP-39",
        name="overhang_steep_cone",
        category="features_dfm",
        expected_rule_fail="DFM-3D-01",
        spec=PartSpec(id="sp_39", name="inverted_funnel", manufacturing_process="3d_printing", verification_depth="manufacturing", length=40.0, width=40.0, height=25.0),
        defective_code="""import cadquery as cq

# Cone with 65° overhang angle (> 45° limit)
result = (
    cq.Workplane("XY")
    .circle(5.0)
    .workplane(offset=25.0)
    .circle(20.0)
    .loft(combine=True)
)
""",
        description="Inverted cone loft with 65° overhang face exceeding 45°."
    ))

    cases.append(SinglePartTestCase(
        id="SP-40",
        name="cnc_sharp_internal_corner",
        category="features_dfm",
        expected_rule_fail="DFM-CNC-02",
        spec=PartSpec(id="sp_40", name="milled_pocket", manufacturing_process="cnc_machining", verification_depth="manufacturing", length=50.0, width=40.0, height=20.0),
        defective_code="""import cadquery as cq

# Pocket with perfectly sharp 90° internal corners (impossible with rotating endmill)
result = (
    cq.Workplane("XY")
    .box(50.0, 40.0, 20.0)
    .faces(">Z").workplane()
    .rect(30.0, 20.0)
    .cutBlind(-10.0)
)
""",
        description="CNC milled pocket with sharp 90° inside corners (requires corner fillet >= 1.5mm)."
    ))

    cases.append(SinglePartTestCase(
        id="SP-41",
        name="cnc_sharp_cavity_step",
        category="features_dfm",
        expected_rule_fail="DFM-CNC-02",
        spec=PartSpec(id="sp_41", name="step_pocket", manufacturing_process="cnc_machining", verification_depth="manufacturing", length=60.0, width=40.0, height=25.0),
        defective_code="""import cadquery as cq

result = (
    cq.Workplane("XY")
    .box(60.0, 40.0, 25.0)
    .faces(">Z").workplane()
    .rect(40.0, 25.0)
    .cutBlind(-15.0)
)
""",
        description="Deep CNC stepped cavity with zero corner radius."
    ))

    cases.append(SinglePartTestCase(
        id="SP-42",
        name="sheet_metal_thick_gauge",
        category="features_dfm",
        expected_rule_fail="DFM-SM-01",
        spec=PartSpec(id="sp_42", name="thick_plate", manufacturing_process="sheet_metal", verification_depth="manufacturing", length=60.0, width=40.0, height=12.0),
        defective_code="""import cadquery as cq

# 12mm thick block declared as sheet metal (> 6.0mm standard press brake gauge)
result = cq.Workplane("XY").box(60.0, 40.0, 12.0)
""",
        description="12mm thickness exceeds max 6.0mm sheet metal gauge limit."
    ))

    cases.append(SinglePartTestCase(
        id="SP-43",
        name="sheet_metal_laser_hole_small",
        category="features_dfm",
        expected_rule_fail="DFM-SM-02",
        spec=PartSpec(id="sp_43", name="laser_bracket", manufacturing_process="sheet_metal", verification_depth="manufacturing", length=50.0, width=30.0, height=4.0),
        defective_code="""import cadquery as cq

# Gauge = 4.0mm, but hole diameter = 2.0mm (< gauge thickness t)
result = (
    cq.Workplane("XY")
    .box(50.0, 30.0, 4.0)
    .faces(">Z").workplane()
    .hole(2.0)
)
""",
        description="Sheet metal laser-cut hole diameter 2.0mm is smaller than sheet thickness 4.0mm."
    ))

    cases.append(SinglePartTestCase(
        id="SP-44",
        name="sheet_metal_sub_thickness_hole",
        category="features_dfm",
        expected_rule_fail="DFM-SM-02",
        spec=PartSpec(id="sp_44", name="chassis_tab", manufacturing_process="sheet_metal", verification_depth="manufacturing", length=40.0, width=25.0, height=3.0),
        defective_code="""import cadquery as cq

# Gauge = 3.0mm, but hole diameter = 1.5mm (< 3.0mm)
result = (
    cq.Workplane("XY")
    .box(40.0, 25.0, 3.0)
    .faces(">Z").workplane()
    .hole(1.5)
)
""",
        description="Laser pierce hole diameter (1.5mm) is less than sheet thickness (3.0mm)."
    ))

    cases.append(SinglePartTestCase(
        id="SP-45",
        name="insufficient_feature_count",
        category="features_dfm",
        expected_rule_fail="FEAT-01",
        spec=PartSpec(id="sp_45", name="detailed_plate", length=50.0, width=50.0, height=10.0, features=[{"name": "hole_1"}, {"name": "hole_2"}]),
        defective_code="""import cadquery as cq

# Plain box with no features
result = cq.Workplane("XY").box(50.0, 50.0, 10.0)
""",
        description="Missing all declared sub-features on detailed plate."
    ))

    cases.append(SinglePartTestCase(
        id="SP-46",
        name="fastener_clearance_tight",
        category="features_dfm",
        expected_rule_fail="FAST-01",
        spec=PartSpec(id="sp_46", name="m4_mount", length=30.0, width=20.0, height=8.0, hole_diameter=4.3, verification_depth="assembly_ready"),
        defective_code="""import cadquery as cq

# Clearance hole for M4 bolt modeled at exact 4.0mm nominal (requires >= 4.3mm clearance)
result = (
    cq.Workplane("XY")
    .box(30.0, 20.0, 8.0)
    .faces(">Z").workplane()
    .hole(4.0)
)
""",
        description="ISO fastener clearance hole is 4.0mm (tight/zero clearance for M4 bolt)."
    ))

    # =========================================================================
    # Category 6: Structural & Mating Compliance (STRUCT-02, MATE-01) - 4 Cases
    # =========================================================================
    cases.append(SinglePartTestCase(
        id="SP-47",
        name="slender_cantilever_beam",
        category="slenderness",
        expected_rule_fail="STRUCT-02",
        spec=PartSpec(id="sp_47", name="support_beam", part_type="bracket", length=120.0, width=15.0, height=3.0),
        defective_code="""import cadquery as cq

# Beam aspect ratio L/t = 120 / 3 = 40.0 (> 20.0 limit for non-shaft parts)
result = cq.Workplane("XY").box(120.0, 15.0, 3.0)
""",
        description="Slender non-shaft beam with L/t = 40.0 exceeding max 20.0 limit."
    ))

    cases.append(SinglePartTestCase(
        id="SP-48",
        name="slender_thin_strip",
        category="slenderness",
        expected_rule_fail="STRUCT-02",
        spec=PartSpec(id="sp_48", name="guide_strip", part_type="bracket", length=80.0, width=10.0, height=2.0),
        defective_code="""import cadquery as cq

# Strip aspect ratio L/t = 80 / 2 = 40.0
result = cq.Workplane("XY").box(80.0, 10.0, 2.0)
""",
        description="Guide strip with extreme slenderness ratio of 40."
    ))

    cases.append(SinglePartTestCase(
        id="SP-49",
        name="mating_bore_missing",
        category="mating",
        expected_rule_fail="MATE-01",
        spec=PartSpec(
            id="sp_49",
            name="bearing_block",
            length=40.0,
            width=40.0,
            height=20.0,
            mates=[MatingContext(partner_id="shaft", mate_type="hole_shaft", my_feature_diameter=12.0)]
        ),
        defective_code="""import cadquery as cq

# Declares mate_type='hole_shaft' with diameter 12.0mm, but BRep solid has NO hole!
result = cq.Workplane("XY").box(40.0, 40.0, 20.0)
""",
        description="Block declares a 12.0mm mating bore but geometry is solid with 0 holes."
    ))

    cases.append(SinglePartTestCase(
        id="SP-50",
        name="mating_bore_wrong_size",
        category="mating",
        expected_rule_fail="MATE-01",
        spec=PartSpec(
            id="sp_50",
            name="pillow_block",
            length=50.0,
            width=30.0,
            height=25.0,
            mates=[MatingContext(partner_id="shaft", mate_type="hole_shaft", my_feature_diameter=16.0)]
        ),
        defective_code="""import cadquery as cq

# Hole is 10.0mm instead of declared 16.0mm
result = (
    cq.Workplane("XY")
    .box(50.0, 30.0, 25.0)
    .faces(">Z").workplane()
    .hole(10.0)
)
""",
        description="Hole diameter is 10.0mm vs declared mating requirement of 16.0mm."
    ))

    for c in cases:
        if c.expected_rule_fail in ("STRUCT-01", "DFM-3D-01", "DFM-3D-02", "DFM-CNC-01", "DFM-CNC-02", "DFM-SM-01", "DFM-SM-02"):
            c.spec.verification_depth = "manufacturing"
        elif c.expected_rule_fail in ("FAST-01", "MATE-01", "CRIT-01", "STRUCT-02"):
            c.spec.verification_depth = "assembly_ready"

    return cases
