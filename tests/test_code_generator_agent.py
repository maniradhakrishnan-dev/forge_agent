"""
Unit tests for CodeGeneratorAgent (orchestrator/agents/code_generator_agent.py).
"""

import pytest
from orchestrator.models import PartSpec, MatingContext
from orchestrator.gateway_client import GatewayClient, GatewayConfig
from orchestrator.agents.code_generator_agent import CodeGeneratorAgent


@pytest.mark.asyncio
async def test_code_generator_outputs_designer_output():
    client = GatewayClient(GatewayConfig(gemini_api_key=None, groq_api_key=None))
    agent = CodeGeneratorAgent(client)
    
    spec = PartSpec(
        id="bracket_1",
        name="cnc_bracket",
        part_type="mounting_bracket",
        manufacturing_process="cnc_machining",
        length=50.0,
        width=40.0,
        height=15.0
    )
    
    output = await agent.generate_designer_output(spec)
    assert output.part_id == "bracket_1"
    assert "result =" in output.code
    assert "hole_center_1" in output.interfaces or "shaft_tip" in output.interfaces
