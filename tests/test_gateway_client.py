"""
Unit tests for GatewayClient (Gemini & Groq routing + fallback).
"""

import pytest
from orchestrator.gateway_client import GatewayClient, GatewayConfig


@pytest.mark.asyncio
async def test_gateway_client_hard_fail_without_keys():
    config = GatewayConfig(
        gemini_api_key=None,
        groq_api_key=None
    )
    client = GatewayClient(config)
    messages = [
        {"role": "user", "content": "Hello"}
    ]
    from orchestrator.gateway_client import LLMAPIError
    with pytest.raises(LLMAPIError):
        await client.complete(messages)


@pytest.mark.live
@pytest.mark.asyncio
async def test_gateway_client_live_completion():
    client = GatewayClient()
    messages = [
        {"role": "user", "content": "Say 'CAD' in exactly one word."}
    ]
    response = await client.complete(messages)
    assert len(response.strip()) > 0
