"""
Unit tests for multi-part assembly verifier (tools/verify_assembly.py).
"""

import pytest
import cadquery as cq
from tools.verify_assembly import (
    check_interference,
    check_fit_clearance,
    check_kinematic_sweep,
    verify_assembly
)
from orchestrator.models import JointDef


def test_assembly_interference_pass():
    box1 = cq.Workplane("XY").box(40, 30, 10)
    box2 = cq.Workplane("XY").workplane(offset=10.1).box(40, 30, 10)  # No overlap
    
    parts = {"p1": box1, "p2": box2}
    diag = check_interference(parts)
    assert diag.status == "PASS"
    assert diag.measured == 0.0


def test_assembly_interference_fail():
    box1 = cq.Workplane("XY").box(40, 30, 10)
    box2 = cq.Workplane("XY").workplane(offset=5.0).box(40, 30, 10)  # 5mm overlap
    
    parts = {"p1": box1, "p2": box2}
    diag = check_interference(parts)
    assert diag.status == "FAIL"
    assert diag.measured > 0.0


def test_verify_assembly_verdict():
    box1 = cq.Workplane("XY").box(40, 30, 10)
    box2 = cq.Workplane("XY").workplane(offset=10.2).box(40, 30, 10)
    
    parts = {"p1": box1, "p2": box2}
    joint = JointDef(id="j1", type="revolute", part_a="p1", part_b="p2", axis=(0, 0, 1))
    
    verdict = verify_assembly(parts, joints=[joint])
    assert verdict.passed is True
    assert len(verdict.diagnostics) == 4


def test_assembly_compliant_interference_pass():
    """Verify that intentional compliant/flexible interference (e.g. cam inside flex cup) passes within allowable elastic deflection."""
    cam = cq.Workplane("XY").ellipse(16.0, 14.0).extrude(10)
    sleeve = cq.Workplane("XY").circle(20.0).extrude(10).cut(cq.Workplane("XY").circle(15.0).extrude(10))

    parts = {"wave_generator_cam": cam, "flexspline_cup": sleeve}
    diag = check_interference(parts)
    assert diag.status == "PASS"
    assert "Compliant interference verified" in diag.message
    assert "1.0mm <= 2.5mm" in diag.message


def test_assembly_gross_solid_collision_fail():
    """Verify that massive volumetric collisions (> 30% overlap, e.g. non-hollow solid cup) fail as gross solid collision."""
    cam = cq.Workplane("XY").ellipse(16.0, 14.0).extrude(10)
    solid_cup = cq.Workplane("XY").circle(20.0).extrude(10)  # Not hollow!

    parts = {"wave_generator_cam": cam, "flexspline_cup": solid_cup}
    diag = check_interference(parts)
    assert diag.status == "FAIL"
    assert "Gross solid collision" in diag.message
    assert "Ensure internal cavity is hollow" in diag.message


def test_assembly_kinematic_mesh_pass():
    """Verify that kinematic gear/spline/cycloid tooth mesh within 2.5mm engagement passes without false-positive collision."""
    ring_with_pins = (
        cq.Workplane("XY").circle(25.0).extrude(10)
        .cut(cq.Workplane("XY").circle(20.0).extrude(10))
        .union(cq.Workplane("XY").polarArray(19.0, 0, 360, 12).circle(1.5).extrude(10))
    )
    lobed_disk = (
        cq.Workplane("XY").circle(18.5).extrude(10)
        .union(cq.Workplane("XY").polarArray(18.5, 0, 360, 11).circle(1.0).extrude(10))
    )

    parts = {"housing_ring": ring_with_pins, "cycloid_disk": lobed_disk}
    diag = check_interference(parts)
    assert diag.status == "PASS"
    assert "Compliant interference verified" in diag.message


def test_assembly_axial_stacking_collision_fail():
    """Verify that two solid plates co-located on the same axis without axial offset fail as axial stacking collision."""
    plate_a = cq.Workplane("XY").circle(20.0).extrude(10)
    plate_b = cq.Workplane("XY").workplane(offset=2.0).circle(18.0).extrude(10)  # 8mm axial overlap, 80% volume

    parts = {"plate_a": plate_a, "plate_b": plate_b}
    diag = check_interference(parts)
    assert diag.status == "FAIL"
    assert "Axial stacking collision" in diag.message



