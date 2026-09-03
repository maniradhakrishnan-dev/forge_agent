"""
Single-Part Concurrent Pipeline Engine (ForgeAgent).
Executes Design -> Sandbox -> 6-Pillar Part Verifier -> (Part Repair) loop asynchronously for a single part.
"""

import time
import json
import uuid
from typing import Dict, Any, Tuple, Optional, List
from orchestrator.gateway_client import GatewayClient
from orchestrator.models import PartSpec, MatingContext, DesignerOutput, VerificationVerdict
from orchestrator.run_logger import RunLogger
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
    master_skeleton: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[DesignerOutput], Optional[VerificationVerdict], Any, Dict[str, str]]:
    """
    Executes single-part pipeline concurrently:
    Spec -> Designer Agent -> CadQuery Sandbox -> 6-Pillar Part Verifier -> (Part Repair Agent) -> Export
    """
    gw = gateway_client or GatewayClient()
    logger = run_logger or RunLogger(run_id=str(uuid.uuid4())[:8], output_dir=output_dir)
    
    code_gen = CodeGeneratorAgent(gw)
    verifier = PartVerifierAgent(min_wall_thickness=spec.wall_thickness, min_hole_diameter=spec.hole_diameter)
    repair_agent = PartRepairAgent()

    repair_instruction = ""
    last_code: Optional[str] = None
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
            master_skeleton=master_skeleton
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
            repair_instruction = repair_agent.generate_syntax_repair_instructions(exec_err, designer_out.code)
            logger.log_step(agent="cad_kernel_sandbox", part_id=spec.id, iteration=iteration, status="ERROR", diagnostics=[exec_err])
            
            # Dump failed code for debugging
            import os
            os.makedirs(f"{output_dir}/{spec.id}", exist_ok=True)
            with open(f"{output_dir}/{spec.id}/failed_{spec.id}_iter_{iteration}.py", "w") as f:
                f.write(designer_out.code)
                
            continue

        # 3. 6-Pillar Part Verifier Agent checks OpenCascade geometry math
        t_ver = time.time()
        final_verdict = verifier.verify_part_solid(solid_obj, spec=spec)
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
            # 5. Part Repair Agent constructs diagnostic feedback
            repair_instruction = repair_agent.generate_repair_instructions(final_verdict)
            logger.log_step(agent="part_repair_agent", part_id=spec.id, iteration=iteration, status="FAIL")

    logger.log_step(agent="part_pipeline", part_id=spec.id, status="ESCALATE")
    return False, designer_out, final_verdict, solid_obj, {}
