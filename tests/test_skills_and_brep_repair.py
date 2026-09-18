"""
Tests for Modular Skill Registry, BRep-Grounded Verification, and JSON-First Repair Architecture.
"""

import pytest
from pathlib import Path
import cadquery as cq

from orchestrator.skills.registry import default_registry, SkillRegistry
from orchestrator.models import PartSpec, VerificationVerdict, DFMDiagnostic
from orchestrator.agents.part_repair_agent import PartRepairAgent
from tools.verify_single_part import check_dfm_wall_thickness, check_feature_count


def test_skill_registry_discovery():
    """Verify that all modular skills are discovered and indexed properly."""
    skills = default_registry.list_skills()
    assert len(skills) >= 10
    assert "cycloidal_drive" in skills
    assert "planetary_gearbox" in skills
    assert "stepped_shaft" in skills
    assert "fasteners_and_flanges" in skills

    # Test keyword resolution
    resolved = default_registry.resolve_skills(
        explicit_skills=[],
        prompt="Design a 20:1 reduction cycloidal drive with eccentric shaft",
        part_types=["disc", "shaft"]
    )
    assert "cycloidal_drive" in resolved
    assert "stepped_shaft" in resolved

    # Test prompt formatting
    formatted = default_registry.format_skills_for_prompt(["cycloidal_drive"])
    assert "Cycloidal Speed Reducer Mechanism Skill" in formatted
    assert "disc_carrier_hole_dia = carrier_pin_dia + (2.0 * eccentricity)" in formatted


def test_brep_wall_thickness_drilled_solid():
    """Verify BRep wall thickness measures true distance from hole to boundary."""
    # Box 40x40x10 with centered through-hole dia 10mm (radius 5mm)
    # Distance from center to edge is 20mm; hole-to-edge wall is 20 - 5 = 15mm
    solid = (
        cq.Workplane("XY")
        .box(40, 40, 10)
        .faces(">Z")
        .workplane()
        .circle(5.0)
        .cutThruAll()
    )
    diag = check_dfm_wall_thickness(solid, min_thickness=1.5)
    assert diag.status == "PASS"
    assert diag.rule_id == "STRUCT-01"
    assert diag.measured >= 14.9  # ~15.0mm


def test_brep_wall_thickness_thin_wall_failure():
    """Verify BRep wall thickness detects thin wall between hole and cylinder perimeter."""
    # Outer radius 6mm, inner hole radius 5.5mm -> wall thickness 0.5mm (< 1.5mm)
    solid = (
        cq.Workplane("XY")
        .circle(6.0)
        .extrude(10.0)
        .faces(">Z")
        .workplane()
        .circle(5.5)
        .cutThruAll()
    )
    diag = check_dfm_wall_thickness(solid, min_thickness=1.5)
    assert diag.status == "FAIL"
    assert diag.rule_id == "STRUCT-01"
    assert diag.measured < 1.0


def test_brep_feature_count_bushing():
    """Verify hollow cylinders (bushings/washers) with 4 faces pass feature count check."""
    # Bushing has 4 faces: outer cylinder, inner cylinder, 2 annular end caps
    solid = (
        cq.Workplane("XY")
        .circle(10.0)
        .extrude(20.0)
        .faces(">Z")
        .workplane()
        .circle(5.0)
        .cutThruAll()
    )
    diag = check_feature_count(solid, requires_hole=True)
    assert diag.status == "PASS"
    assert diag.rule_id == "FEAT-01"
    assert diag.measured == 4.0


def test_json_first_spec_repair(tmp_path):
    """Verify that PartRepairAgent repairs PartSpec contract on disk before code patching."""
    agent = PartRepairAgent()
    spec = PartSpec(
        id="gear_casing",
        name="gear_casing",
        wall_thickness=1.0,
        hole_diameter=1.2,
        length=50.0,
        width=50.0,
        height=20.0
    )

    verdict = VerificationVerdict(
        passed=False,
        diagnostics=[
            DFMDiagnostic(
                rule_id="STRUCT-01",
                status="FAIL",
                parameter="min_wall_thickness",
                measured=1.0,
                required=1.5,
                message="Wall thickness 1.0mm < 1.5mm"
            ),
            DFMDiagnostic(
                rule_id="DFM-3D-02",
                status="FAIL",
                parameter="min_hole_diameter",
                measured=1.2,
                required=2.0,
                message="Hole diameter 1.2mm < 2.0mm"
            )
        ]
    )

    spec_file = tmp_path / "spec.json"
    repaired_spec, was_repaired, notes = agent.repair_spec_contract(spec, verdict, spec_file_path=spec_file)

    assert was_repaired is True
    assert repaired_spec.wall_thickness >= 2.0  # 1.5 + 0.5 safety margin
    assert repaired_spec.hole_diameter >= 2.2   # 2.0 + 0.2 safety margin
    assert spec_file.exists()

    # Load from disk to verify JSON contract integrity
    disk_spec = PartSpec.from_json_file(spec_file)
    assert disk_spec.wall_thickness == repaired_spec.wall_thickness
    assert disk_spec.hole_diameter == repaired_spec.hole_diameter


