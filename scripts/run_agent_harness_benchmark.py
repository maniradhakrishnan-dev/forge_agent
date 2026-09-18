"""
Comprehensive Zero-LLM Agent Harness Stress-Testing Benchmark.

Tests ForgeAgent harness across:
1. 50 Single-Part Defect Cases (SP-01 to SP-50)
2. 25 Multi-Part Assembly Defect Cases (ASY-01 to ASY-25)

Evaluates:
- Verifier detection fidelity
- Zero-LLM repair capabilities (parametric variable editing, syntax/BRep regex healing, assembly graph patching)
- Escalation routing and diagnostic instruction precision
- System limitations and edge cases
"""

import sys
import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List

# Ensure repo root is in python path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from tests.mock_tests.single_part_cases import get_50_single_part_cases, SinglePartTestCase
from tests.mock_tests.assembly_cases import get_25_assembly_cases, AssemblyTestCase
from orchestrator.agents.part_verifier_agent import PartVerifierAgent
from orchestrator.agents.part_repair_agent import PartRepairAgent
from orchestrator.agents.assembly_agent import AssemblyAgent
from orchestrator.agents.assembly_verifier_agent import AssemblyVerifierAgent
from orchestrator.agents.assembly_repair_agent import AssemblyRepairAgent
from tools.cad_kernel import _sync_execute_cadquery


