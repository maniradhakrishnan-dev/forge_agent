"""
Unit tests for AssemblyRepairAgent 3-Way Triage (orchestrator/agents/assembly_repair_agent.py).

Verifies:
1. Triage Branch (a): Graph/Port Mismatch -> Direct AssemblyGraph Patch (zero LLM)
   - Center distance parameter patch
   - Axial stacking offset patch
2. Triage Branch (b): Tolerance/Fit Mismatch -> Clearance + Code Variable Patch (zero LLM)
   - Too loose (>0.5mm)
   - Too tight (<0.1mm)
   - Large displacement (>3.0mm) -> positioning fault
3. Triage Branch (c): Geometry Defect -> Routes to PartRepairAgent
   - Gross solid collision (bore/cavity missing)
   - Coaxial tooth/dimension interference
4. Escalation to PlannerAgent after exhausted retries (>5)
"""

import pytest
from orchestrator.models import (
    AssemblyVerdict,
    AssemblyDiagnostic,
    AssemblyGraph,
    PartSpec,
    MatingContext
)
from orchestrator.agents.assembly_repair_agent import AssemblyRepairAgent


@pytest.fixture
def agent():
    return AssemblyRepairAgent()


def test_triage_graph_patch_center_distance(agent):
    """Interference between two parts with a shared center_distance parameter should patch the graph directly."""
    diag = AssemblyDiagnostic(
        rule_id="ASSY-01",
        status="FAIL",
        parameter="interference_overlap_volume",
        measured=120.0,
        required=0.0,
        message="Interference detected between gear_1 and gear_2",
        involved_parts=["gear_1", "gear_2"]
    )
    verdict = AssemblyVerdict(passed=False, diagnostics=[diag])
    graph = AssemblyGraph(
        name="gear_assembly",
        parts=[PartSpec(id="gear_1"), PartSpec(id="gear_2")],
        shared_parameters={"center_distance": 50.0}
    )

    instruction = agent.diagnose_repair(verdict, graph, retry_count=1)
    assert instruction.target_agent == "assembly_agent"
    assert instruction.fault_type == "graph_patch"
    assert instruction.patched_graph is not None
    # 50.0 * 1.1 = 55.0
    assert instruction.patched_graph.shared_parameters["center_distance"] == 55.0


def test_triage_graph_patch_axial_stacking(agent):
    """Axial stacking collision should add axial Z offset to shared_parameters in graph."""
    diag = AssemblyDiagnostic(
        rule_id="ASSY-01",
        status="FAIL",
        parameter="interference_overlap_volume",
        measured=450.0,
        required=0.0,
        message="Axial stacking collision between base_plate and top_bracket: parts co-located on the same axis.",
        involved_parts=["base_plate", "top_bracket"]
    )
    verdict = AssemblyVerdict(passed=False, diagnostics=[diag])
    graph = AssemblyGraph(
        name="bracket_assembly",
        parts=[
            PartSpec(id="base_plate", height=15.0),
            PartSpec(id="top_bracket", height=10.0)
        ]
    )

    instruction = agent.diagnose_repair(verdict, graph, retry_count=1)
    assert instruction.target_agent == "assembly_agent"
    assert instruction.fault_type == "graph_patch"
    assert instruction.patched_graph is not None
    assert instruction.patched_graph.shared_parameters["axial_offsets"]["top_bracket"] == 15.0


def test_triage_tolerance_patch_too_tight(agent):
    """Fit clearance < 0.1mm should produce a tolerance_patch adjusting graph and part code."""
    diag = AssemblyDiagnostic(
        rule_id="ASSY-02",
        status="FAIL",
        parameter="fit_clearance_mm",
        measured=0.02,
        required=0.1,
        message="Mating clearance 0.02mm is too tight",
        involved_parts=["housing", "pin"]
    )
    verdict = AssemblyVerdict(passed=False, diagnostics=[diag])
    graph = AssemblyGraph(
        name="pin_joint",
        parts=[
            PartSpec(
                id="housing",
                mates=[MatingContext(partner_id="pin", mate_type="hole_shaft", clearance_mm=0.02, my_feature_diameter=10.0)]
            ),
            PartSpec(
                id="pin",
                mates=[MatingContext(partner_id="housing", mate_type="shaft_hole", clearance_mm=0.02, my_feature_diameter=10.0)]
            )
        ]
    )
    part_codes = {
        "housing": "import cadquery as cq\nhole_dia = 10.0\nresult = cq.Workplane('XY').box(30, 30, 10).faces('>Z').hole(hole_dia)",
        "pin": "import cadquery as cq\nshaft_dia = 9.98\nresult = cq.Workplane('XY').circle(shaft_dia/2).extrude(20)"
    }

    instruction = agent.diagnose_repair(verdict, graph, retry_count=1, part_codes=part_codes)
    assert instruction.target_agent == "assembly_agent"
    assert instruction.fault_type == "tolerance_patch"
    assert instruction.patched_graph is not None
    # Verify graph clearance adjusted
    housing_part = next(p for p in instruction.patched_graph.parts if p.id == "housing")
    assert housing_part.mates[0].clearance_mm > 0.02
    # Verify code was patched
    assert instruction.patched_code is not None
    assert "housing" in instruction.patched_code
    assert "hole_dia = 10.13" in instruction.patched_code["housing"]


