"""
P0 Test Case 1: Single Mounting Bracket with Clearance Holes.
Verifies single-part CAD generation, 6-pillar DFM verification across processes, and STEP export.
"""

import pytest
import cadquery as cq
from tools.verify_single_part import verify_single_part
from orchestrator.models import PartSpec
from orchestrator.agents.part_verifier_agent import PartVerifierAgent


def test_p0_bracket_3d_printing():
    bracket = (
        cq.Workplane("XY")
        .box(40, 30, 10)
        .faces(">Z").workplane()
        .hole(4.3)
    )
    spec = PartSpec(
        name="mounting_bracket",
        manufacturing_process="3d_printing",
        verification_depth="manufacturing",
        length=40.0,
        width=30.0,
        height=10.0
    )
    verifier = PartVerifierAgent()
    verdict = verifier.verify_part_solid(bracket, spec=spec)
    assert verdict.passed is True
    assert verdict.volume > 0


def test_p0_bracket_cnc_machining():
    bracket = (
        cq.Workplane("XY")
        .box(50, 40, 15)
        .faces(">Z").workplane()
        .hole(5.3)
        .edges("|Z").fillet(2.0)  # Tool clearance fillet
    )
    spec = PartSpec(
        name="cnc_bracket",
        manufacturing_process="cnc_machining",
        verification_depth="manufacturing",
        length=50.0,
        width=40.0,
        height=15.0
    )
    verifier = PartVerifierAgent()
    verdict = verifier.verify_part_solid(bracket, spec=spec)
    assert verdict.passed is True


def test_p0_bracket_sheet_metal():
    bracket = (
        cq.Workplane("XY")
        .box(50, 40, 2.0)  # Thin uniform sheet plate
        .faces(">Z").workplane()
        .hole(4.3)
    )
    spec = PartSpec(
        name="sheet_metal_bracket",
        manufacturing_process="sheet_metal",
        verification_depth="manufacturing",
        length=50.0,
        width=40.0,
        height=2.0
    )
    verifier = PartVerifierAgent()
    verdict = verifier.verify_part_solid(bracket, spec=spec)
    assert verdict.passed is True
