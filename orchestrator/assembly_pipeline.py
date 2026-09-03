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
from typing import Dict, Any, List, Tuple, Optional
from orchestrator.gateway_client import GatewayClient
from orchestrator.models import (
    AssemblyGraph,
    PartSpec,
    DesignerOutput,
    VerificationVerdict,
    AssemblyVerdict,
    ValidationResult,
    RepairInstruction
)
from orchestrator.run_logger import RunLogger
from orchestrator.agents.planner_agent import PlannerAgent
from orchestrator.agents.assembly_agent import AssemblyAgent
from orchestrator.agents.assembly_verifier_agent import AssemblyVerifierAgent
from orchestrator.agents.assembly_repair_agent import AssemblyRepairAgent
from orchestrator.constraint_validator import ConstraintValidator
from orchestrator.part_pipeline import run_part_pipeline
from tools.cad_kernel import export_cad_artifacts


async def run_full_assembly_pipeline(
    prompt: str,
    output_dir: str = "artifacts/assembly_run",
    max_part_retries: int = 3,
    max_assembly_retries: int = 3,
    gateway_client: Optional[GatewayClient] = None,
    run_id: Optional[str] = None
) -> Tuple[bool, AssemblyGraph, AssemblyVerdict, Dict[str, Any], Dict[str, Dict[str, str]]]:
    """
    Executes full multi-part assembly design, verification, and diagnostic repair pipeline.
    """
    run_id = run_id or str(uuid.uuid4())[:8]
    logger = RunLogger(run_id=run_id, output_dir=output_dir)
    gw = gateway_client or GatewayClient()

    planner = PlannerAgent(gw)
    assembler = AssemblyAgent(gw)
    verifier = AssemblyVerifierAgent()
    repair_router = AssemblyRepairAgent(gw)

    # 1. Planner Agent decomposes prompt -> AssemblyGraph with ConstraintValidator retry loop
    print(f"\n[Phase 1/4] 🧠 Decomposing prompt into AssemblyGraph...")
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

        # 2. Constraint Validator checks pre-design consistency
        val_res = ConstraintValidator.validate(graph)
        if val_res.valid:
            logger.log_step(agent="constraint_validator", iteration=plan_iter, status="PASS")
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

    # 3. Parallel Part Generation for all parts in AssemblyGraph
    print(f"\n[Phase 2/4] ⚙️  Designing & verifying {len(graph.parts)} parts concurrently {[p.name for p in graph.parts]}...")
    shared_params = graph.shared_parameters or graph.master_skeleton
    part_tasks = [
        run_part_pipeline(
            spec=part_spec,
            output_dir=output_dir,
            max_retries=max_part_retries,
            gateway_client=gw,
            run_logger=logger,
            master_skeleton=shared_params
        )
        for part_spec in graph.parts
    ]

    results = await asyncio.gather(*part_tasks)

    designer_outputs: Dict[str, DesignerOutput] = {}
    verified_solids: Dict[str, Any] = {}
    interfaces: Dict[str, Dict[str, Any]] = {}
    part_artifacts: Dict[str, Dict[str, str]] = {}

    for part_spec, (passed, designer_out, verdict, solid_obj, artifacts) in zip(graph.parts, results):
        if passed and designer_out:
            designer_outputs[part_spec.id] = designer_out
            verified_solids[part_spec.id] = solid_obj
            interfaces[part_spec.id] = designer_out.interfaces
            part_artifacts[part_spec.id] = artifacts
        else:
            logger.log_step(agent="assembly_pipeline", status="FAIL", diagnostics=[f"Part '{part_spec.id}' failed single-part DFM."])
            logger.generate_summary_markdown(prompt, False)
            return False, graph, AssemblyVerdict(passed=False), {}, {}

    # 4. Multi-Part Assembly & Verification Loop
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
        final_verdict = verifier.verify_assembly_solids(transformed_solids, joints=graph.joints)
        ver_status = "PASS" if final_verdict.passed else "FAIL"
        logger.log_step(
            agent="assembly_verifier_agent",
            iteration=assy_iter,
            status=ver_status,
            diagnostics=[d.model_dump() for d in final_verdict.diagnostics],
            latency_ms=(time.time() - t_ver) * 1000
        )

        if final_verdict.passed:
            # 5. Export assembled STEP/STL artifacts on success
            print(f"\n[Phase 4/4] 💾 Exporting multi-part assembly CAD artifacts...")
            if cq_assembly:
                assy_artifacts = await export_cad_artifacts(cq_assembly, output_dir, graph.name)
                part_artifacts["assembly"] = assy_artifacts
            logger.log_step(agent="reporter_agent", iteration=assy_iter, status="PASS")
            logger.generate_summary_markdown(prompt, True)
            return True, graph, final_verdict, transformed_solids, part_artifacts

        else:
            # 6. Assembly Repair Diagnostic Router
            instruction = repair_router.diagnose_repair(final_verdict, graph, retry_count=assy_iter)
            logger.log_step(agent="assembly_repair_agent", iteration=assy_iter, status="FAIL", diagnostics=[instruction.model_dump()])

            if instruction.fault_type == "positioning":
                pos_repair_prompt = instruction.prompt
            elif instruction.fault_type == "geometry" and instruction.target_part_id in designer_outputs:
                # Target re-generation of specific faulty part
                target_spec = next((p for p in graph.parts if p.id == instruction.target_part_id), None)
                if target_spec:
                    p_passed, p_out, p_ver, p_solid, p_art = await run_part_pipeline(
                        spec=target_spec,
                        output_dir=output_dir,
                        max_retries=2,
                        gateway_client=gw,
                        run_logger=logger,
                        master_skeleton=shared_params
                    )
                    if p_passed and p_out:
                        designer_outputs[target_spec.id] = p_out
                        verified_solids[target_spec.id] = p_solid
                        interfaces[target_spec.id] = p_out.interfaces

    logger.log_step(agent="full_assembly_pipeline", status="ESCALATE")
    logger.generate_summary_markdown(prompt, False)
    return False, graph, final_verdict, transformed_solids, part_artifacts
