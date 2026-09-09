"""
Integration Test Suite for Goal 1 Multi-Agent Pipeline.
Tests Planner Agent -> Code Generator Agent -> Sandbox -> Verification Agent -> Repair Agent -> Export.
"""

import pytest
import asyncio
from pathlib import Path
from orchestrator.gateway_client import GatewayClient
from orchestrator.part_pipeline import run_single_part_pipeline


@pytest.mark.live
def test_goal1_pipeline_end_to_end(tmp_path):
    """Test full Goal 1 pipeline asynchronously."""
    prompt = "Create a heavy-duty mounting bracket 40x30x10mm with two M4 clearance holes"
    out_dir = str(tmp_path / "artifacts_goal1")
    
    gw = GatewayClient()
    success, spec, verdict, code, artifact_paths = asyncio.run(
        run_single_part_pipeline(prompt, output_dir=out_dir, gateway_client=gw)
    )

    assert success is True, f"Goal 1 Pipeline failed. Verdict: {verdict}"
    assert "bracket" in spec.name.lower() or "mount" in spec.name.lower() or spec.part_type == "mounting_bracket"
    assert "step" in artifact_paths and Path(artifact_paths["step"]).exists()
    assert "stl" in artifact_paths and Path(artifact_paths["stl"]).exists()
    assert "result =" in code
    print("\n[SUCCESS] Goal 1 Multi-Agent Pipeline passed end-to-end!")
    print(f"Part Spec: {spec.model_dump_json()}")
    print(f"Exported STEP: {artifact_paths['step']}")
    print(f"Exported STL: {artifact_paths['stl']}")


if __name__ == "__main__":
    from pathlib import Path
    test_goal1_pipeline_end_to_end(Path("artifacts/test_goal1"))