def run_single_part_benchmark() -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("RUNNING BENCHMARK PART 1: 50 SINGLE-PART DEFECT TEST CASES")
    print("=" * 80)

    cases = get_50_single_part_cases()
    verifier = PartVerifierAgent()
    repair_agent = PartRepairAgent()

    results = []
    stats = {
        "total": len(cases),
        "initial_execution_success": 0,
        "initial_execution_failed": 0,
        "syntax_fix_attempted": 0,
        "syntax_fix_succeeded": 0,
        "verifier_caught_defect": 0,
        "verifier_missed_defect": 0,
        "parametric_fix_attempted": 0,
        "parametric_fix_succeeded": 0,
        "escalated_to_designer": 0,
        "diagnostic_instruction_generated": 0,
        "by_category": {}
    }

    for case in cases:
        cat = case.category
        if cat not in stats["by_category"]:
            stats["by_category"][cat] = {
                "total": 0,
                "detected": 0,
                "zero_llm_fixed": 0,
                "escalated": 0
            }
        stats["by_category"][cat]["total"] += 1

        case_record = {
            "id": case.id,
            "name": case.name,
            "category": case.category,
            "expected_rule": case.expected_rule_fail,
            "detected": False,
            "detected_rules": [],
            "syntax_fixed": False,
            "parametric_fixed": False,
            "escalated": False,
            "notes": ""
        }

        # Step 1: Initial CadQuery execution
        solid, err = _sync_execute_cadquery(case.defective_code)
        active_code = case.defective_code

        if err:
            stats["initial_execution_failed"] += 1
            # Attempt syntax/BRep fix
            stats["syntax_fix_attempted"] += 1
            fixed_code, was_fixed, fix_notes = repair_agent.attempt_syntax_fix(case.defective_code, err)
            if was_fixed and fixed_code:
                active_code = fixed_code
                solid2, err2 = _sync_execute_cadquery(fixed_code)
                if solid2:
                    solid = solid2
                    case_record["syntax_fixed"] = True
                    stats["syntax_fix_succeeded"] += 1
                    case_record["notes"] += f"Syntax fixed: {', '.join(fix_notes)}. "
                else:
                    case_record["notes"] += f"Syntax fix failed re-exec: {err2[:80]}. "
            else:
                case_record["notes"] += f"Execution error: {err[:80]}. "
        else:
            stats["initial_execution_success"] += 1

        if not solid:
            # If still not executable, this is either caught as PHYS-01 / CADKernel error
            case_record["detected"] = True
            case_record["detected_rules"] = ["PHYS-01"]
            stats["verifier_caught_defect"] += 1
            stats["by_category"][cat]["detected"] += 1
            stats["escalated_to_designer"] += 1
            stats["by_category"][cat]["escalated"] += 1
            case_record["escalated"] = True
            # Generate syntax repair instruction
            instr = repair_agent.generate_syntax_repair_instructions(err or "Failed solid creation", case.defective_code)
            stats["diagnostic_instruction_generated"] += 1
            results.append(case_record)
            print(f"[{case.id}] {case.name} ({case.category}) -> EXEC_FAIL -> Syntax Instruction Generated")
            continue

        # Step 2: Verification
        verdict = verifier.verify_part_solid(
            solid,
            spec=case.spec,
            process=case.spec.manufacturing_process,
            depth=case.spec.verification_depth
        )

        failed_rules = [d.rule_id for d in verdict.diagnostics if d.status == "FAIL"]
        case_record["detected_rules"] = failed_rules

        if not verdict.passed:
            case_record["detected"] = True
            stats["verifier_caught_defect"] += 1
            stats["by_category"][cat]["detected"] += 1

            # Step 3: Attempt zero-LLM parametric repair
            stats["parametric_fix_attempted"] += 1
            fixed_code, was_fixed, p_notes = repair_agent.attempt_parametric_fix(active_code, verdict, case.spec)

            if was_fixed and fixed_code:
                # Re-execute and re-verify
                re_solid, re_err = _sync_execute_cadquery(fixed_code)
                if re_solid:
                    re_verdict = verifier.verify_part_solid(
                        re_solid,
                        spec=case.spec,
                        process=case.spec.manufacturing_process,
                        depth=case.spec.verification_depth
                    )
                    if re_verdict.passed:
                        case_record["parametric_fixed"] = True
                        stats["parametric_fix_succeeded"] += 1
                        stats["by_category"][cat]["zero_llm_fixed"] += 1
                        case_record["notes"] += f"Zero-LLM Parametric Repair PASSED: {', '.join(p_notes)}."
                    else:
                        remaining = [d.rule_id for d in re_verdict.diagnostics if d.status == "FAIL"]
                        case_record["notes"] += f"Parametric fix applied but failed rules remain: {remaining}. "
                        stats["escalated_to_designer"] += 1
                        stats["by_category"][cat]["escalated"] += 1
                        case_record["escalated"] = True
                else:
                    case_record["notes"] += f"Parametric fix resulted in exec error: {re_err[:80]}. "
                    stats["escalated_to_designer"] += 1
                    stats["by_category"][cat]["escalated"] += 1
                    case_record["escalated"] = True
            else:
                stats["escalated_to_designer"] += 1
                stats["by_category"][cat]["escalated"] += 1
                case_record["escalated"] = True
                instr = repair_agent.generate_repair_instructions(verdict)
                stats["diagnostic_instruction_generated"] += 1
                case_record["notes"] += f"Escalated to Designer: {', '.join(p_notes) if p_notes else 'No parametric fix available'}."

            status_str = "FIXED_PARAMETRIC" if case_record["parametric_fixed"] else "ESCALATED_DESIGNER"
            print(f"[{case.id}] {case.name} ({case.category}) -> DETECTED ({failed_rules}) -> {status_str}")
        else:
            stats["verifier_missed_defect"] += 1
            case_record["notes"] += f"MISSED: Verifier passed despite expected {case.expected_rule_fail}!"
            print(f"[{case.id}] {case.name} ({case.category}) -> MISSED_DEFECT (Passed all verifier rules)")

        results.append(case_record)

    return {"stats": stats, "results": results}


