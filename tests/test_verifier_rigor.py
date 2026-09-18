"""
Unit tests for Verifier Rigor and Zero-Token Iterations.

Validates that:
1. SPEC-01 enforces all 3 bounding dimensions (catches multi-axis deviations).
2. DFM-3D-02 distinguishes internal holes from external solid pins/shafts.
3. STRUCT-01 catches true hole-to-edge wall thickness violations.
4. ASSY-01 does not excuse arbitrary rigid collisions as gear meshes.
5. ASSY-02 fails when declared mating parts are displaced/too loose.
6. PartRepairAgent.attempt_user_parametric_edit resolves numeric user prompts in 0 LLM tokens.
"""

import pytest
import cadquery as cq
from orchestrator.models import AssemblyGraph, PartSpec, MatingContext
from tools.verify_single_part import (
    check_bounding_box_compliance,
    check_dfm_hole_diameter,
    check_dfm_wall_thickness,
    check_feature_count
)
from tools.verify_assembly import (
    check_interference,
    check_fit_clearance
)
from orchestrator.agents.part_repair_agent import PartRepairAgent


def test_spec_01_multi_axis_enforcement():
    """A 100x100x100 cube must fail when spec requested 100x20x5mm."""
    cube = cq.Workplane("XY").box(100, 100, 100).val()
    diag = check_bounding_box_compliance(cube, target_len=100.0, target_width=20.0, target_height=5.0)
    assert diag.status == "FAIL"
    assert "deviates from target" in diag.message


def test_dfm_3d_02_ignores_external_pins():
    """An external 1.5mm pin/shaft (diameter 1.5mm) must NOT fail DFM-3D-02 (minimum hole diameter 2.0mm)."""
    # Create a base block with a 1.5mm pin on top
    pin_part = (
        cq.Workplane("XY")
        .box(20, 20, 5)
        .faces(">Z")
        .circle(0.75)  # Radius 0.75mm -> Diameter 1.5mm
        .extrude(6.0)
        .val()
    )
    diag = check_dfm_hole_diameter(pin_part, min_diameter=2.0)
    # The pin is solid material, so it should be skipped and reported as no holes or PASS
    assert diag.status == "PASS"


def test_dfm_3d_02_catches_small_internal_hole():
    """An internal hole with diameter 1.5mm must fail DFM-3D-02 (minimum hole diameter 2.0mm)."""
    hole_part = (
        cq.Workplane("XY")
        .box(20, 20, 10)
        .faces(">Z")
        .hole(1.5)  # Diameter 1.5mm hole
        .val()
    )
    diag = check_dfm_hole_diameter(hole_part, min_diameter=2.0)
    assert diag.status == "FAIL"
    assert diag.measured == 1.5


def test_struct_01_catches_hole_too_close_to_edge():
    """A hole drilled 0.8mm from the outer boundary must fail STRUCT-01 (min wall 1.5mm)."""
    # Box 20x20x10 (X from -10 to 10). Hole of radius 2.0 at X=7.2 -> wall to edge is 10 - (7.2 + 2.0) = 0.8mm
    box_thin_wall = (
        cq.Workplane("XY")
        .box(20, 20, 10)
        .faces(">Z")
        .workplane()
        .transformed(offset=(7.2, 0, 0))
        .hole(4.0)
        .val()
    )
    diag = check_dfm_wall_thickness(box_thin_wall, min_thickness=1.5)
    assert diag.status == "FAIL"
    assert "Hole wall thickness to outer edge" in diag.message


def test_assy_01_does_not_excuse_rigid_collision_as_gears():
    """A rigid block colliding with another rigid block must FAIL ASSY-01 even if overlap < 15%."""
    # Two rigid blocks colliding slightly (overlap volume ~ 5%)
    part_a = cq.Workplane("XY").box(20, 20, 10).val()
    part_b = cq.Workplane("XY").transformed(offset=(18, 0, 0)).box(20, 20, 10).val()

    parts = {"block_a": part_a, "block_b": part_b}
    diag = check_interference(parts)
    assert diag.status == "FAIL"
    assert "Interference detected between" in diag.message


