"""
Multi-Part Assembly Orchestrator Pipeline (ForgeAgent).
Complete End-to-End Multi-Agent Assembly Pipeline:
1. Planner Agent decomposes spec -> AssemblyGraph (with process, depth, mates, joints)
2. ConstraintValidator checks pre-design consistency
3. Parallel part generation via asyncio.gather(*[run_part_pipeline(...)])
4. Assembly Agent mates verified solids into cq.Assembly() using InterfacePorts
5. Assembly Verifier Agent verifies ground-truth math (Interference == 0, Fit Clearance, Kinematics)
6. Assembly Repair Diagnostic Router routes targeted repair payloads on failure
7. Artifact Export (Assembled STEP/STL) & Structured Run Logging
"""

import time
import uuid
import asyncio
from typing import Dict, Any, Tuple, Optional
from orchestrator.gateway_client import GatewayClient
from orchestrator.models import (
    AssemblyGraph,
    DesignerOutput,
    AssemblyVerdict,
)
from orchestrator.run_logger import RunLogger
from orchestrator.agents.planner_agent import PlannerAgent
from orchestrator.agents.assembly_agent import AssemblyAgent
from orchestrator.agents.assembly_verifier_agent import AssemblyVerifierAgent
from orchestrator.agents.assembly_repair_agent import AssemblyRepairAgent
from orchestrator.agents.constraint_validator import ConstraintValidator
from orchestrator.live_graph.planner import LiveCADPlanner
from orchestrator.part_pipeline import run_part_pipeline
from tools.cad_kernel import export_cad_artifacts, execute_cadquery_code


