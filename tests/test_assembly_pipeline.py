"""
Unit tests for Full Assembly Pipeline Phase C (orchestrator/assembly_pipeline.py).
"""

import pytest
from orchestrator.gateway_client import GatewayClient, GatewayConfig
from orchestrator.assembly_pipeline import run_full_assembly_pipeline


@pytest.mark.asyncio
async def test_full_assembly_pipeline_bracket_bolt():
    client = GatewayClient(GatewayConfig(gemini_api_key=None, groq_api_key=None))
    passed, graph, verdict, solids, artifacts = await run_full_assembly_pipeline(
        prompt="Bracket with M4 bolt assembly",
        output_dir="artifacts/test_full_assembly_c",
        gateway_client=client
    )

    assert len(graph.parts) == 2
    assert passed is True
    assert verdict.passed is True
    assert "bracket_1" in solids
    assert "bolt_1" in solids