def test_triage_tolerance_patch_too_loose(agent):
    """Fit clearance > 0.5mm but <= 3.0mm should produce a tolerance_patch."""
    diag = AssemblyDiagnostic(
        rule_id="ASSY-02",
        status="FAIL",
        parameter="fit_clearance_mm",
        measured=0.8,
        required=0.5,
        message="Mating clearance 0.8mm is too loose",
        involved_parts=["bush", "shaft"]
    )
    verdict = AssemblyVerdict(passed=False, diagnostics=[diag])
    graph = AssemblyGraph(
        name="bush_shaft",
        parts=[
            PartSpec(
                id="bush",
                mates=[MatingContext(partner_id="shaft", mate_type="hole_shaft", clearance_mm=0.8, my_feature_diameter=12.0)]
            ),
            PartSpec(id="shaft")
        ]
    )
    part_codes = {
        "bush": "import cadquery as cq\nbore_dia = 12.0\nresult = cq.Workplane('XY').box(20, 20, 15).faces('>Z').hole(bore_dia)"
    }

    instruction = agent.diagnose_repair(verdict, graph, retry_count=1, part_codes=part_codes)
    assert instruction.fault_type == "tolerance_patch"
    assert instruction.patched_graph is not None
    bush_part = next(p for p in instruction.patched_graph.parts if p.id == "bush")
    assert bush_part.mates[0].clearance_mm < 0.8
    assert instruction.patched_code is not None
    assert "bore_dia = 11.65" in instruction.patched_code["bush"]


def test_triage_clearance_large_displacement_positioning(agent):
    """Fit clearance > 3.0mm should be triaged as positioning fault, not tolerance."""
    diag = AssemblyDiagnostic(
        rule_id="ASSY-02",
        status="FAIL",
        parameter="fit_clearance_mm",
        measured=12.5,
        required=0.5,
        message="Parts displaced in space",
        involved_parts=["part_a", "part_b"]
    )
    verdict = AssemblyVerdict(passed=False, diagnostics=[diag])
    graph = AssemblyGraph(parts=[PartSpec(id="part_a"), PartSpec(id="part_b")])

    instruction = agent.diagnose_repair(verdict, graph, retry_count=1)
    assert instruction.target_agent == "assembly_agent"
    assert instruction.fault_type == "positioning"
    assert "Mating clearance is 12.5mm" in instruction.prompt


def test_triage_gross_solid_collision_geometry(agent):
    """Gross solid collision where one part is inside another should route to PartRepairAgent targeting container."""
    diag = AssemblyDiagnostic(
        rule_id="ASSY-01",
        status="FAIL",
        parameter="interference_overlap_volume",
        measured=50000.0,
        required=0.0,
        message="Gross solid collision: inner component immersed in outer housing. Internal cavity missing.",
        involved_parts=["housing_case", "spindle"]
    )
    verdict = AssemblyVerdict(passed=False, diagnostics=[diag])
    graph = AssemblyGraph(parts=[
        PartSpec(id="housing_case", width=100.0, length=100.0),
        PartSpec(id="spindle", width=20.0, length=20.0)
    ])

    instruction = agent.diagnose_repair(verdict, graph, retry_count=1)
    assert instruction.target_agent == "part_repair_agent"
    assert instruction.target_part_id == "housing_case"
    assert instruction.fault_type == "geometry"
    assert "internal cavity or bore" in instruction.prompt


def test_triage_escalation_exhausted_retries(agent):
    """When retries exceed 5, escalate to planner_agent."""
    verdict = AssemblyVerdict(passed=False, diagnostics=[
        AssemblyDiagnostic(
            rule_id="ASSY-01",
            status="FAIL",
            parameter="interference_overlap_volume",
            measured=10.0,
            required=0.0,
            message="Collision",
            involved_parts=["p1", "p2"]
        )
    ])
    graph = AssemblyGraph(parts=[PartSpec(id="p1"), PartSpec(id="p2")])

    instruction = agent.diagnose_repair(verdict, graph, retry_count=6)
    assert instruction.target_agent == "planner_agent"
    assert "Assembly retries exhausted" in instruction.prompt
