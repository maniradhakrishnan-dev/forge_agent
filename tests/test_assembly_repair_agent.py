"""
Unit tests for AssemblyRepairAgent (orchestrator/agents/assembly_repair_agent.py).
"""

from orchestrator.models import AssemblyVerdict, AssemblyDiagnostic, AssemblyGraph, PartSpec
from orchestrator.agents.assembly_repair_agent import AssemblyRepairAgent


def test_assembly_repair_routing_geometry_fault():
    agent = AssemblyRepairAgent()
    diag = AssemblyDiagnostic(
        rule_id="ASSY-01",
        status="FAIL",
        parameter="interference_overlap_volume",
        measured=5.2,
        required=0.0,
        message="Interference detected between bracket_1 and bolt_1",
        involved_parts=["bracket_1", "bolt_1"]
    )
    verdict = AssemblyVerdict(passed=False, diagnostics=[diag])
    graph = AssemblyGraph(parts=[PartSpec(id="bracket_1"), PartSpec(id="bolt_1")])

    instruction = agent.diagnose_repair(verdict, graph, retry_count=1)
    assert instruction.target_agent == "part_repair_agent"
    assert instruction.target_part_id == "bolt_1"
    assert instruction.fault_type == "geometry"


def test_assembly_repair_routing_escalation():
    agent = AssemblyRepairAgent()
    verdict = AssemblyVerdict(passed=False, diagnostics=[])
    graph = AssemblyGraph(parts=[PartSpec(id="bracket_1")])

    instruction = agent.diagnose_repair(verdict, graph, retry_count=6)
    assert instruction.target_agent == "planner_agent"


def test_assembly_repair_routing_gross_solid_collision():
    agent = AssemblyRepairAgent()
    diag = AssemblyDiagnostic(
        rule_id="ASSY-01",
        status="FAIL",
        parameter="interference_overlap_volume",
        measured=32000.0,
        required=0.0,
        message="Gross solid collision between 'cup_housing' and 'inner_rotor': 90.0% volume overlap. Ensure internal cavity is hollow.",
        involved_parts=["cup_housing", "inner_rotor"]
    )
    verdict = AssemblyVerdict(passed=False, diagnostics=[diag])
    # cup_housing is the larger container
    graph = AssemblyGraph(parts=[
        PartSpec(id="cup_housing", width=80.0, length=80.0),
        PartSpec(id="inner_rotor", width=40.0, length=40.0)
    ])

    instruction = agent.diagnose_repair(verdict, graph, retry_count=1)
    assert instruction.target_agent == "part_repair_agent"
    assert instruction.target_part_id == "cup_housing"
    assert "internal cavity or bore" in instruction.prompt


def test_assembly_repair_routing_axial_stacking_collision():
    agent = AssemblyRepairAgent()
    diag = AssemblyDiagnostic(
        rule_id="ASSY-01",
        status="FAIL",
        parameter="interference_overlap_volume",
        measured=25000.0,
        required=0.0,
        message="Axial stacking collision between 'disc_a' and 'plate_b': parts co-located on the same axis with 15.0 mm axial overlap.",
        involved_parts=["disc_a", "plate_b"]
    )
    verdict = AssemblyVerdict(passed=False, diagnostics=[diag])
    graph = AssemblyGraph(parts=[PartSpec(id="disc_a"), PartSpec(id="plate_b")])

    instruction = agent.diagnose_repair(verdict, graph, retry_count=1)
    assert instruction.target_agent == "assembly_agent"
    assert instruction.fault_type == "graph_patch"
    assert instruction.patched_graph is not None

