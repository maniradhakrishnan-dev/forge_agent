"""
Single-Part Concurrent Pipeline Engine (ForgeAgent).
Executes Design -> Sandbox -> 6-Pillar Part Verifier -> (Part Repair) loop asynchronously for a single part.
"""

import time
import uuid
from typing import Dict, Any, Tuple, Optional, List
from orchestrator.gateway_client import GatewayClient
from orchestrator.models import PartSpec, DesignerOutput, VerificationVerdict, InterfacePort
from orchestrator.run_logger import RunLogger
from orchestrator.agents.planner_agent import PlannerAgent
from orchestrator.agents.code_generator_agent import CodeGeneratorAgent
from orchestrator.agents.part_verifier_agent import PartVerifierAgent
from orchestrator.agents.part_repair_agent import PartRepairAgent
from tools.cad_kernel import execute_cadquery_code, export_cad_artifacts


async def run_part_pipeline(
    spec: PartSpec,
    output_dir: str = "artifacts/parts",
    max_retries: int = 3,
    gateway_client: Optional[GatewayClient] = None,
    run_logger: Optional[RunLogger] = None,
    master_skeleton: Optional[Dict[str, Any]] = None,
    initial_code: Optional[str] = None,
    user_modification_prompt: Optional[str] = None,
    partner_interfaces: Optional[Dict[str, Dict[str, InterfacePort]]] = None,
    pillars: Optional[List[str]] = None,
    repair_tier: str = "parametric_first"
) -> Tuple[bool, Optional[DesignerOutput], Optional[VerificationVerdict], Any, Dict[str, str]]:
    """
    Executes single-part pipeline concurrently:
    Spec -> Designer Agent -> CadQuery Sandbox -> 6-Pillar Part Verifier -> (Part Repair Agent) -> Export
    When initial_code is passed, Designer Agent seeds Attempt 1 with previous_code for surgical iteration.
    When partner_interfaces is passed, verified interface coordinates are given to the Designer.
    When pillars is passed, Part Verifier checks only the specified pillar rule IDs.
    When repair_tier is 'llm_only', bypasses parametric fix attempts.
    """
    gw = gateway_client or GatewayClient()
    logger = run_logger or RunLogger(run_id=str(uuid.uuid4())[:8], output_dir=output_dir)
    
    code_gen = CodeGeneratorAgent(gw)
    verifier = PartVerifierAgent(min_wall_thickness=spec.wall_thickness, min_hole_diameter=spec.hole_diameter)
    repair_agent = PartRepairAgent()

    repair_instruction = user_modification_prompt or ""
    last_code: Optional[str] = initial_code
    designer_out: Optional[DesignerOutput] = None
    final_verdict: Optional[VerificationVerdict] = None
    solid_obj: Any = None

    for iteration in range(1, max_retries + 1):
        # 1. Code Generator Agent writes CadQuery code and exports InterfacePorts
        t_gen = time.time()
        designer_out = await code_gen.generate_designer_output(
            spec,
            mates=spec.mates,
            repair_prompt=repair_instruction,
            previous_code=last_code,
            master_skeleton=master_skeleton,
            partner_interfaces=partner_interfaces
        )
        last_code = designer_out.code
        logger.log_step(
            agent="code_generator_agent",
            part_id=spec.id,
            iteration=iteration,
            status="PASS",
            latency_ms=(time.time() - t_gen) * 1000
        )

        # 2. CadQuery Sandbox executes code
        solid_obj, exec_err = await execute_cadquery_code(designer_out.code)
        if exec_err:
            print(f"  ❌ [run_part_pipeline] Sandbox execution error on '{spec.id}' (Attempt {iteration}):\n{exec_err}")

            # Phase 1: Attempt zero-LLM syntax fix (remove fillet, filterBy, bad selectors)
            fixed_code, was_fixed, fix_notes = repair_agent.attempt_syntax_fix(designer_out.code, exec_err)
            if was_fixed and fixed_code:
                for note in fix_notes:
                    print(f"  🔧 [PartRepairAgent] Syntax fix applied: {note}")
                # Re-execute the patched code
                solid_obj, exec_err2 = await execute_cadquery_code(fixed_code)
                if not exec_err2:
                    print(f"  ✅ [PartRepairAgent] Syntax fix succeeded — continuing to verification (0 LLM tokens)")
                    designer_out.code = fixed_code
                    last_code = fixed_code
                    logger.log_step(agent="part_repair_agent", part_id=spec.id, iteration=iteration, status="PASS",
                                    diagnostics=[{"fix_type": "syntax", "notes": fix_notes}])
                    # Fall through to verification step below (solid_obj is now valid)
                else:
                    # Syntax fix didn't resolve execution — escalate to Designer
                    repair_instruction = repair_agent.generate_syntax_repair_instructions(exec_err, designer_out.code)
                    logger.log_step(agent="cad_kernel_sandbox", part_id=spec.id, iteration=iteration, status="ERROR", diagnostics=[exec_err])
                    import os
                    os.makedirs(f"{output_dir}/{spec.id}", exist_ok=True)
                    with open(f"{output_dir}/{spec.id}/failed_{spec.id}_iter_{iteration}.py", "w") as f:
                        f.write(designer_out.code)
                    continue
            else:
                # No syntax fix available — escalate to Designer
                repair_instruction = repair_agent.generate_syntax_repair_instructions(exec_err, designer_out.code)
                logger.log_step(agent="cad_kernel_sandbox", part_id=spec.id, iteration=iteration, status="ERROR", diagnostics=[exec_err])
                import os
                os.makedirs(f"{output_dir}/{spec.id}", exist_ok=True)
                with open(f"{output_dir}/{spec.id}/failed_{spec.id}_iter_{iteration}.py", "w") as f:
                    f.write(designer_out.code)
                continue

        # 3. 6-Pillar Part Verifier Agent checks OpenCascade geometry math
        t_ver = time.time()
        final_verdict = verifier.verify_part_solid(solid_obj, spec=spec, pillars=pillars)
        ver_status = "PASS" if final_verdict.passed else "FAIL"
        logger.log_step(
            agent="part_verifier_agent",
            part_id=spec.id,
            iteration=iteration,
            status=ver_status,
            diagnostics=[d.model_dump() for d in final_verdict.diagnostics],
            latency_ms=(time.time() - t_ver) * 1000
        )

        if final_verdict.passed:
            # 4. Export artifacts on success
            part_dir = f"{output_dir}/{spec.id}"
            artifact_paths = await export_cad_artifacts(solid_obj, part_dir, spec.name, code=designer_out.code)
            logger.log_step(agent="reporter_agent", part_id=spec.id, iteration=iteration, status="PASS")
            return True, designer_out, final_verdict, solid_obj, artifact_paths
        else:
            # 5. Part Repair Agent: attempt zero-LLM parametric fix first (if repair_tier allows)
            was_fixed = False
            fixed_code = None
            fix_notes = []
            if repair_tier == "parametric_first":
                fixed_code, was_fixed, fix_notes = repair_agent.attempt_parametric_fix(designer_out.code, final_verdict)
            else:
                fix_notes = [f"Bypassing parametric repair for '{spec.id}' (repair_tier={repair_tier})"]

            if was_fixed and fixed_code:
                for note in fix_notes:
                    print(f"  🔧 [PartRepairAgent] Parametric fix: {note}")
                # Re-execute and re-verify the patched code in-place
                solid_re, err_re = await execute_cadquery_code(fixed_code)
                if not err_re:
                    verdict_re = verifier.verify_part_solid(solid_re, spec=spec, pillars=pillars)
                    if verdict_re.passed:
                        print(f"  ✅ [PartRepairAgent] Parametric fix verified — PASS (0 LLM tokens)")
                        designer_out.code = fixed_code
                        part_dir = f"{output_dir}/{spec.id}"
                        artifact_paths = await export_cad_artifacts(solid_re, part_dir, spec.name, code=fixed_code)
                        logger.log_step(agent="part_repair_agent", part_id=spec.id, iteration=iteration, status="PASS",
                                        diagnostics=[{"fix_type": "parametric", "notes": fix_notes}])
                        return True, designer_out, verdict_re, solid_re, artifact_paths
                    else:
                        # Parametric fix executed but still fails verification — update code and fall through to Designer
                        print(f"  ⚠️  [PartRepairAgent] Parametric fix executed but still fails verification. Escalating to Designer.")
                        last_code = fixed_code
                        designer_out.code = fixed_code
                        solid_obj = solid_re
                        final_verdict = verdict_re
                        repair_instruction = repair_agent.generate_repair_instructions(verdict_re)
                        logger.log_step(agent="part_repair_agent", part_id=spec.id, iteration=iteration, status="FAIL")
                else:
                    # Parametric fix broke execution — revert and escalate
                    repair_instruction = repair_agent.generate_repair_instructions(final_verdict)
                    logger.log_step(agent="part_repair_agent", part_id=spec.id, iteration=iteration, status="FAIL")
            else:
                # Cannot fix parametrically or bypassed — escalate to Designer (LLM)
                for note in fix_notes:
                    print(f"  ℹ️  [PartRepairAgent] {note}")
                repair_instruction = repair_agent.generate_repair_instructions(final_verdict)
                logger.log_step(agent="part_repair_agent", part_id=spec.id, iteration=iteration, status="FAIL")

    logger.log_step(agent="part_pipeline", part_id=spec.id, status="ESCALATE")
    return False, designer_out, final_verdict, solid_obj, {}


