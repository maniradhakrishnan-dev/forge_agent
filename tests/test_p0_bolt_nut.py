"""
P0 Test Case 2: Bolt + Nut Fit Pair.
Verifies standard fastener fit clearance between M4 bolt shaft and nut bore.
"""

import pytest
import cadquery as cq
from tools.verify_assembly import verify_assembly


def test_p0_bolt_nut_clearance_fit():
    # M4 Bolt shaft (4.0mm diameter)
    bolt = cq.Workplane("XY").cylinder(15.0, 2.0)
    
    # M4 Nut (4.3mm clearance bore)
    nut = (
        cq.Workplane("XY")
        .polygon(6, 7.0)
        .extrude(3.2)
        .faces(">Z").workplane()
        .hole(4.3)
        .translate((0, 0, 5.0))
    )

    parts = {"bolt": bolt, "nut": nut}
    verdict = verify_assembly(parts, min_clearance=0.1, max_clearance=0.5)
    assert verdict.passed is True
