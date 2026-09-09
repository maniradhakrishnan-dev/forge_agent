"""
Tests for PartRepairAgent zero-LLM code editing tools.

Verifies:
1. Variable parsing from CadQuery scripts
2. Parametric fixes (wall thickness, hole diameter, bounding box)
3. Correct escalation for topology/manifold failures
4. Syntax fixes (fillet removal, filterBy removal)
"""

import pytest
from orchestrator.agents.part_repair_agent import PartRepairAgent
from orchestrator.models import VerificationVerdict, DFMDiagnostic


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CADQUERY_CODE = """import cadquery as cq
import math

# Parameters
wall_thickness = 1.2
outer_dia = 50.0
height = 30.0
hole_diameter = 1.5
bore_dia = 6.0
num_teeth = 20
module_val = 2.5

# Build part
result = cq.Workplane("XY").circle(outer_dia / 2).extrude(height)
result = result.faces(">Z").workplane().circle(bore_dia / 2).cutThruAll()
result = result.faces(">Z").workplane().circle(hole_diameter / 2).cutThruAll()
"""

SAMPLE_CODE_WITH_FILLET = """import cadquery as cq

outer_dia = 40.0
height = 20.0

result = cq.Workplane("XY").circle(outer_dia / 2).extrude(height)
result = result.edges("|Z").fillet(2.0)
result = result.faces(">Z").workplane().circle(3).cutThruAll()
result = result.edges("%CIRCLE").chamfer(0.5)
"""

SAMPLE_CODE_WITH_FILTERBY = """import cadquery as cq

result = cq.Workplane("XY").box(40, 30, 10)
result = result.faces(">Z").edges().filterBy(lambda e: e.Length() > 20).fillet(1.0)
"""


@pytest.fixture
def agent():
    return PartRepairAgent()


# ---------------------------------------------------------------------------
# 1. Variable Parsing Tests
# ---------------------------------------------------------------------------

class TestVariableParsing:
    def test_parses_simple_assignments(self):
        variables = PartRepairAgent._parse_variables(SAMPLE_CADQUERY_CODE)
        assert "wall_thickness" in variables
        assert variables["wall_thickness"][0] == 1.2
        assert "outer_dia" in variables
        assert variables["outer_dia"][0] == 50.0
        assert "height" in variables
        assert variables["height"][0] == 30.0

    def test_parses_hole_diameter(self):
        variables = PartRepairAgent._parse_variables(SAMPLE_CADQUERY_CODE)
        assert "hole_diameter" in variables
        assert variables["hole_diameter"][0] == 1.5

    def test_skips_import_lines(self):
        variables = PartRepairAgent._parse_variables(SAMPLE_CADQUERY_CODE)
        assert "cq" not in variables
        assert "math" not in variables

    def test_skips_cadquery_object_assignments(self):
        variables = PartRepairAgent._parse_variables(SAMPLE_CADQUERY_CODE)
        assert "result" not in variables

    def test_empty_code(self):
        variables = PartRepairAgent._parse_variables("")
        assert variables == {}


# ---------------------------------------------------------------------------
# 2. Parametric Fix Tests
# ---------------------------------------------------------------------------

class TestParametricFix:
    def test_fixes_wall_thickness(self, agent):
        """STRUCT-01: wall_thickness 1.2mm → 2.0mm (required ≥1.5mm + 0.5 margin)"""
        verdict = VerificationVerdict(
            passed=False,
            diagnostics=[
                DFMDiagnostic(
                    rule_id="STRUCT-01",
                    status="FAIL",
                    parameter="min_wall_thickness",
                    measured=1.2,
                    required=1.5,
                    message="Wall thickness 1.2mm < minimum 1.5mm"
                )
            ]
        )
        fixed_code, was_fixed, notes = agent.attempt_parametric_fix(SAMPLE_CADQUERY_CODE, verdict)
        assert was_fixed is True
        assert fixed_code is not None
        assert "wall_thickness = 2.0" in fixed_code
        assert "STRUCT-01" in notes[0]

    def test_fixes_hole_diameter(self, agent):
        """DFM-3D-02: hole_diameter 1.5mm → 2.2mm (required ≥2.0mm + 0.2 margin)"""
        verdict = VerificationVerdict(
            passed=False,
            diagnostics=[
                DFMDiagnostic(
                    rule_id="DFM-3D-02",
                    status="FAIL",
                    parameter="min_hole_diameter",
                    measured=1.5,
                    required=2.0,
                    message="Hole diameter 1.5mm too small for 3D printing"
                )
            ]
        )
        fixed_code, was_fixed, notes = agent.attempt_parametric_fix(SAMPLE_CADQUERY_CODE, verdict)
        assert was_fixed is True
        assert fixed_code is not None
        assert "hole_diameter = 2.2" in fixed_code

    def test_fixes_bounding_box_too_large(self, agent):
        """SPEC-01: outer_dia 50.0mm when target is 45.0mm — scale down"""
        verdict = VerificationVerdict(
            passed=False,
            diagnostics=[
                DFMDiagnostic(
                    rule_id="SPEC-01",
                    status="FAIL",
                    parameter="bounding_box_width",
                    measured=50.0,
                    required=45.0,
                    message="Bounding box 50.0mm > target 45.0mm"
                )
            ]
        )
        fixed_code, was_fixed, notes = agent.attempt_parametric_fix(SAMPLE_CADQUERY_CODE, verdict)
        assert was_fixed is True
        assert fixed_code is not None
        # outer_dia should be scaled down by factor 45/50 = 0.9
        assert "outer_dia = 45.0" in fixed_code
        assert "SPEC-01" in notes[0]

    def test_refuses_topology_failure(self, agent):
        """PHYS-01 (disconnected bodies) cannot be fixed parametrically"""
        verdict = VerificationVerdict(
            passed=False,
            diagnostics=[
                DFMDiagnostic(
                    rule_id="PHYS-01",
                    status="FAIL",
                    parameter="solid_bodies",
                    measured=3.0,
                    required=1.0,
                    message="Part consists of 3 disconnected solid bodies"
                )
            ]
        )
        fixed_code, was_fixed, notes = agent.attempt_parametric_fix(SAMPLE_CADQUERY_CODE, verdict)
        assert was_fixed is False
        assert fixed_code is None
        assert any("Designer" in n or "LLM" in n for n in notes)

    def test_refuses_self_intersection(self, agent):
        """PHYS-02 (self-intersection) cannot be fixed parametrically"""
        verdict = VerificationVerdict(
            passed=False,
            diagnostics=[
                DFMDiagnostic(
                    rule_id="PHYS-02",
                    status="FAIL",
                    parameter="topology",
                    measured=0.0,
                    required=0.0,
                    message="Self-intersecting wires detected"
                )
            ]
        )
        fixed_code, was_fixed, notes = agent.attempt_parametric_fix(SAMPLE_CADQUERY_CODE, verdict)
        assert was_fixed is False
        assert fixed_code is None

    def test_no_op_on_passing_verdict(self, agent):
        """If all diagnostics pass, return the code unchanged."""
        verdict = VerificationVerdict(
            passed=True,
            diagnostics=[
                DFMDiagnostic(
                    rule_id="STRUCT-01",
                    status="PASS",
                    parameter="min_wall_thickness",
                    measured=2.0,
                    required=1.5,
                    message="Wall thickness OK"
                )
            ]
        )
        fixed_code, was_fixed, notes = agent.attempt_parametric_fix(SAMPLE_CADQUERY_CODE, verdict)
        assert was_fixed is True
        assert fixed_code == SAMPLE_CADQUERY_CODE


