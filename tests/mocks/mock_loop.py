"""
Mock P0 Single-Part Verification Loop (Async).
Used for fast unit/integration testing without calling real LLM APIs.
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
    """Mock parser converting text prompt to PartSpec without LLM."""
    await asyncio.sleep(0.01)
    return PartSpec(
        name="mounting_bracket",
        description=prompt,
        length=40.0,
        width=30.0,
        height=10.0,
        hole_diameter=4.3
    )


async def mock_part_designer_agent(spec: PartSpec, repair_info: Optional[str] = None) -> str:
    """Mock code generator emitting CadQuery code without LLM."""
    await asyncio.sleep(0.01)
    hole_d = spec.hole_diameter

    if repair_info and "min_hole_diameter" in repair_info:
        hole_d = max(hole_d, 2.5)

    code = f"""import cadquery as cq

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
    """Mock P0 loop execution for testing."""
    spec = await mock_architect_parser(prompt)
    repair_payload = None
    current_code = ""

    for iteration in range(1, max_retries + 1):
        current_code = await mock_part_designer_agent(spec, repair_info=repair_payload)
        solid_obj, exec_err = await execute_cadquery_code(current_code)
        if exec_err:
            repair_payload = f"Execution Error on Iteration {iteration}: {exec_err}"
            continue

        verdict = verify_single_part(solid_obj, min_wall=1.5, min_hole=2.0)
        if verdict.passed:
            artifact_paths = await export_cad_artifacts(solid_obj, output_dir, spec.name)
            return True, verdict, current_code, artifact_paths
        else:
            failed_rules = [d.model_dump() for d in verdict.diagnostics if d.status == "FAIL"]
            repair_payload = json.dumps(failed_rules)

    return False, verdict, current_code, {}
