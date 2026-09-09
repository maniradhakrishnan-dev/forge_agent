"""
Unit tests for Full Assembly Pipeline Phase C (orchestrator/assembly_pipeline.py).
"""

import pytest
from orchestrator.gateway_client import GatewayClient, GatewayConfig
from orchestrator.assembly_pipeline import run_full_assembly_pipeline


@pytest.mark.live
@pytest.mark.asyncio
async def test_full_assembly_pipeline_bracket_bolt():
    client = GatewayClient()
    passed, graph, verdict, solids, artifacts = await run_full_assembly_pipeline(
        prompt="Mounting plate 50x40x10mm with two M4 clearance holes and a matching M4 bolt",
        output_dir="artifacts/test_full_assembly_c",
        gateway_client=client
    )

    assert len(graph.parts) == 2
    assert passed is True
    assert verdict.passed is True
    assert len(solids) == 2
    assert "assembly" in artifacts