# ---------------------------------------------------------------------------
# 3. Syntax Fix Tests
# ---------------------------------------------------------------------------

class TestSyntaxFix:
    def test_removes_fillet_on_brep_failure(self, agent):
        """Fillet crash → remove .fillet() and .chamfer() calls"""
        error = "Standard_Failure: BRep_API fillet operation failed: StdFail_NotDone"
        fixed_code, was_fixed, notes = agent.attempt_syntax_fix(SAMPLE_CODE_WITH_FILLET, error)
        assert was_fixed is True
        assert ".fillet(" not in fixed_code
        assert ".chamfer(" not in fixed_code
        # Core geometry should be preserved
        assert "circle(outer_dia / 2)" in fixed_code
        assert ".extrude(height)" in fixed_code

    def test_removes_filterby(self, agent):
        """filterBy crash → remove .filterBy() calls"""
        error = "AttributeError: 'Workplane' object has no attribute 'filterBy'"
        fixed_code, was_fixed, notes = agent.attempt_syntax_fix(SAMPLE_CODE_WITH_FILTERBY, error)
        assert was_fixed is True
        assert ".filterBy(" not in fixed_code

    def test_no_fix_for_unknown_error(self, agent):
        """Unknown error → no fix available"""
        error = "SomeCompletelyUnknownError: something weird happened"
        fixed_code, was_fixed, notes = agent.attempt_syntax_fix(SAMPLE_CADQUERY_CODE, error)
        assert was_fixed is False
        assert fixed_code is None


# ---------------------------------------------------------------------------
# 4. Variable Replacement Tests
# ---------------------------------------------------------------------------

class TestVariableReplacement:
    def test_replaces_exact_variable(self):
        code = "wall_thickness = 1.2\nouter_dia = 50.0\n"
        result = PartRepairAgent._replace_variable(code, "wall_thickness", "wall_thickness = 1.2", 2.0)
        assert "wall_thickness = 2.0" in result
        assert "outer_dia = 50.0" in result  # Other variables untouched

    def test_preserves_other_lines(self):
        code = "import cadquery as cq\nwall_thickness = 1.2\nresult = cq.Workplane('XY').box(10, 10, 10)\n"
        result = PartRepairAgent._replace_variable(code, "wall_thickness", "wall_thickness = 1.2", 2.5)
        assert "import cadquery as cq" in result
        assert "result = cq.Workplane" in result
        assert "wall_thickness = 2.5" in result


# ---------------------------------------------------------------------------
# 5. Escalation Path Tests (existing methods still work)
# ---------------------------------------------------------------------------

class TestEscalationFormatters:
    def test_generate_repair_instructions_format(self, agent):
        """Existing text formatter still works for Designer escalation"""
        verdict = VerificationVerdict(
            passed=False,
            diagnostics=[
                DFMDiagnostic(
                    rule_id="PHYS-01",
                    status="FAIL",
                    parameter="solid_bodies",
                    measured=3.0,
                    required=1.0,
                    message="Part consists of 3 disconnected solid bodies"
                )
            ]
        )
        result = agent.generate_repair_instructions(verdict)
        assert "PHYS-01" in result
        assert "disconnected solid bodies" in result

    def test_generate_syntax_repair_instructions(self, agent):
        error = "Standard_Failure in fillet operation"
        result = agent.generate_syntax_repair_instructions(error)
        assert "fillet" in result.lower()
