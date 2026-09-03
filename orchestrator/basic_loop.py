"""
Basic P0 Single-Part Verification Loop (Async).
Executes generate -> kernel -> critic -> repair retry loop asynchronously for a single CAD part.
"""

from typing import Dict, Any, Tuple, Optional
import json
import asyncio
from pydantic import BaseModel
from tools.cad_kernel import execute_cadquery_code, export_cad_artifacts
from tools.verify_single_part import verify_single_part, VerificationVerdict


class PartSpec(BaseModel):
    name: str
    description: str
    length: float
    width: float
    height: float
    hole_diameter: float


async def mock_architect_parser(prompt: str) -> PartSpec:
    """
    Asynchronously parses a plain-English prompt into a structured PartSpec.
    (In full system, LLM Architect Agent performs this).
    """
    await asyncio.sleep(0.01)  # Non-blocking async yield
    return PartSpec(
        name="mounting_bracket",
        description=prompt,
        length=40.0,
        width=30.0,
        height=10.0,
        hole_diameter=4.3  # M4 clearance hole
    )


async def mock_part_designer_agent(spec: PartSpec, repair_info: Optional[str] = None) -> str:
    """
    Asynchronously generates CadQuery Python code for the requested PartSpec.
    Supports injecting a repair if a previous iteration failed a Critic check.
    (In full system, LLM Part Designer Agent performs this).
    """
    await asyncio.sleep(0.01)  # Non-blocking async yield
    hole_d = spec.hole_diameter

    # If repair requests fixing a hole size that was too small
    if repair_info and "min_hole_diameter" in repair_info:
        hole_d = max(hole_d, 2.5)

    code = f"""import cadquery as cq

# Mounting Bracket Part Generation
result = (
    cq.Workplane("XY")
    .box({spec.length}, {spec.width}, {spec.height})
    .faces(">Z").workplane()
    .hole({hole_d})
)
"""
    return code


async def run_basic_p0_loop(
    prompt: str,
    output_dir: str = "artifacts/p0_bracket",
    max_retries: int = 3
) -> Tuple[bool, VerificationVerdict, str, Dict[str, str]]:
    """
    Asynchronously executes the Basic P0 Loop:
    Prompt -> Spec -> Designer -> Kernel -> Critic -> (Repair if needed) -> Export
    """
    spec = await mock_architect_parser(prompt)
    repair_payload = None
    current_code = ""

    for iteration in range(1, max_retries + 1):
        # 1. Designer Agent writes code asynchronously
        current_code = await mock_part_designer_agent(spec, repair_info=repair_payload)
        
        # 2. Kernel Sandbox executes code asynchronously in threadpool
        solid_obj, exec_err = await execute_cadquery_code(current_code)
        if exec_err:
            repair_payload = f"Execution Error on Iteration {iteration}: {exec_err}"
            continue

        # 3. Part Critic Agent runs geometric math verification
        verdict = verify_single_part(solid_obj, min_wall=1.5, min_hole=2.0)
        
        if verdict.passed:
            # 4. Export artifacts asynchronously on success
            artifact_paths = await export_cad_artifacts(solid_obj, output_dir, spec.name)
            return True, verdict, current_code, artifact_paths
        else:
            # Prepare diagnostic payload for repair loop
            failed_rules = [d.model_dump() for d in verdict.diagnostics if d.status == "FAIL"]
            repair_payload = json.dumps(failed_rules)

    # Failed after max retries
    return False, verdict, current_code, {}
