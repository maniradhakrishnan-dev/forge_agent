"""
Unit tests for 6-pillar single-part verification depth system (tools/verify_single_part.py).
"""

import pytest
import cadquery as cq
from tools.verify_single_part import (
    check_solid_manifold,
    check_brep_topology_integrity,
    check_dfm_wall_thickness,
    check_dfm_hole_diameter,
    check_dfm_overhang_angle,
    check_cnc_hole_aspect_ratio,
    check_sheet_metal_uniform_thickness,
    check_bounding_box_compliance,
    verify_single_part
)
from orchestrator.toolbox import AgentToolbox, AgentToolboxError


def test_concept_depth_fast():
    box = cq.Workplane("XY").box(40, 30, 10)
    verdict = verify_single_part(box, depth="concept")
    assert verdict.passed is True
    # Concept depth should only run 3 checks
    assert len(verdict.diagnostics) == 3
    assert any(d.rule_id == "SPEC-01" for d in verdict.diagnostics)


def test_functional_depth_standard():
    part = cq.Workplane("XY").box(40, 30, 10).faces(">Z").workplane().hole(4.3)
    verdict = verify_single_part(part, depth="functional", target_len=40.0)
    assert verdict.passed is True
    assert len(verdict.diagnostics) == 6
    assert any(d.rule_id == "STRUCT-02" for d in verdict.diagnostics)


def test_manufacturing_depth_3d_printing():
    part = cq.Workplane("XY").box(40, 30, 10).faces(">Z").workplane().hole(4.3)
    verdict = verify_single_part(part, process="3d_printing", depth="manufacturing", target_len=40.0)
    assert verdict.passed is True
    assert any(d.rule_id == "DFM-3D-01" for d in verdict.diagnostics)


def test_manufacturing_depth_cnc():
    part = cq.Workplane("XY").box(40, 30, 10).faces(">Z").workplane().hole(4.3)
    verdict = verify_single_part(part, process="cnc_machining", depth="manufacturing", target_len=40.0)
    assert verdict.passed is True
    assert any(d.rule_id == "DFM-CNC-01" for d in verdict.diagnostics)


def test_manufacturing_depth_sheet_metal():
    part = cq.Workplane("XY").box(40, 30, 2)
    verdict = verify_single_part(part, process="sheet_metal", depth="manufacturing", target_len=40.0)
    assert verdict.passed is True
    assert any(d.rule_id == "DFM-SM-01" for d in verdict.diagnostics)


def test_assembly_ready_depth_fastener_check():
    part = cq.Workplane("XY").box(40, 30, 10).faces(">Z").workplane().hole(4.3)
    verdict = verify_single_part(part, depth="assembly_ready", target_len=40.0)
    assert verdict.passed is True
    assert any(d.rule_id == "FAST-01" for d in verdict.diagnostics)


def test_guardrail_enforcement():
    # Toolbox allows part_verifier_agent to call verify_single_part
    assert AgentToolbox.can_use("part_verifier_agent", "verify_single_part") is True
    # Toolbox forbids code_generator_agent from calling verify_single_part directly
    assert AgentToolbox.can_use("code_generator_agent", "verify_single_part") is False
    
    with pytest.raises(AgentToolboxError):
        AgentToolbox.enforce("code_generator_agent", "verify_single_part")