def test_level1_zero_llm_spec_sync_edit():
    """Verify Level 1 zero-LLM deterministic code syncing from repaired PartSpec."""
    agent = PartRepairAgent()
    code = """import cadquery as cq
wall_thickness = 1.0
hole_dia = 1.2
length = 50.0
width = 50.0
height = 20.0
result = cq.Workplane("XY").box(length, width, height)
"""
    repaired_spec = PartSpec(
        id="casing",
        name="casing",
        wall_thickness=2.0,
        hole_diameter=2.5,
        length=45.0,
        width=45.0,
        height=18.0
    )

    synced_code, was_synced, notes = agent.attempt_spec_sync_edit(code, repaired_spec)
    assert was_synced is True
    assert "wall_thickness = 2.0" in synced_code
    assert "hole_dia = 2.5" in synced_code
    assert "length = 45.0" in synced_code
    assert "width = 45.0" in synced_code
    assert "height = 18.0" in synced_code


def test_attempt_parametric_fix_with_spec(tmp_path):
    """Verify end-to-end parametric fix with JSON contract updating and variable sync."""
    agent = PartRepairAgent()
    code = """import cadquery as cq
wall_thickness = 1.0
hole_dia = 1.2
result = cq.Workplane("XY").box(40, 40, 10)
"""
    spec = PartSpec(id="bracket", name="bracket", wall_thickness=1.0, hole_diameter=1.2)
    verdict = VerificationVerdict(
        passed=False,
        diagnostics=[
            DFMDiagnostic(
                rule_id="STRUCT-01",
                status="FAIL",
                parameter="min_wall_thickness",
                measured=1.0,
                required=1.5,
                message="Wall too thin"
            )
        ]
    )
    spec_path = tmp_path / "spec.json"

    fixed_code, was_fixed, notes = agent.attempt_parametric_fix(code, verdict, spec=spec, spec_file_path=spec_path)
    assert was_fixed is True
    assert "wall_thickness = 2.0" in fixed_code
    assert spec_path.exists()
    saved = PartSpec.from_json_file(spec_path)
    assert saved.wall_thickness == 2.0


def test_catalog_formatting_and_planner_injection():
    """Verify format_catalog_for_planner produces markdown descriptions of all skills."""
    catalog = default_registry.format_catalog_for_planner()
    assert "- `stepped_shaft`:" in catalog
    assert "- `fasteners_and_flanges`:" in catalog
    assert "- `fits_and_tolerances`:" in catalog
    assert "- `cycloidal_drive`:" in catalog
    assert "- `planetary_gearbox`:" in catalog
    assert "- `dfm_3d_printing`:" in catalog


def test_explicit_skills_priority_over_keyword_heuristics():
    """Verify that explicit_skills from PartSpec are resolved directly without keyword matching."""
    # Even if prompt mentions 'shaft' and 'cycloid', explicit_skills should take precedence
    resolved = default_registry.resolve_skills(
        explicit_skills=["fasteners_and_flanges", "dfm_cnc_machining"],
        prompt="Design a cycloidal drive with an eccentric stepped shaft",
        part_types=["shaft", "disc"]
    )
    assert "fasteners_and_flanges" in resolved
    assert "dfm_cnc_machining" in resolved
    assert "cadquery_modeling" in resolved
    # Should NOT have cycloidal_drive or stepped_shaft because explicit_skills took precedence
    assert "cycloidal_drive" not in resolved
    assert "stepped_shaft" not in resolved


def test_part_verifier_typed_contract_hole_detection():
    """Verify PartVerifierAgent relies on typed contract fields rather than name strings."""
    from orchestrator.agents.part_verifier_agent import PartVerifierAgent
    verifier = PartVerifierAgent()

    # Solid bracket with NO hole in spec, features, critical_dimensions, or mates
    solid_cube = cq.Workplane("XY").box(40, 40, 20)
    spec_no_hole = PartSpec(
        id="bracket_1",
        name="bracket_mounting",
        part_type="bracket",
        hole_diameter=0.0,
        features=[],
        mates=[],
        critical_dimensions={"length": 40.0, "width": 40.0, "height": 20.0}
    )

    verdict = verifier.verify_part_solid(solid_cube, spec=spec_no_hole)
    # FEAT-01 must not fail for missing hole on a part that never asked for a hole
    feat_01_diags = [d for d in verdict.diagnostics if d.rule_id == "FEAT-01"]
    for d in feat_01_diags:
        assert d.status == "PASS", f"FEAT-01 failed: {d.message}"

