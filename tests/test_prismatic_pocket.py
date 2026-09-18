"""
Unit tests for prismatic block cuts, pockets, CAD kernel solid enforcement, and BRep verification.
"""

import pytest
import cadquery as cq
from tools.cad_kernel import _sync_execute_cadquery
from tools.verify_single_part import check_solid_manifold, check_mating_feature_compliance, verify_single_part
from orchestrator.models import PartSpec, VerificationVerdict
from orchestrator.agents.part_repair_agent import PartRepairAgent


def test_cad_kernel_rejects_2d_sketch():
    """Verify that cad_kernel sandbox strictly rejects 2D sketches/wires as non-solids."""
    code_2d = """
import cadquery as cq
result = cq.Workplane("XY").rect(50, 50)
"""
    res, err = _sync_execute_cadquery(code_2d)
    assert res is None
    assert err is not None
    assert "does not contain any 3D solid bodies" in err


def test_cad_kernel_rejects_vector_result():
    """Verify that cad_kernel sandbox rejects non-Workplane/Shape result like Vector."""
    code_vec = """
import cadquery as cq
result = cq.Vector(1, 2, 3)
"""
    res, err = _sync_execute_cadquery(code_vec)
    assert res is None
    assert err is not None
    assert "Vector" in err


def test_cad_kernel_accepts_valid_solid():
    """Verify that cad_kernel accepts a valid 3D solid block with pocket."""
    code_pocket = """
import cadquery as cq
result = (
    cq.Workplane("XY")
    .box(100, 100, 10)
    .faces(">Z").workplane(centerOption="CenterOfMass")
    .rect(50, 50)
    .cutBlind(-5)
)
"""
    res, err = _sync_execute_cadquery(code_pocket)
    assert err is None
    assert res is not None
    assert len(res.solids().vals()) == 1


def test_check_solid_manifold_rejects_wire():
    """Verify that PHYS-01 fails when given an unextruded 2D wire."""
    wire = cq.Workplane("XY").rect(50, 50).val()
    diag = check_solid_manifold(wire)
    assert diag.status == "FAIL"
    assert "does not contain any 3D solid bodies" in diag.message


def test_crit_01_cavity_dimension_measurement():
    """Verify that CRIT-01 correctly measures cavity dimensions from internal BRep faces."""
    # 100x100x10 block with centered 50x50x5 pocket
    solid = (
        cq.Workplane("XY")
        .box(100, 100, 10)
        .faces(">Z").workplane(centerOption="CenterOfMass")
        .rect(50, 50)
        .cutBlind(-5)
        .val()
    )
    crit_dims = {
        "outer_length": 100.0,
        "outer_width": 100.0,
        "outer_height": 10.0,
        "cavity_length": 50.0,
        "cavity_width": 50.0,
        "cavity_depth": 5.0
    }
    diagnostics = check_mating_feature_compliance(solid, critical_dimensions=crit_dims)
    for d in diagnostics:
        assert d.status == "PASS", f"Failed {d.parameter}: {d.message}"


def test_syntax_fix_rejects_non_solid_output():
    """Verify that PartRepairAgent rejects syntax patches that leave non-solid 2D geometry."""
    agent = PartRepairAgent()
    # Code that attempts invalid fillet on 2D sketch
    broken_code = """
import cadquery as cq
result = (
    cq.Workplane("XY")
    .box(100, 100, 10)
)
result = (
    result.faces(">Z")
    .workplane(centerOption="CenterOfMass")
    .rect(50, 50)
    .edges("|Z")
    .fillet(2.5)
)
"""
    exec_error = "ValueError: Fillets requires that edges be selected"
    fixed_code, was_fixed, notes = agent.attempt_syntax_fix(broken_code, exec_error)
    # Since stripping fillet from the second block leaves result as a 2D wire,
    # the syntax fix must reject it because it fails solid execution!
    assert was_fixed is False