async def run_single_part_pipeline(
    prompt: str,
    output_dir: str = "artifacts/single_part",
    max_retries: int = 3,
    gateway_client: Optional[GatewayClient] = None,
    initial_code: Optional[str] = None,
    user_modification_prompt: Optional[str] = None,
    run_logger: Optional[RunLogger] = None
) -> Tuple[bool, PartSpec, Optional[VerificationVerdict], str, Dict[str, str]]:
    """
    Executes full single-part pipeline from plain-English prompt:
    Prompt -> PlannerAgent -> PartSpec -> run_part_pipeline -> Export
    """
    gw = gateway_client or GatewayClient()
    logger = run_logger or RunLogger(run_id=str(uuid.uuid4())[:8], output_dir=output_dir)
    planner = PlannerAgent(gw)

    t0 = time.time()
    if initial_code:
        part_spec = await planner.plan_iteration_part(initial_code, prompt)
    else:
        part_spec = await planner.plan_part(prompt)
    logger.log_step(agent="planner_agent", part_id=part_spec.id, status="PASS", latency_ms=(time.time() - t0) * 1000)

    success, designer_out, verdict, solid, artifacts = await run_part_pipeline(
        spec=part_spec,
        output_dir=output_dir,
        max_retries=max_retries,
        gateway_client=gw,
        run_logger=logger,
        initial_code=initial_code,
        user_modification_prompt=user_modification_prompt
    )

    code = designer_out.code if designer_out else ""
    return success, part_spec, verdict, code, artifacts

