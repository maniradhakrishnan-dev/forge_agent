"""
P1 Test Case: Crank-Slider Mechanism (3-4 parts, revolute pin joint, 360° kinematic sweep).
Verifies multi-part kinematic motion sweep trajectory for collision-free rotation.
"""

import pytest
import cadquery as cq
from tools.verify_assembly import verify_assembly
from orchestrator.models import JointDef


def test_p1_crank_slider_kinematic_sweep():
    # Base Ground Frame
    frame = cq.Workplane("XY").box(100, 40, 10)
    
    # Rotating Crank Arm (length=30mm)
    crank = cq.Workplane("XY").workplane(offset=15.0).box(30, 10, 5)
    
    # Connecting Rod (length=50mm)
    conrod = cq.Workplane("XY").workplane(offset=25.0).box(50, 8, 4)

    parts = {"frame": frame, "crank": crank, "conrod": conrod}
    
    # Revolute joint defining crank rotation around Z-axis
    crank_joint = JointDef(
        id="j_crank",
        type="revolute",
        part_a="frame",
        part_b="crank",
        axis=(0, 0, 1)
    )

    verdict = verify_assembly(parts, joints=[crank_joint])
    assert verdict.passed is True
    assert any(d.rule_id == "ASSY-03" for d in verdict.diagnostics)