def test_assy_02_fails_displaced_mating_pair():
    """Declared mating parts separated by 10mm must FAIL ASSY-02, not pass as 'spaced links'."""
    part_a = cq.Workplane("XY").box(20, 20, 10).val()
    part_b = cq.Workplane("XY").transformed(offset=(30, 0, 0)).box(20, 20, 10).val()

    graph = AssemblyGraph(
        name="test_assembly",
        parts=[
            PartSpec(id="part_a", mates=[MatingContext(partner_id="part_b", mate_type="hole_shaft")]),
            PartSpec(id="part_b", mates=[MatingContext(partner_id="part_a", mate_type="shaft_hole")])
        ]
    )
    parts = {"part_a": part_a, "part_b": part_b}
    diag = check_fit_clearance(parts, graph=graph, min_clearance=0.1, max_clearance=0.5)
    assert diag.status == "FAIL"
    assert "outside allowable range" in diag.message


def test_part_repair_agent_user_parametric_edit():
    """PartRepairAgent.attempt_user_parametric_edit correctly modifies code with 0 LLM tokens."""
    code = (
        "import cadquery as cq\n"
        "length = 40.0\n"
        "width = 30.0\n"
        "hole_dia = 4.0\n"
        "result = cq.Workplane('XY').box(length, width, 10).faces('>Z').hole(hole_dia)\n"
    )
    agent = PartRepairAgent()

    # Edit 1: Hole diameter
    new_code, fixed, note = agent.attempt_user_parametric_edit(code, "increase hole diameter to 6mm")
    assert fixed is True
    assert "hole_dia = 6.0" in new_code
    assert "length = 40.0" in new_code

    # Edit 2: Length
    new_code2, fixed2, note2 = agent.attempt_user_parametric_edit(code, "change length to 55mm")
    assert fixed2 is True
    assert "length = 55.0" in new_code2
    assert "hole_dia = 4.0" in new_code2


def test_spec_01_unconstrained_single_part_flexibility():
    """Unconstrained single parts (no explicit user constraints) tolerate natural proportional variations."""
    shape = cq.Workplane("XY").box(100.0, 50.0, 50.0)
    
    # 1. With is_single_part=True and no explicit constraints: 100x50x50 passes against inferred 50x50x50
    diag_pass = check_bounding_box_compliance(
        shape, target_len=50.0, target_width=50.0, target_height=50.0,
        is_single_part=True, explicit_constraints={}
    )
    assert diag_pass.status == "PASS"

    # 2. With explicit user constraints (user asked for length=50): 100x50x50 strictly fails
    diag_fail = check_bounding_box_compliance(
        shape, target_len=50.0, target_width=50.0, target_height=50.0,
        is_single_part=True, explicit_constraints={"length": 50.0}
    )
    assert diag_fail.status == "FAIL"


def test_part_repair_fillet_crash_healing():
    """PartRepairAgent heals OpenCascade ChFi3d_Builder and empty edge selection crashes."""
    code = (
        "import cadquery as cq\n"
        "result = cq.Workplane('XY').box(20, 20, 10).edges().fillet(2.0)\n"
    )
    agent = PartRepairAgent()
    
    # Simulate ChFi3d_Builder crash
    err = "CadQuery Execution Error: Standard_ConstructionError: ChFi3d_Builder:only 2 faces"
    new_code, fixed, notes = agent.attempt_syntax_fix(code, err)
    assert fixed is True
    assert ".fillet(" not in new_code
    assert "result = cq.Workplane('XY').box(20, 20, 10)" in new_code


def test_feat_01_allows_cylindrical_shaft():
    """A cylindrical shaft has 3 to 5 faces and must PASS FEAT-01 (not require >=6 faces like a box)."""
    # Simple cylinder with 3 faces (1 tube + 2 caps)
    shaft = cq.Workplane("XY").circle(5.0).extrude(40.0).val()
    diag = check_feature_count(shaft, is_shaft=True)
    assert diag.status == "PASS"

    # Chamfered shaft with 5 faces
    chamfered_shaft = cq.Workplane("XY").circle(5.0).extrude(40.0).faces("<Z or >Z").chamfer(0.5).val()
    diag2 = check_feature_count(chamfered_shaft, is_shaft=True)
    assert diag2.status == "PASS"

