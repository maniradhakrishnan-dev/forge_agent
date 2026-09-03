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