async def run_assembly_benchmark() -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("RUNNING BENCHMARK PART 2: 25 ASSEMBLY DEFECT TEST CASES")
    print("=" * 80)

    cases = get_25_assembly_cases()
    assembly_agent = AssemblyAgent()
    verifier_agent = AssemblyVerifierAgent()
    repair_agent = AssemblyRepairAgent()

    results = []
    stats = {
        "total": len(cases),
        "verifier_caught_fault": 0,
        "verifier_missed_fault": 0,
        "routed_graph_patch": 0,
        "routed_tolerance_patch": 0,
        "routed_geometry": 0,
        "routed_positioning": 0,
        "resolved_by_graph_patch": 0,
        "by_category": {}
    }

    for case in cases:
        cat = case.category
        if cat not in stats["by_category"]:
            stats["by_category"][cat] = {
                "total": 0,
                "detected": 0,
                "routed_graph_patch": 0,
                "routed_tolerance_patch": 0,
                "routed_geometry": 0,
                "routed_positioning": 0,
                "resolved_graph_patch": 0
            }
        stats["by_category"][cat]["total"] += 1

        case_record = {
            "id": case.id,
            "name": case.name,
            "category": case.category,
            "expected_fault": case.expected_fault_type,
            "detected": False,
            "failing_rules": [],
            "routed_target": "",
            "routed_fault": "",
            "graph_patch_resolved": False,
            "notes": ""
        }

        # Step 1: Execute all part scripts to obtain raw solids
        raw_solids = {}
        exec_failed = False
        for part_id, pcode in case.parts_code.items():
            s, err = _sync_execute_cadquery(pcode)
            if s:
                raw_solids[part_id] = s
            else:
                exec_failed = True
                case_record["notes"] += f"Part {part_id} exec failed: {err}. "

        if exec_failed or len(raw_solids) != len(case.parts_code):
            case_record["detected"] = True
            stats["verifier_caught_fault"] += 1
            stats["by_category"][cat]["detected"] += 1
            stats["routed_geometry"] += 1
            stats["by_category"][cat]["routed_geometry"] += 1
            case_record["routed_fault"] = "geometry"
            results.append(case_record)
            print(f"[{case.id}] {case.name} ({case.category}) -> RAW_PART_EXEC_FAIL")
            continue

        # Step 2: Assemble parts
        transformed_solids, cq_assembly = await assembly_agent.assemble_parts(
            case.graph,
            raw_solids,
            interfaces=case.interfaces
        )

        # Step 3: Verify assembly
        verdict = verifier_agent.verify_assembly_solids(
            transformed_solids,
            joints=case.graph.joints,
            graph=case.graph,
            interfaces=case.interfaces
        )

        failed_diags = [d for d in verdict.diagnostics if d.status == "FAIL"]
        case_record["failing_rules"] = [f"{d.rule_id} ({d.parameter}: {d.measured})" for d in failed_diags]

        if not verdict.passed:
            case_record["detected"] = True
            stats["verifier_caught_fault"] += 1
            stats["by_category"][cat]["detected"] += 1

            # Step 4: Run AssemblyRepairAgent diagnosis
            instruction = repair_agent.diagnose_repair(
                verdict,
                case.graph,
                retry_count=1,
                part_codes=case.parts_code
            )

            case_record["routed_target"] = instruction.target_agent
            case_record["routed_fault"] = instruction.fault_type

            if instruction.fault_type == "graph_patch":
                stats["routed_graph_patch"] += 1
                stats["by_category"][cat]["routed_graph_patch"] += 1

                # Step 5: Test if the graph patch actually resolves the assembly defect
                if instruction.patched_graph:
                    p_solids, p_assy = await assembly_agent.assemble_parts(
                        instruction.patched_graph,
                        raw_solids,
                        interfaces=case.interfaces
                    )
                    re_verdict = verifier_agent.verify_assembly_solids(
                        p_solids,
                        joints=instruction.patched_graph.joints,
                        graph=instruction.patched_graph,
                        interfaces=case.interfaces
                    )
                    if re_verdict.passed:
                        case_record["graph_patch_resolved"] = True
                        stats["resolved_by_graph_patch"] += 1
                        stats["by_category"][cat]["resolved_graph_patch"] += 1
                        case_record["notes"] += "Graph patch completely resolved assembly collision! "
                    else:
                        case_record["notes"] += f"Graph patch re-verification still failed: {[d.rule_id for d in re_verdict.diagnostics if d.status == 'FAIL']}. "

            elif instruction.fault_type == "tolerance_patch":
                stats["routed_tolerance_patch"] += 1
                stats["by_category"][cat]["routed_tolerance_patch"] += 1
                case_record["notes"] += f"Routed to tolerance patch: {instruction.prompt[:100]}... "

            elif instruction.fault_type == "geometry":
                stats["routed_geometry"] += 1
                stats["by_category"][cat]["routed_geometry"] += 1
                case_record["notes"] += f"Routed to geometry repair: {instruction.prompt[:100]}... "

            elif instruction.fault_type == "positioning":
                stats["routed_positioning"] += 1
                stats["by_category"][cat]["routed_positioning"] += 1
                case_record["notes"] += f"Routed to positioning repair: {instruction.prompt[:100]}... "

            print(f"[{case.id}] {case.name} ({case.category}) -> FAULT_DETECTED -> Routed to {instruction.target_agent} ({instruction.fault_type})")
        else:
            stats["verifier_missed_fault"] += 1
            case_record["notes"] += "MISSED: Assembly verifier passed despite intentional defect!"
            print(f"[{case.id}] {case.name} ({case.category}) -> MISSED_FAULT (Passed all verifier rules)")

        results.append(case_record)

    return {"stats": stats, "results": results}


