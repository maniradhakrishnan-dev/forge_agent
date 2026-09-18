"""
End-to-end tests for shaft and hole assembly.
Verifies that:
1. Mating feature contracts (MATE-01) validate BRep cylinder radii against MatingContext.
2. Contract-driven AssemblyAgent correctly snaps shaft into bore without guessing.
3. Multi-part assembly verification passes ASSY-01 (no interference) and ASSY-02 (fit clearance).
4. Sizing mismatch (shaft > hole) is caught as a physical failure.
"""

import pytest
import cadquery as cq
from orchestrator.models import (
    PartSpec,
    MatingContext,
    InterfacePort,
    AssemblyGraph,
    JointDef
)
from orchestrator.agents.assembly_agent import AssemblyAgent
from tools.verify_single_part import verify_single_part
from tools.verify_assembly import verify_assembly


def test_shaft_hole_mating_feature_verification():
    """Verify that MATE-01 detects compliant cylindrical features matching the spec contract."""
    # 1. Housing with 6.15mm bore
    housing_solid = (
        cq.Workplane("XY")
        .circle(15.0)  # OD 30mm
        .extrude(20.0)
        .faces(">Z")
        .hole(6.15, 20.0)  # ID 6.15mm
    )

    housing_spec = PartSpec(
        id="housing",
        name="bearing_housing",
        part_type="housing",
        geometry_form="annular_flanged_casing",
        length=30.0,
        width=30.0,
        height=20.0,
        critical_dimensions={"bore_diameter": 6.15, "outer_diameter": 30.0},
        mates=[
            MatingContext(
                partner_id="shaft",
                mate_type="hole_shaft",
                my_feature_name="bore_center",
                mate_port_id="shaft_tip",
                my_feature_diameter=6.15,
                clearance_mm=0.15
            )
        ]
    )

    h_verdict = verify_single_part(
        housing_solid,
        depth="assembly_ready",
        mates=housing_spec.mates,
        critical_dimensions=housing_spec.critical_dimensions
    )
    assert h_verdict.passed is True
    mate_diag = next(d for d in h_verdict.diagnostics if d.rule_id == "MATE-01")
    assert mate_diag.status == "PASS"

    # 2. Shaft with 6.0mm outer diameter
    shaft_solid = (
        cq.Workplane("XY")
        .circle(3.0)  # OD 6.0mm
        .extrude(35.0)  # Length 35mm
    )

    shaft_spec = PartSpec(
        id="shaft",
        name="drive_shaft",
        part_type="shaft",
        geometry_form="stepped_shaft",
        length=35.0,
        width=6.0,
        height=6.0,
        critical_dimensions={"outer_diameter": 6.0, "length": 35.0},
        mates=[
            MatingContext(
                partner_id="housing",
                mate_type="shaft_hole",
                my_feature_name="shaft_tip",
                mate_port_id="bore_center",
                my_feature_diameter=6.0,
                clearance_mm=0.15
            )
        ]
    )

    s_verdict = verify_single_part(
        shaft_solid,
        depth="assembly_ready",
        mates=shaft_spec.mates,
        critical_dimensions=shaft_spec.critical_dimensions
    )
    assert s_verdict.passed is True
    s_mate_diag = next(d for d in s_verdict.diagnostics if d.rule_id == "MATE-01")
    assert s_mate_diag.status == "PASS"


