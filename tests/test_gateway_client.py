"""
Unit tests for GatewayClient (Gemini & Groq routing + fallback).
"""

import pytest
from orchestrator.gateway_client import GatewayClient, GatewayConfig


@pytest.mark.asyncio
async def test_gateway_client_fallback_mode():
    config = GatewayConfig(
        gemini_api_key=None,
        groq_api_key=None
    )
    client = GatewayClient(config)
    messages = [
        {"role": "system", "content": "You are the Planner Agent. Target format: PartSpec JSON"},
        {"role": "user", "content": "L-shaped corner bracket 50x50x15mm"}
    ]
    response = await client.complete(messages)
    assert "l_bracket" in response.lower()
    assert "50" in response