async def async_main():
    start_time = time.time()

    sp_data = run_single_part_benchmark()
    assy_data = await run_assembly_benchmark()

    elapsed = round(time.time() - start_time, 2)

    output_dir = repo_root / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "agent_harness_benchmark_results.json"

    full_report = {
        "execution_time_seconds": elapsed,
        "single_part": sp_data,
        "assembly": assy_data
    }

    json_path.write_text(json.dumps(full_report, indent=2), encoding="utf-8")
    print("\n" + "=" * 80)
    print(f"BENCHMARK COMPLETED IN {elapsed}s")
    print(f"Saved structured raw results to: {json_path}")
    print("=" * 80)

    # Print Executive Summary Table
    sp_s = sp_data["stats"]
    print("\n--- SINGLE-PART SUMMARY (50 CASES) ---")
    print(f"Total Cases:                 {sp_s['total']}")
    print(f"Defect Detection Rate:       {sp_s['verifier_caught_defect']}/{sp_s['total']} ({sp_s['verifier_caught_defect']/sp_s['total']*100:.1f}%)")
    print(f"Zero-LLM Parametric Fixed:   {sp_s['parametric_fix_succeeded']}/{sp_s['verifier_caught_defect']} ({sp_s['parametric_fix_succeeded']/max(sp_s['verifier_caught_defect'], 1)*100:.1f}%)")
    print(f"Zero-LLM Syntax Fixed:       {sp_s['syntax_fix_succeeded']}/{max(sp_s['syntax_fix_attempted'], 1)}")
    print(f"Escalated to Designer (LLM): {sp_s['escalated_to_designer']}")
    print(f"Actionable Prompt Generated: {sp_s['diagnostic_instruction_generated']}")

    assy_s = assy_data["stats"]
    print("\n--- ASSEMBLY SUMMARY (25 CASES) ---")
    print(f"Total Cases:                 {assy_s['total']}")
    print(f"Fault Detection Rate:        {assy_s['verifier_caught_fault']}/{assy_s['total']} ({assy_s['verifier_caught_fault']/assy_s['total']*100:.1f}%)")
    print(f"Routed to Graph Patch:       {assy_s['routed_graph_patch']}")
    print(f"Resolved by Graph Patch:     {assy_s['resolved_by_graph_patch']}")
    print(f"Routed to Tolerance Patch:   {assy_s['routed_tolerance_patch']}")
    print(f"Routed to Geometry Repair:   {assy_s['routed_geometry']}")
    print(f"Routed to Positioning:       {assy_s['routed_positioning']}")


def main():
    import asyncio
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
