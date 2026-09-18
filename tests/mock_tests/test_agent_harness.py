"""
Pytest integration test for Mock Agent Harness Benchmark.
Ensures single-part defect test cases and assembly cases can execute through
the verifier and repair agent harness without unhandled exceptions or crashes.
"""

import pytest
from tests.mock_tests.single_part_cases import get_50_single_part_cases
from tests.mock_tests.assembly_cases import get_25_assembly_cases
from orchestrator.agents.part_verifier_agent import PartVerifierAgent
from orchestrator.agents.part_repair_agent import PartRepairAgent
from orchestrator.agents.assembly_agent import AssemblyAgent
from orchestrator.agents.assembly_verifier_agent import AssemblyVerifierAgent
from orchestrator.agents.assembly_repair_agent import AssemblyRepairAgent
from tools.cad_kernel import _sync_execute_cadquery


def test_mock_single_part_cases_count():
    cases = get_50_single_part_cases()
    assert len(cases) == 50


def test_mock_assembly_cases_count():
    cases = get_25_assembly_cases()
    assert len(cases) == 25


def test_single_part_parametric_repair_sample():
    cases = get_50_single_part_cases()
    # SP-01 is bracket_thin_wall (STRUCT-01)
    sp01 = next(c for c in cases if c.id == "SP-01")
    solid, err = _sync_execute_cadquery(sp01.defective_code)
    assert solid is not None
    
    verifier = PartVerifierAgent()
    verdict = verifier.verify_part_solid(solid, spec=sp01.spec)
    assert not verdict.passed
    assert any(d.rule_id == "STRUCT-01" for d in verdict.diagnostics)

    repair_agent = PartRepairAgent()
    fixed_code, was_fixed, notes = repair_agent.attempt_parametric_fix(sp01.defective_code, verdict, sp01.spec)
    assert was_fixed is True
    assert fixed_code is not None

    re_solid, re_err = _sync_execute_cadquery(fixed_code)
    assert re_solid is not None
    re_verdict = verifier.verify_part_solid(re_solid, spec=sp01.spec)
    assert re_verdict.passed is True


@pytest.mark.asyncio
async def test_assembly_repair_routing_sample():
    cases = get_25_assembly_cases()
    # ASY-01 is coaxial_discs_no_offset (axial_stacking)
    asy01 = next(c for c in cases if c.id == "ASY-01")
    
    assembly_agent = AssemblyAgent()
    verifier_agent = AssemblyVerifierAgent()
    repair_agent = AssemblyRepairAgent()

    raw_solids = {}
    for pid, code in asy01.parts_code.items():
        s, _ = _sync_execute_cadquery(code)
        raw_solids[pid] = s

    transformed, assy = await assembly_agent.assemble_parts(asy01.graph, raw_solids)
    verdict = verifier_agent.verify_assembly_solids(transformed, graph=asy01.graph)
    assert not verdict.passed

    instruction = repair_agent.diagnose_repair(verdict, asy01.graph, retry_count=1)
    assert instruction.fault_type == "graph_patch"
    assert instruction.target_agent == "assembly_agent"
    assert instruction.patched_graph is not None