@pytest.mark.asyncio
async def test_shaft_hole_assembly_end_to_end():
    """Verify that AssemblyAgent positions shaft inside housing and assembly verification passes."""
    housing_solid = (
        cq.Workplane("XY")
        .circle(15.0)
        .extrude(20.0)
        .faces(">Z")
        .hole(6.15, 20.0)
    )

    shaft_solid = (
        cq.Workplane("XY")
        .circle(3.0)
        .extrude(35.0)
    )

    housing_ports = {
        "bore_center": InterfacePort(
            name="bore_center",
            mate_key="shaft_tip",
            position=(0.0, 0.0, 20.0),
            direction=(0.0, 0.0, 1.0),
            feature_type="hole",
            diameter=6.15
        )
    }

    shaft_ports = {
        "shaft_tip": InterfacePort(
            name="shaft_tip",
            mate_key="bore_center",
            position=(0.0, 0.0, 0.0),
            direction=(0.0, 0.0, -1.0),
            feature_type="shaft",
            diameter=6.0
        )
    }

    graph = AssemblyGraph(
        name="shaft_housing_assembly",
        parts=[
            PartSpec(
                id="housing",
                name="housing",
                part_type="housing",
                geometry_form="annular_flanged_casing",
                length=30.0,
                width=30.0,
                height=20.0,
                mates=[
                    MatingContext(
                        partner_id="shaft",
                        mate_type="hole_shaft",
                        my_feature_name="bore_center",
                        mate_port_id="shaft_tip",
                        my_feature_diameter=6.15,
                        clearance_mm=0.15
                    )
                ]
            ),
            PartSpec(
                id="shaft",
                name="shaft",
                part_type="shaft",
                geometry_form="stepped_shaft",
                length=35.0,
                width=6.0,
                height=6.0,
                mates=[
                    MatingContext(
                        partner_id="housing",
                        mate_type="shaft_hole",
                        my_feature_name="shaft_tip",
                        mate_port_id="bore_center",
                        my_feature_diameter=6.0,
                        clearance_mm=0.15
                    )
                ]
            )
        ],
        joints=[
            JointDef(
                id="j_rev",
                type="revolute",
                part_a="housing",
                part_b="shaft",
                axis=(0.0, 0.0, 1.0)
            )
        ]
    )

    agent = AssemblyAgent()
    solids = {"housing": housing_solid, "shaft": shaft_solid}
    interfaces = {"housing": housing_ports, "shaft": shaft_ports}

    transformed_solids, cq_assy = await agent.assemble_parts(graph, solids, interfaces)

    assert "housing" in transformed_solids
    assert "shaft" in transformed_solids

    # Run assembly verification
    verdict = verify_assembly(
        transformed_solids,
        joints=graph.joints,
        graph=graph,
        interfaces=interfaces
    )

    assert verdict.passed is True
    # Verify no interference
    inter_diag = next(d for d in verdict.diagnostics if d.rule_id == "ASSY-01")
    assert inter_diag.status == "PASS"


def test_shaft_hole_interference_caught_when_oversized():
    """Verify that if the shaft is oversized (diameter 6.5mm in 6.15mm hole), it fails."""
    # Housing with 6.15mm bore
    housing_solid = (
        cq.Workplane("XY")
        .circle(15.0)
        .extrude(20.0)
        .faces(">Z")
        .hole(6.15, 20.0)
    )

    # Oversized shaft: OD 6.5mm (radius 3.25mm) in a 6.15mm hole
    oversized_shaft = (
        cq.Workplane("XY")
        .circle(3.25)
        .extrude(35.0)
    )

    # Put shaft co-axial with housing hole
    parts = {
        "housing": housing_solid,
        "shaft": oversized_shaft
    }

    # Verify assembly detects interference
    verdict = verify_assembly(parts)
    inter_diag = next(d for d in verdict.diagnostics if d.rule_id == "ASSY-01")
    assert inter_diag.status == "FAIL"
    assert inter_diag.measured > 0.0


def test_shaft_bounding_box_compliance_with_cylindrical_envelope():
    """Verify that a 15mm cylindrical shaft complies with SPEC-01 and CRIT-01 without false rectangular failure."""
    from orchestrator.agents.part_verifier_agent import PartVerifierAgent
    verifier = PartVerifierAgent()

    shaft_spec = PartSpec(
        id="shaft_corner",
        name="corner_shaft",
        part_type="shaft",
        geometry_form="stepped_shaft",
        length=50.0,
        critical_dimensions={"outer_diameter": 14.9, "length": 50.0},
        mates=[
            MatingContext(
                partner_id="block",
                mate_type="shaft_hole",
                my_feature_name="shaft_base",
                my_feature_diameter=14.9,
                clearance_mm=0.1
            )
        ]
    )

    # Verify model validator synchronized width and height to outer_diameter
    assert shaft_spec.width == 14.9
    assert shaft_spec.height == 14.9

    # Model a true physical 14.9mm cylinder of length 50mm
    shaft_solid = cq.Workplane("XY").circle(14.9 / 2.0).extrude(50.0)

    verdict = verifier.verify_part_solid(shaft_solid, spec=shaft_spec)
    assert verdict.passed is True
    spec_diag = next(d for d in verdict.diagnostics if d.rule_id == "SPEC-01")
    assert spec_diag.status == "PASS"
    mate_diag = next(d for d in verdict.diagnostics if d.rule_id == "MATE-01")
    assert mate_diag.status == "PASS"

