"""
Goal 1 Multi-Agent Loop Orchestrator.
Connects Planner -> Code Generator -> CadQuery Sandbox -> Part Verifier -> Part Repair -> Artifact Export.
"""

import time
import uuid
from typing import Dict, Any, Tuple, Optional
from pathlib import Path
from orchestrator.gateway_client import GatewayClient
from orchestrator.models import PartSpec, VerificationVerdict
from orchestrator.run_logger import RunLogger
from orchestrator.agents.planner_agent import PlannerAgent
from orchestrator.agents.code_generator_agent import CodeGeneratorAgent
from orchestrator.agents.part_verifier_agent import PartVerifierAgent
from orchestrator.agents.part_repair_agent import PartRepairAgent
from tools.cad_kernel import execute_cadquery_code, export_cad_artifacts


async def run_goal1_pipeline(
    prompt: str,
    output_dir: str = "artifacts/goal1_single_part",
    max_retries: int = 3,
    gateway_client: Optional[GatewayClient] = None
) -> Tuple[bool, PartSpec, VerificationVerdict, str, Dict[str, str]]:
    """
    Executes Goal 1 Multi-Agent Loop:
    Prompt -> Planner Agent -> Code Generator Agent -> CadQuery Sandbox -> Part Verifier Agent -> (Part Repair Agent) -> Export
    """
    run_id = str(uuid.uuid4())[:8]
    logger = RunLogger(run_id=run_id, output_dir=output_dir)
    
    gw = gateway_client or GatewayClient()
    planner = PlannerAgent(gw)
    code_gen = CodeGeneratorAgent(gw)
    verifier = PartVerifierAgent(min_wall_thickness=1.5, min_hole_diameter=2.0)
    repair_agent = PartRepairAgent()

    # 1. Planner Agent decomposes spec
    t0 = time.time()
    part_spec = await planner.plan_part(prompt)
    logger.log_step(agent="planner_agent", part_id=part_spec.id, status="PASS", latency_ms=(time.time() - t0)*1000)
    
    repair_instruction = ""
    current_code = ""
    last_code: Optional[str] = None
    final_verdict = None

    for iteration in range(1, max_retries + 1):
        # 2. Code Generator Agent writes CadQuery code
        t_gen = time.time()
        current_code = await code_gen.generate_code(
            part_spec,
            repair_prompt=repair_instruction,
            previous_code=last_code
        )
        last_code = current_code
        logger.log_step(agent="code_generator_agent", part_id=part_spec.id, iteration=iteration, status="PASS", latency_ms=(time.time() - t_gen)*1000)

        # 3. Sandbox executes code
        solid_obj, exec_err = await execute_cadquery_code(current_code)
        if exec_err:
            print(f"\n  ❌ [CadQuery Sandbox Error] Part '{part_spec.id}' (Attempt {iteration}):\n{exec_err}\n")
            repair_instruction = repair_agent.generate_syntax_repair_instructions(exec_err, current_code)
            logger.log_step(agent="cad_kernel_sandbox", part_id=part_spec.id, iteration=iteration, status="ERROR", diagnostics=[exec_err])
            
            # Dump failed code for debugging
            import os
            os.makedirs(f"{output_dir}/{part_spec.id}", exist_ok=True)
            with open(f"{output_dir}/{part_spec.id}/failed_{part_spec.id}_iter_{iteration}.py", "w") as f:
                f.write(current_code)
                
            continue

        # 4. Part Verifier Agent checks OpenCascade geometry math
        t_ver = time.time()
        final_verdict = verifier.verify_part_solid(solid_obj, spec=part_spec)
        ver_status = "PASS" if final_verdict.passed else "FAIL"
        logger.log_step(
            agent="part_verifier_agent",
            part_id=part_spec.id,
            iteration=iteration,
            status=ver_status,
            diagnostics=[d.model_dump() for d in final_verdict.diagnostics],
            latency_ms=(time.time() - t_ver)*1000
        )

        if final_verdict.passed:
            # 5. Export artifacts on success
            artifact_paths = await export_cad_artifacts(solid_obj, output_dir, part_spec.name, code=current_code)
            logger.log_step(agent="reporter_agent", part_id=part_spec.id, iteration=iteration, status="PASS")
            logger.generate_summary_markdown(prompt, True)
            return True, part_spec, final_verdict, current_code, artifact_paths
        else:
            # 6. Part Repair Agent constructs diagnostic feedback
            repair_instruction = repair_agent.generate_repair_instructions(final_verdict)
            logger.log_step(agent="part_repair_agent", part_id=part_spec.id, iteration=iteration, status="FAIL")

    # Failed after max retries
    logger.log_step(agent="goal1_pipeline", part_id=part_spec.id, status="ESCALATE")
    logger.generate_summary_markdown(prompt, False)
    return False, part_spec, final_verdict, current_code, {}