async def run_full_assembly_pipeline(
    prompt: str,
    output_dir: str = "artifacts/assembly_run",
    process: Optional[str] = None,
    depth: Optional[str] = None,
    max_part_retries: int = 5,
    max_assembly_retries: int = 3,
    gateway_client: Optional[GatewayClient] = None,
    run_id: Optional[str] = None,
    run_logger: Optional[RunLogger] = None
) -> Tuple[bool, AssemblyGraph, AssemblyVerdict, Dict[str, Any], Dict[str, Dict[str, str]]]:
    """
    Complete end-to-end multi-agent assembly pipeline driven by dynamic mechanism classification:
    Prompt -> PlannerAgent -> ConstraintValidator -> Dynamic Execution Plan (Waves) -> AssemblyAgent -> AssemblyVerifierAgent -> Export
    """
    gw = gateway_client or GatewayClient()
    logger = run_logger or RunLogger(run_id=run_id or str(uuid.uuid4())[:8], output_dir=output_dir)

    planner = PlannerAgent(gw)
    assembler = AssemblyAgent(gw)
    verifier = AssemblyVerifierAgent()
    repair_router = AssemblyRepairAgent(gw)

    # 1. Planner Agent decomposes user prompt into AssemblyGraph
    print(f"\n[Phase 1/4] 🧠 Decomposing prompt into AssemblyGraph via PlannerAgent...")
    max_planning_retries = 3
    graph = None
    validation_errors = None

    for plan_iter in range(1, max_planning_retries + 1):
        t0 = time.time()
        graph = await planner.plan_assembly(prompt, validation_errors=validation_errors)
        logger.log_step(
            agent="planner_agent",
            iteration=plan_iter,
            status="PASS",
            latency_ms=(time.time() - t0) * 1000
        )

        # Apply CLI process/depth overrides if provided
        if process:
            p_lower = prompt.lower()
            prompt_has_explicit_process = any(
                kw in p_lower for kw in ["sheet metal", "cnc", "machin", "lathe", "milled", "3d print", "additive"]
            )
            for p in graph.parts:
                if not prompt_has_explicit_process or not getattr(p, "manufacturing_process", None):
                    p.manufacturing_process = process
        if depth:
            for p in graph.parts:
                p.verification_depth = depth


        # 2. Constraint Validator checks pre-design consistency
        val_res = ConstraintValidator.validate(graph)
        if val_res.valid:
            logger.log_step(agent="constraint_validator", iteration=plan_iter, status="PASS")
            # Persist the assembly graph and per-part specifications as typed contracts on disk
            try:
                graph.to_json_file(f"{output_dir}/assembly_graph.json")
                for p_spec in graph.parts:
                    p_spec.to_json_file(f"{output_dir}/{p_spec.id}/spec.json")
            except Exception as e:
                print(f"  ⚠️  Warning persisting assembly specs: {e}")
            break
        else:
            print(f"  ⚠️  [ConstraintValidator] Consistency check failed (Attempt {plan_iter}/{max_planning_retries}):")
            for err in val_res.errors:
                print(f"     • {err}")
            logger.log_step(agent="constraint_validator", iteration=plan_iter, status="FAIL", diagnostics=val_res.errors)
            validation_errors = val_res.errors
            if plan_iter == max_planning_retries:
                logger.generate_summary_markdown(prompt, False)
                return False, graph, AssemblyVerdict(passed=False), {}, {}
            print(f"  🔧 Feeding validation errors back to PlannerAgent for self-correction...")

    # 3. Dynamic Live Graph Execution: Reactive Topological Dispatch
    live_planner = LiveCADPlanner(graph)
    print(f"\n[Phase 2/4] 🚀 Reactive Live Graph: Designing {len(graph.parts)} parts dynamically from physical interface events...")

    part_map = {p.id: p for p in graph.parts}
    designer_outputs: Dict[str, DesignerOutput] = {}
    verified_solids: Dict[str, Any] = {}
    interfaces: Dict[str, Dict[str, Any]] = {}
    part_artifacts: Dict[str, Dict[str, str]] = {}

    remaining_parts = set(part_map.keys())
    running_tasks: Dict[asyncio.Task, str] = {}
    sem = asyncio.Semaphore(2)

    async def _execute_part(ps, dp):
        async with sem:
            shared_params = graph.shared_parameters if graph.shared_parameters is not None else graph.master_skeleton
            return await run_part_pipeline(
                spec=ps,
                output_dir=output_dir,
                max_retries=max_part_retries,
                gateway_client=gw,
                run_logger=logger,
                master_skeleton=shared_params,
                partner_interfaces=dp if dp else None,
            )

    while remaining_parts or running_tasks:
        # Identify ready parts whose prerequisite interface dependencies are proven
        ready_parts = [
            pid for pid in list(remaining_parts)
            if live_planner.deps.get(pid, set()).issubset(interfaces.keys())
        ]

        for pid in ready_parts:
            remaining_parts.remove(pid)
            part_spec = part_map[pid]
            dep_ports = {
                dep_id: interfaces[dep_id]
                for dep_id in live_planner.deps.get(pid, set())
                if dep_id in interfaces
            }

            t = asyncio.create_task(_execute_part(part_spec, dep_ports))
            running_tasks[t] = pid
            print(f"  ⚡ [LiveGraph] Dispatched part '{pid}' (Prerequisites: {list(dep_ports.keys()) or 'None (Root Datum)'})")

        if not running_tasks:
            if remaining_parts:
                next_pid = remaining_parts.pop()
                print(f"  ⚠️ [LiveGraph] Breaking dependency cycle on '{next_pid}'")
                part_spec = part_map[next_pid]
                dep_ports = {dep_id: interfaces[dep_id] for dep_id in interfaces}
                t = asyncio.create_task(_execute_part(part_spec, dep_ports))
                running_tasks[t] = next_pid
            else:
                break

        done, _ = await asyncio.wait(running_tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
        for completed_task in done:
            pid = running_tasks.pop(completed_task)
            res = completed_task.result()
            passed, designer_out, verdict, solid_obj, artifacts = res[0], res[1], res[2], res[3], res[4]
            if passed and designer_out:
                designer_outputs[pid] = designer_out
                verified_solids[pid] = solid_obj
                interfaces[pid] = designer_out.interfaces
                part_artifacts[pid] = artifacts
                print(f"  ✅ [LiveGraph] Part '{pid}' passed physical verification; recorded interface ports: {list(designer_out.interfaces.keys())}")
            else:
                logger.log_step(agent="assembly_pipeline", status="FAIL", diagnostics=[f"Part '{pid}' failed single-part DFM in live graph."])
                logger.generate_summary_markdown(prompt, False)
                return False, graph, AssemblyVerdict(passed=False), {}, {}

    # 4. Single-Part vs Multi-Part Branching
    if len(graph.parts) == 1:
        # Standalone single-part specification: already verified via 6-pillar DFM
        pid = graph.parts[0].id
        p_artifacts = part_artifacts.get(pid, {})
        from pathlib import Path
        root_spec = Path(output_dir) / "spec.json"
        if not root_spec.exists():
            graph.parts[0].to_json_file(root_spec)
        logger.log_step(agent="reporter_agent", iteration=1, status="PASS")
        logger.generate_summary_markdown(prompt, True)
        return True, graph, AssemblyVerdict(passed=True), verified_solids, part_artifacts

    # Multi-Part Assembly & Verification Loop
    print(f"\n[Phase 3/4] 🧩 Mating parts and verifying 3D spatial alignment...")
    final_verdict = AssemblyVerdict(passed=False)
    transformed_solids: Dict[str, Any] = {}
    cq_assembly: Any = None

    pos_repair_prompt = ""
    for assy_iter in range(1, max_assembly_retries + 1):
        # Assemble parts via InterfacePorts
        t_assy = time.time()
        transformed_solids, cq_assembly = await assembler.assemble_parts(
            graph, verified_solids, interfaces, positioning_repair_prompt=pos_repair_prompt
        )
        logger.log_step(agent="assembly_agent", iteration=assy_iter, status="PASS", latency_ms=(time.time() - t_assy) * 1000)

        # Run Assembly Verifier checks (Interference, Fit Clearance, Kinematics)
        t_ver = time.time()
        final_verdict = verifier.verify_assembly_solids(
            transformed_solids,
            joints=graph.joints,
            graph=graph,
            interfaces=interfaces
        )
        ver_status = "PASS" if final_verdict.passed else "FAIL"
        logger.log_step(
            agent="assembly_verifier_agent",
            iteration=assy_iter,
            status=ver_status,
            diagnostics=[d.model_dump() for d in final_verdict.diagnostics],
            latency_ms=(time.time() - t_ver) * 1000
        )

        if final_verdict.passed:
            # 5. Export assembled STEP/STL and Python assembly script artifacts on success
            print(f"\n[Phase 4/4] 💾 Exporting multi-part assembly CAD artifacts...")
            if cq_assembly:
                assy_code = assembler.generate_assembly_script(graph, output_dir)
                assy_artifacts = await export_cad_artifacts(cq_assembly, output_dir, graph.name, code=assy_code, spec=graph)
                part_artifacts["assembly"] = assy_artifacts
            logger.log_step(agent="reporter_agent", iteration=assy_iter, status="PASS")
            logger.generate_summary_markdown(prompt, True)
            return True, graph, final_verdict, transformed_solids, part_artifacts

        else:
            # 6. Assembly Repair Diagnostic Router (3-way triage: graph_patch, tolerance_patch, geometry)
            part_codes_map = {pid: d.code for pid, d in designer_outputs.items()}
            instruction = repair_router.diagnose_repair(
                final_verdict, graph, retry_count=assy_iter, part_codes=part_codes_map
            )
            logger.log_step(agent="assembly_repair_agent", iteration=assy_iter, status="FAIL", diagnostics=[instruction.model_dump()])

            if instruction.fault_type == "graph_patch":
                print(f"  🔧 [AssemblyRepair] Direct graph patch applied (zero LLM): {instruction.prompt}")
                pos_repair_prompt = instruction.prompt
                if instruction.patched_graph:
                    graph = instruction.patched_graph
                    try:
                        graph.to_json_file(f"{output_dir}/assembly_graph.json")
                        for p in graph.parts:
                            p.to_json_file(f"{output_dir}/{p.id}/spec.json")
                    except Exception:
                        pass
            elif instruction.fault_type == "tolerance_patch":
                print(f"  🔧 [AssemblyRepair] Direct tolerance patch applied (zero LLM): {instruction.prompt}")
                if instruction.patched_graph:
                    graph = instruction.patched_graph
                    try:
                        graph.to_json_file(f"{output_dir}/assembly_graph.json")
                        for p in graph.parts:
                            p.to_json_file(f"{output_dir}/{p.id}/spec.json")
                    except Exception:
                        pass
                if instruction.patched_code:
                    for pid, fixed_code in instruction.patched_code.items():
                        solid, err = await execute_cadquery_code(fixed_code)
                        if not err and solid:
                            verified_solids[pid] = solid
                            if pid in designer_outputs:
                                designer_outputs[pid].code = fixed_code
            elif instruction.fault_type == "positioning":
                pos_repair_prompt = instruction.prompt
            elif instruction.fault_type == "geometry" and instruction.target_part_id in designer_outputs:
                # Target re-generation of specific faulty part (parametric fix attempted first in part_pipeline)
                target_spec = next((p for p in graph.parts if p.id == instruction.target_part_id), None)
                if target_spec:
                    prev_c = designer_outputs[target_spec.id].code if target_spec.id in designer_outputs else None
                    p_passed, p_out, p_ver, p_solid, p_art = await run_part_pipeline(
                        spec=target_spec,
                        output_dir=output_dir,
                        max_retries=2,
                        gateway_client=gw,
                        run_logger=logger,
                        master_skeleton=graph.shared_parameters if graph.shared_parameters is not None else graph.master_skeleton,
                        initial_code=prev_c,
                        user_modification_prompt=instruction.prompt
                    )
                    if p_passed and p_out:
                        designer_outputs[target_spec.id] = p_out
                        verified_solids[target_spec.id] = p_solid
                        interfaces[target_spec.id] = p_out.interfaces

    logger.log_step(agent="full_assembly_pipeline", status="ESCALATE")
    logger.generate_summary_markdown(prompt, False)
    return False, graph, final_verdict, transformed_solids, part_artifacts
