"""
25 Multi-Part Assembly Defect Test Cases for ForgeAgent Stress-Test Benchmark.

Categories:
1. Axial Stacking / Co-location Collisions (ASY-01 to ASY-06)
2. Dimensional Sizing Mismatches (ASY-07 to ASY-12)
3. Clearance Fit Violations (ASY-13 to ASY-17)
4. InterfacePort Misalignments (ASY-18 to ASY-21)
5. Center-Distance / Gear Meshing Clash (ASY-22 to ASY-25)
"""

from typing import List, Dict, Optional
from pydantic import BaseModel
from orchestrator.models import (
    AssemblyGraph,
    PartSpec,
    MatingContext,
    InterfacePort,
    JointDef,
)


class AssemblyTestCase(BaseModel):
    id: str
    name: str
    category: str
    expected_fault_type: str  # "graph_patch", "tolerance_patch", "geometry", "positioning"
    graph: AssemblyGraph
    parts_code: Dict[str, str]
    interfaces: Optional[Dict[str, Dict[str, InterfacePort]]] = None
    description: str


def get_25_assembly_cases() -> List[AssemblyTestCase]:
    cases: List[AssemblyTestCase] = []

    # =========================================================================
    # Category 1: Axial Stacking / Co-location Collisions (ASY-01 to ASY-06)
    # Tested with explicit overlapping axial_offsets so AssemblyRepairAgent patches the graph.
    # =========================================================================
    cases.append(AssemblyTestCase(
        id="ASY-01",
        name="coaxial_discs_no_offset",
        category="axial_stacking",
        expected_fault_type="graph_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="disc_a", name="disc_a", part_type="base", height=10.0, length=40.0, width=40.0),
                PartSpec(id="disc_b", name="disc_b", height=10.0, length=36.0, width=36.0,
                         mates=[MatingContext(partner_id="disc_a", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"disc_b": 2.0}}
        ),
        parts_code={
            "disc_a": """import cadquery as cq
result = cq.Workplane("XY").circle(20.0).extrude(10.0)
""",
            "disc_b": """import cadquery as cq
result = cq.Workplane("XY").circle(18.0).extrude(10.0)
"""
        },
        description="Two solid discs with only 2.0mm axial offset, causing 8.0mm severe axial overlap."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-02",
        name="stacked_plates_clash",
        category="axial_stacking",
        expected_fault_type="graph_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="plate_bottom", name="plate_bottom", part_type="base", length=50.0, width=50.0, height=12.0),
                PartSpec(id="plate_top", name="plate_top", length=40.0, width=40.0, height=12.0,
                         mates=[MatingContext(partner_id="plate_bottom", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"plate_top": 3.0}}
        ),
        parts_code={
            "plate_bottom": """import cadquery as cq
result = cq.Workplane("XY").box(50.0, 50.0, 12.0)
""",
            "plate_top": """import cadquery as cq
result = cq.Workplane("XY").box(40.0, 40.0, 12.0)
"""
        },
        description="Two rectangular plates with 3mm offset vs 12mm thickness (9mm axial clash)."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-03",
        name="coaxial_spacers_collision",
        category="axial_stacking",
        expected_fault_type="graph_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="spacer_1", name="spacer_1", part_type="base", height=15.0, length=20.0, width=20.0),
                PartSpec(id="spacer_2", name="spacer_2", height=15.0, length=20.0, width=20.0,
                         mates=[MatingContext(partner_id="spacer_1", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"spacer_2": 4.0}}
        ),
        parts_code={
            "spacer_1": """import cadquery as cq
result = cq.Workplane("XY").circle(10.0).circle(5.0).extrude(15.0)
""",
            "spacer_2": """import cadquery as cq
result = cq.Workplane("XY").circle(10.0).circle(5.0).extrude(15.0)
"""
        },
        description="Two spacers with 4mm offset vs 15mm height (11mm axial overlap)."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-04",
        name="gear_pulley_colocated",
        category="axial_stacking",
        expected_fault_type="graph_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="spur_gear", name="spur_gear", part_type="base", height=8.0, length=30.0, width=30.0),
                PartSpec(id="v_pulley", name="v_pulley", height=12.0, length=32.0, width=32.0,
                         mates=[MatingContext(partner_id="spur_gear", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"v_pulley": 2.0}}
        ),
        parts_code={
            "spur_gear": """import cadquery as cq
result = cq.Workplane("XY").circle(15.0).extrude(8.0)
""",
            "v_pulley": """import cadquery as cq
result = cq.Workplane("XY").circle(16.0).extrude(12.0)
"""
        },
        description="Gear (8mm) and pulley (12mm) placed with only 2mm offset."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-05",
        name="bearing_collar_overlap",
        category="axial_stacking",
        expected_fault_type="graph_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="bearing_inner", name="bearing_inner", part_type="base", height=9.0, length=18.0, width=18.0),
                PartSpec(id="retaining_collar", name="retaining_collar", height=8.0, length=22.0, width=22.0,
                         mates=[MatingContext(partner_id="bearing_inner", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"retaining_collar": 3.0}}
        ),
        parts_code={
            "bearing_inner": """import cadquery as cq
result = cq.Workplane("XY").circle(9.0).circle(6.0).extrude(9.0)
""",
            "retaining_collar": """import cadquery as cq
result = cq.Workplane("XY").circle(11.0).circle(6.0).extrude(8.0)
"""
        },
        description="Collar offset by 3mm penetrating 9mm bearing inner ring."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-06",
        name="dual_bracket_overlap",
        category="axial_stacking",
        expected_fault_type="graph_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="bracket_left", name="bracket_left", part_type="base", length=30.0, width=20.0, height=25.0),
                PartSpec(id="bracket_right", name="bracket_right", length=30.0, width=20.0, height=25.0,
                         mates=[MatingContext(partner_id="bracket_left", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"bracket_right": 5.0}}
        ),
        parts_code={
            "bracket_left": """import cadquery as cq
result = cq.Workplane("XY").box(30.0, 20.0, 25.0)
""",
            "bracket_right": """import cadquery as cq
result = cq.Workplane("XY").box(30.0, 20.0, 25.0)
"""
        },
        description="Bracket flanges with 5mm offset vs 25mm height."
    ))

    # =========================================================================
    # Category 2: Dimensional Sizing Mismatches (ASY-07 to ASY-12)
    # Shaft inserted into hole, but shaft outer diameter exceeds hole inner diameter.
    # =========================================================================
    cases.append(AssemblyTestCase(
        id="ASY-07",
        name="shaft_oversized_for_hole",
        category="dimensional_mismatch",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="bushing_block", name="bushing_block", part_type="housing", length=40.0, width=40.0, height=20.0, hole_diameter=10.0),
                PartSpec(id="pin_shaft", name="pin_shaft", length=35.0, width=12.0, height=12.0,
                         mates=[MatingContext(partner_id="bushing_block", mate_type="shaft_hole")])
            ]
        ),
        parts_code={
            "bushing_block": """import cadquery as cq
result = cq.Workplane("XY").box(40.0, 40.0, 20.0).faces(">Z").workplane().hole(10.0)
""",
            "pin_shaft": """import cadquery as cq
result = cq.Workplane("XY").circle(6.0).extrude(35.0)
"""
        },
        interfaces={
            "bushing_block": {"bore": InterfacePort(name="bore", mate_key="shaft", position=(0,0,10), direction=(0,0,1), feature_type="hole", diameter=10.0)},
            "pin_shaft": {"shaft": InterfacePort(name="shaft", mate_key="bore", position=(0,0,10), direction=(0,0,1), feature_type="shaft", diameter=12.0)}
        },
        description="Shaft diameter 12mm inserted into 10mm hole (2mm diametral interference = 345 mm³ overlap)."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-08",
        name="dowel_pin_oversized",
        category="dimensional_mismatch",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="locating_plate", name="locating_plate", part_type="housing", length=50.0, width=30.0, height=10.0, hole_diameter=5.0),
                PartSpec(id="dowel_pin", name="dowel_pin", length=20.0, width=6.0, height=6.0,
                         mates=[MatingContext(partner_id="locating_plate", mate_type="shaft_hole")])
            ]
        ),
        parts_code={
            "locating_plate": """import cadquery as cq
result = cq.Workplane("XY").box(50.0, 30.0, 10.0).faces(">Z").workplane().hole(5.0)
""",
            "dowel_pin": """import cadquery as cq
result = cq.Workplane("XY").circle(3.0).extrude(20.0)
"""
        },
        interfaces={
            "locating_plate": {"hole": InterfacePort(name="hole", mate_key="pin", position=(0,0,5), direction=(0,0,1), feature_type="hole", diameter=5.0)},
            "dowel_pin": {"pin": InterfacePort(name="pin", mate_key="hole", position=(0,0,5), direction=(0,0,1), feature_type="shaft", diameter=6.0)}
        },
        description="Dowel pin 6mm OD into 5mm hole (1mm diametral collision)."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-09",
        name="rectangular_key_oversized",
        category="dimensional_mismatch",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="hub", name="hub", part_type="housing", length=30.0, width=30.0, height=20.0),
                PartSpec(id="drive_key", name="drive_key", length=15.0, width=8.0, height=8.0,
                         mates=[MatingContext(partner_id="hub", mate_type="slot_tab")])
            ]
        ),
        parts_code={
            "hub": """import cadquery as cq
result = (
    cq.Workplane("XY").circle(15.0).extrude(20.0)
    .faces(">Z").workplane().hole(10.0)
    .faces(">Z").workplane().rect(6.0, 3.0).cutThruAll()
)
""",
            "drive_key": """import cadquery as cq
result = cq.Workplane("XY").box(8.0, 8.0, 15.0)
"""
        },
        interfaces={
            "hub": {"keyway": InterfacePort(name="keyway", mate_key="key", position=(0,0,10), direction=(0,0,1), feature_type="hole")},
            "drive_key": {"key": InterfacePort(name="key", mate_key="keyway", position=(0,0,10), direction=(0,0,1), feature_type="shaft")}
        },
        description="Key is 8x8mm but keyway slot is only 6x3mm."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-10",
        name="flanged_bushing_outer_body_clash",
        category="dimensional_mismatch",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="housing", name="housing", part_type="housing", length=40.0, width=40.0, height=25.0, hole_diameter=14.0),
                PartSpec(id="bushing", name="bushing", length=16.0, width=16.0, height=20.0,
                         mates=[MatingContext(partner_id="housing", mate_type="shaft_hole")])
            ]
        ),
        parts_code={
            "housing": """import cadquery as cq
result = cq.Workplane("XY").box(40.0, 40.0, 25.0).faces(">Z").workplane().hole(14.0)
""",
            "bushing": """import cadquery as cq
result = cq.Workplane("XY").circle(8.0).circle(5.0).extrude(20.0)
"""
        },
        interfaces={
            "housing": {"bore": InterfacePort(name="bore", mate_key="bushing_body", position=(0,0,12), direction=(0,0,1), feature_type="hole", diameter=14.0)},
            "bushing": {"bushing_body": InterfacePort(name="bushing_body", mate_key="bore", position=(0,0,12), direction=(0,0,1), feature_type="shaft", diameter=16.0)}
        },
        description="Bushing outer barrel (16mm OD) clashes with 14mm housing bore."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-11",
        name="stepped_shaft_step_oversized",
        category="dimensional_mismatch",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="bearing_block", name="bearing_block", part_type="housing", length=50.0, width=40.0, height=30.0, hole_diameter=20.0),
                PartSpec(id="stepped_shaft", name="stepped_shaft", length=40.0, width=22.0, height=22.0,
                         mates=[MatingContext(partner_id="bearing_block", mate_type="shaft_hole")])
            ]
        ),
        parts_code={
            "bearing_block": """import cadquery as cq
result = cq.Workplane("XY").box(50.0, 40.0, 30.0).faces(">Z").workplane().hole(20.0)
""",
            "stepped_shaft": """import cadquery as cq
result = cq.Workplane("XY").circle(11.0).extrude(40.0)
"""
        },
        interfaces={
            "bearing_block": {"bore": InterfacePort(name="bore", mate_key="shaft", position=(0,0,15), direction=(0,0,1), feature_type="hole", diameter=20.0)},
            "stepped_shaft": {"shaft": InterfacePort(name="shaft", mate_key="bore", position=(0,0,15), direction=(0,0,1), feature_type="shaft", diameter=22.0)}
        },
        description="Shaft step (22mm OD) intersects 20mm housing bore."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-12",
        name="pin_pressfit_excessive_interference",
        category="dimensional_mismatch",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="link_arm", name="link_arm", part_type="housing", length=60.0, width=20.0, height=10.0, hole_diameter=8.0),
                PartSpec(id="pivot_pin", name="pivot_pin", length=25.0, width=9.2, height=9.2,
                         mates=[MatingContext(partner_id="link_arm", mate_type="press_fit")])
            ]
        ),
        parts_code={
            "link_arm": """import cadquery as cq
result = cq.Workplane("XY").box(60.0, 20.0, 10.0).faces(">Z").workplane().hole(8.0)
""",
            "pivot_pin": """import cadquery as cq
result = cq.Workplane("XY").circle(4.6).extrude(25.0)
"""
        },
        interfaces={
            "link_arm": {"hole": InterfacePort(name="hole", mate_key="pin", position=(0,0,5), direction=(0,0,1), feature_type="hole", diameter=8.0)},
            "pivot_pin": {"pin": InterfacePort(name="pin", mate_key="hole", position=(0,0,5), direction=(0,0,1), feature_type="shaft", diameter=9.2)}
        },
        description="Pivot pin 9.2mm OD into 8.0mm hole (1.2mm interference >> allowable)."
    ))

    # =========================================================================
    # Category 3: Clearance Fit Violations (ASY-13 to ASY-17)
    # Tested via InterfacePort diameters or verify_assembly fit clearance checks.
    # =========================================================================
    cases.append(AssemblyTestCase(
        id="ASY-13",
        name="shaft_hole_excessive_play",
        category="clearance_fit",
        expected_fault_type="tolerance_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="guide_block", name="guide_block", part_type="housing", length=30.0, width=30.0, height=15.0, hole_diameter=10.0),
                PartSpec(id="guide_rod", name="guide_rod", length=40.0, width=8.5, height=8.5,
                         mates=[MatingContext(partner_id="guide_block", mate_type="shaft_hole", my_feature_diameter=8.5, clearance_mm=1.5)])
            ]
        ),
        parts_code={
            "guide_block": """import cadquery as cq
result = cq.Workplane("XY").box(30.0, 30.0, 15.0).faces(">Z").workplane().hole(10.0)
""",
            "guide_rod": """import cadquery as cq
result = cq.Workplane("XY").circle(4.25).extrude(40.0)
"""
        },
        interfaces={
            "guide_block": {"bore": InterfacePort(name="bore", mate_key="rod", feature_type="hole", diameter=10.0, position=(0,0,7.5), direction=(0,0,1))},
            "guide_rod": {"rod": InterfacePort(name="rod", mate_key="bore", feature_type="shaft", diameter=8.5, position=(0,0,7.5), direction=(0,0,1))}
        },
        description="1.5mm diametral clearance (0.75mm radial > 0.65mm max limit for guide rod)."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-14",
        name="extreme_slop_hole_shaft",
        category="clearance_fit",
        expected_fault_type="tolerance_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="support_yoke", name="support_yoke", part_type="housing", length=40.0, width=40.0, height=20.0, hole_diameter=12.0),
                PartSpec(id="cross_pin", name="cross_pin", length=30.0, width=8.0, height=8.0,
                         mates=[MatingContext(partner_id="support_yoke", mate_type="shaft_hole", my_feature_diameter=8.0, clearance_mm=4.0)])
            ]
        ),
        parts_code={
            "support_yoke": """import cadquery as cq
result = cq.Workplane("XY").box(40.0, 40.0, 20.0).faces(">Z").workplane().hole(12.0)
""",
            "cross_pin": """import cadquery as cq
result = cq.Workplane("XY").circle(4.0).extrude(30.0)
"""
        },
        interfaces={
            "support_yoke": {"bore": InterfacePort(name="bore", mate_key="pin", feature_type="hole", diameter=12.0, position=(0,0,10), direction=(0,0,1))},
            "cross_pin": {"pin": InterfacePort(name="pin", mate_key="bore", feature_type="shaft", diameter=8.0, position=(0,0,10), direction=(0,0,1))}
        },
        description="Cross pin 8.0mm in 12.0mm bore (4mm slop)."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-15",
        name="zero_clearance_sliding_fit",
        category="clearance_fit",
        expected_fault_type="tolerance_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="sleeve", name="sleeve", part_type="housing", height=20.0, length=20.0, width=20.0, hole_diameter=10.0),
                PartSpec(id="slider_rod", name="slider_rod", length=35.0, width=10.0, height=10.0,
                         mates=[MatingContext(partner_id="sleeve", mate_type="shaft_hole", my_feature_diameter=10.0, clearance_mm=0.0)])
            ]
        ),
        parts_code={
            "sleeve": """import cadquery as cq
result = cq.Workplane("XY").circle(10.0).circle(5.0).extrude(20.0)
""",
            "slider_rod": """import cadquery as cq
result = cq.Workplane("XY").circle(5.0).extrude(35.0)
"""
        },
        interfaces={
            "sleeve": {"bore": InterfacePort(name="bore", mate_key="rod", feature_type="hole", diameter=10.0, position=(0,0,10), direction=(0,0,1))},
            "slider_rod": {"rod": InterfacePort(name="rod", mate_key="bore", feature_type="shaft", diameter=10.0, position=(0,0,10), direction=(0,0,1))}
        },
        description="10.0mm rod in 10.0mm bore (zero clearance sliding fit causes binding)."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-16",
        name="bolt_hole_no_clearance",
        category="clearance_fit",
        expected_fault_type="tolerance_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="base_flange", name="base_flange", part_type="housing", length=50.0, width=50.0, height=10.0, hole_diameter=4.0),
                PartSpec(id="m4_bolt", name="m4_bolt", length=20.0, width=7.0, height=7.0,
                         mates=[MatingContext(partner_id="base_flange", mate_type="shaft_hole", my_feature_diameter=4.0, clearance_mm=0.0)])
            ]
        ),
        parts_code={
            "base_flange": """import cadquery as cq
result = cq.Workplane("XY").box(50.0, 50.0, 10.0).faces(">Z").workplane().hole(4.0)
""",
            "m4_bolt": """import cadquery as cq
result = cq.Workplane("XY").circle(2.0).extrude(17.0)
"""
        },
        interfaces={
            "base_flange": {"hole": InterfacePort(name="hole", mate_key="bolt", feature_type="hole", diameter=4.0, position=(0,0,5), direction=(0,0,1))},
            "m4_bolt": {"bolt": InterfacePort(name="bolt", mate_key="hole", feature_type="shaft", diameter=4.0, position=(0,0,5), direction=(0,0,1))}
        },
        description="M4 clearance hole drilled at exactly 4.0mm instead of 4.5mm."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-17",
        name="loose_bearing_pocket",
        category="clearance_fit",
        expected_fault_type="tolerance_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="gearbox_wall", name="gearbox_wall", part_type="housing", length=60.0, width=60.0, height=15.0, hole_diameter=25.0),
                PartSpec(id="ball_bearing", name="ball_bearing", length=22.0, width=22.0, height=8.0,
                         mates=[MatingContext(partner_id="gearbox_wall", mate_type="shaft_hole", my_feature_diameter=22.0, clearance_mm=3.0)])
            ]
        ),
        parts_code={
            "gearbox_wall": """import cadquery as cq
result = cq.Workplane("XY").box(60.0, 60.0, 15.0).faces(">Z").workplane().hole(25.0)
""",
            "ball_bearing": """import cadquery as cq
result = cq.Workplane("XY").circle(11.0).circle(5.0).extrude(8.0)
"""
        },
        interfaces={
            "gearbox_wall": {"pocket": InterfacePort(name="pocket", mate_key="bearing", feature_type="hole", diameter=25.0, position=(0,0,7.5), direction=(0,0,1))},
            "ball_bearing": {"bearing": InterfacePort(name="bearing", mate_key="pocket", feature_type="shaft", diameter=22.0, position=(0,0,7.5), direction=(0,0,1))}
        },
        description="Bearing pocket is 25mm for 22mm bearing OD (3mm loose pocket)."
    ))

    # =========================================================================
    # Category 4: InterfacePort Misalignments (ASY-18 to ASY-21)
    # Tested with conflicting port directions / offsets.
    # =========================================================================
    cases.append(AssemblyTestCase(
        id="ASY-18",
        name="perpendicular_normal_vector_clash",
        category="port_misalignment",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="mounting_plate", name="mounting_plate", part_type="base", length=50.0, width=40.0, height=10.0),
                PartSpec(id="angle_bracket", name="angle_bracket", length=30.0, width=30.0, height=30.0,
                         mates=[MatingContext(partner_id="mounting_plate", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"angle_bracket": 5.0}}
        ),
        parts_code={
            "mounting_plate": """import cadquery as cq
result = cq.Workplane("XY").box(50.0, 40.0, 10.0)
""",
            "angle_bracket": """import cadquery as cq
result = cq.Workplane("XY").box(30.0, 30.0, 30.0)
"""
        },
        interfaces={
            "mounting_plate": {"top_face": InterfacePort(name="top_face", feature_type="face", position=(0,0,5), direction=(0,0,1))},
            "angle_bracket": {"side_flange": InterfacePort(name="side_flange", feature_type="face", position=(0,0,0), direction=(1,0,0))}
        },
        description="Port normals are perpendicular ((0,0,1) vs (1,0,0)), with 5mm axial offset causing collision."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-19",
        name="inverted_mating_normals",
        category="port_misalignment",
        expected_fault_type="graph_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="lower_half", name="lower_half", part_type="base", length=40.0, width=40.0, height=15.0),
                PartSpec(id="upper_half", name="upper_half", length=40.0, width=40.0, height=15.0,
                         mates=[MatingContext(partner_id="lower_half", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"upper_half": 5.0}}
        ),
        parts_code={
            "lower_half": """import cadquery as cq
result = cq.Workplane("XY").box(40.0, 40.0, 15.0)
""",
            "upper_half": """import cadquery as cq
result = cq.Workplane("XY").box(40.0, 40.0, 15.0)
"""
        },
        interfaces={
            "lower_half": {"split_plane": InterfacePort(name="split_plane", feature_type="face", position=(0,0,7.5), direction=(0,0,1))},
            "upper_half": {"split_plane": InterfacePort(name="split_plane", feature_type="face", position=(0,0,7.5), direction=(0,0,1))}
        },
        description="Both ports have outward normal +Z causing overlap when offset is only 5mm."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-20",
        name="eccentric_port_position_offset",
        category="port_misalignment",
        expected_fault_type="graph_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="base_chassis", name="base_chassis", part_type="base", length=60.0, width=60.0, height=10.0),
                PartSpec(id="sensor_boss", name="sensor_boss", length=20.0, width=20.0, height=10.0,
                         mates=[MatingContext(partner_id="base_chassis", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"sensor_boss": 3.0}}
        ),
        parts_code={
            "base_chassis": """import cadquery as cq
result = cq.Workplane("XY").box(60.0, 60.0, 10.0)
""",
            "sensor_boss": """import cadquery as cq
result = cq.Workplane("XY").box(20.0, 20.0, 10.0)
"""
        },
        interfaces={
            "base_chassis": {"mount_pad": InterfacePort(name="mount_pad", feature_type="face", position=(15.0, 10.0, 5.0), direction=(0,0,1))},
            "sensor_boss": {"bottom": InterfacePort(name="bottom", feature_type="face", position=(-10.0, -10.0, -5.0), direction=(0,0,-1))}
        },
        description="Sensor boss port position offset with 3mm axial overlap."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-21",
        name="bolt_circle_pitch_mismatch",
        category="port_misalignment",
        expected_fault_type="graph_patch",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="flange_pipe", name="flange_pipe", part_type="base", length=60.0, width=60.0, height=10.0),
                PartSpec(id="cover_lid", name="cover_lid", length=60.0, width=60.0, height=8.0,
                         mates=[MatingContext(partner_id="flange_pipe", mate_type="face_face")])
            ],
            shared_parameters={"axial_offsets": {"cover_lid": 2.0}}
        ),
        parts_code={
            "flange_pipe": """import cadquery as cq
result = (
    cq.Workplane("XY").circle(30.0).extrude(10.0)
    .faces(">Z").workplane().circle(15.0).cutThruAll()
    .faces(">Z").workplane().polarArray(22.0, 0, 360, 4).hole(4.0)
)
""",
            "cover_lid": """import cadquery as cq
result = (
    cq.Workplane("XY").circle(30.0).extrude(8.0)
    .faces(">Z").workplane().polarArray(26.0, 0, 360, 4).hole(4.0)
)
"""
        },
        description="Bolt circles differ (PCD 44mm vs 52mm) with 2mm axial overlap."
    ))

    # =========================================================================
    # Category 5: Center-Distance / Gear Meshing Clash (ASY-22 to ASY-25)
    # Severe body overlap due to undersized center distance.
    # =========================================================================
    cases.append(AssemblyTestCase(
        id="ASY-22",
        name="spur_gear_center_distance_clash",
        category="gear_mesh",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="gear_driver", name="gear_driver", part_type="base", length=40.0, width=40.0, height=10.0),
                PartSpec(id="gear_driven", name="gear_driven", length=60.0, width=60.0, height=10.0,
                         mates=[MatingContext(partner_id="gear_driver", mate_type="gear_mesh")])
            ],
            shared_parameters={"center_to_center_distance": 38.0}
        ),
        parts_code={
            "gear_driver": """import cadquery as cq
result = cq.Workplane("XY").circle(20.0).extrude(10.0)
""",
            "gear_driven": """import cadquery as cq
result = cq.Workplane("XY").circle(30.0).extrude(10.0)
"""
        },
        interfaces={
            "gear_driver": {"pitch": InterfacePort(name="pitch", feature_type="gear_mesh", diameter=38.0, position=(0,0,5), direction=(0,0,1))},
            "gear_driven": {"pitch": InterfacePort(name="pitch", feature_type="gear_mesh", diameter=58.0, position=(0,0,5), direction=(0,0,1))}
        },
        description="Target center distance should be 50mm, but placed at 38mm (12mm severe gear body overlap)."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-23",
        name="timing_pulleys_overlapping",
        category="gear_mesh",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="pulley_in", name="pulley_in", part_type="base", length=30.0, width=30.0, height=15.0),
                PartSpec(id="pulley_out", name="pulley_out", length=30.0, width=30.0, height=15.0,
                         mates=[MatingContext(partner_id="pulley_in", mate_type="gear_mesh")])
            ],
            shared_parameters={"center_to_center_distance": 20.0}
        ),
        parts_code={
            "pulley_in": """import cadquery as cq
result = cq.Workplane("XY").circle(15.0).extrude(15.0)
""",
            "pulley_out": """import cadquery as cq
result = cq.Workplane("XY").circle(15.0).extrude(15.0)
"""
        },
        interfaces={
            "pulley_in": {"pitch": InterfacePort(name="pitch", feature_type="gear_mesh", diameter=30.0, position=(0,0,7.5), direction=(0,0,1))},
            "pulley_out": {"pitch": InterfacePort(name="pitch", feature_type="gear_mesh", diameter=30.0, position=(0,0,7.5), direction=(0,0,1))}
        },
        description="Two 30mm OD pulleys placed at 20mm center distance (10mm overlap)."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-24",
        name="pinion_ring_gear_clash",
        category="gear_mesh",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="ring_gear", name="ring_gear", part_type="base", length=70.0, width=70.0, height=12.0),
                PartSpec(id="planet_pinion", name="planet_pinion", length=25.0, width=25.0, height=12.0,
                         mates=[MatingContext(partner_id="ring_gear", mate_type="gear_mesh")])
            ],
            shared_parameters={"center_to_center_distance": 28.0}
        ),
        parts_code={
            "ring_gear": """import cadquery as cq
result = cq.Workplane("XY").circle(35.0).circle(25.0).extrude(12.0)
""",
            "planet_pinion": """import cadquery as cq
result = cq.Workplane("XY").circle(12.5).extrude(12.0)
"""
        },
        interfaces={
            "ring_gear": {"internal_pitch": InterfacePort(name="internal_pitch", feature_type="gear_mesh", diameter=50.0, position=(0,0,6), direction=(0,0,1))},
            "planet_pinion": {"pitch": InterfacePort(name="pitch", feature_type="gear_mesh", diameter=25.0, position=(0,0,6), direction=(0,0,1))}
        },
        description="Planet pinion center at 28mm clashes with 25mm internal tooth rim."
    ))

    cases.append(AssemblyTestCase(
        id="ASY-25",
        name="dual_roller_interference",
        category="gear_mesh",
        expected_fault_type="positioning",
        graph=AssemblyGraph(
            parts=[
                PartSpec(id="drive_roller", name="drive_roller", part_type="base", length=40.0, width=40.0, height=30.0),
                PartSpec(id="pinch_roller", name="pinch_roller", length=40.0, width=40.0, height=30.0,
                         mates=[MatingContext(partner_id="drive_roller", mate_type="gear_mesh")])
            ],
            shared_parameters={"center_to_center_distance": 34.0}
        ),
        parts_code={
            "drive_roller": """import cadquery as cq
result = cq.Workplane("XY").circle(20.0).extrude(30.0)
""",
            "pinch_roller": """import cadquery as cq
result = cq.Workplane("XY").circle(20.0).extrude(30.0)
"""
        },
        interfaces={
            "drive_roller": {"contact": InterfacePort(name="contact", feature_type="gear_mesh", diameter=40.0, position=(0,0,15), direction=(0,0,1))},
            "pinch_roller": {"contact": InterfacePort(name="contact", feature_type="gear_mesh", diameter=40.0, position=(0,0,15), direction=(0,0,1))}
        },
        description="Two 40mm OD rollers placed at center distance 34mm (6mm heavy interference instead of tangent 40mm)."
    ))

    return cases
