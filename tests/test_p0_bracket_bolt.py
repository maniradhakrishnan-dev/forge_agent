"""
P0 Test Case 3: Bracket + Bolt Assembly.
Verifies multi-part placement, zero interference (0.0 mm³ overlap), and fit clearance.
"""

import pytest
import cadquery as cq
from tools.verify_assembly import verify_assembly


def test_p0_bracket_bolt_assembly():
    # Mounting Bracket with 4.3mm hole at origin
    bracket = (
        cq.Workplane("XY")
        .box(40, 30, 10)
        .faces(">Z").workplane()
        .hole(4.3)
    )
    
    # M4 Bolt shaft (4.0mm diameter) positioned inside bracket hole
    # Bracket top face is at Z=+5.0. Bolt head is 3mm tall, centered at Z=+6.5 so bottom is at Z=+5.0.
    bolt_head = cq.Workplane("XY").workplane(offset=6.5).cylinder(3.0, 4.0)
    bolt_shaft = cq.Workplane("XY").cylinder(10.0, 2.0)
    bolt = bolt_head.union(bolt_shaft)

    parts = {"bracket": bracket, "bolt": bolt}
    verdict = verify_assembly(parts, min_clearance=0.1, max_clearance=0.5)
    assert verdict.passed is True
    assert all(d.status == "PASS" for d in verdict.diagnostics)
