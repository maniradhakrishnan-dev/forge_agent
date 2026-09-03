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
    assert instruction.target_agent == "code_generator_agent"
    assert instruction.target_part_id == "bolt_1"
    assert instruction.fault_type == "geometry"


def test_assembly_repair_routing_escalation():
    agent = AssemblyRepairAgent()
    verdict = AssemblyVerdict(passed=False, diagnostics=[])
    graph = AssemblyGraph(parts=[PartSpec(id="bracket_1")])

    instruction = agent.diagnose_repair(verdict, graph, retry_count=6)
    assert instruction.target_agent == "planner_agent"
