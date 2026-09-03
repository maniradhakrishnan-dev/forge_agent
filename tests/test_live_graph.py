"""
Unit tests for Reactive Live Graph Engine (orchestrator/live_graph/).
"""

import pytest
from orchestrator.live_graph.store import GraphStore
from orchestrator.live_graph.executor import LiveGraphExecutor
from orchestrator.gateway_client import GatewayClient, GatewayConfig


@pytest.mark.asyncio
async def test_live_graph_executor_standalone_part():
    client = GatewayClient(GatewayConfig(gemini_api_key=None, groq_api_key=None))
    store = GraphStore()
    executor = LiveGraphExecutor(store)

    passed, state_file = await executor.execute_prompt(
        prompt="Mounting bracket 40x30x10mm with 4.3mm hole",
        output_dir="artifacts/test_live_graph_part",
        gateway_client=client
    )

    assert passed is True
    node = store.get_node("node_part_verifier")
    assert node is not None
    assert node.status == "PASS"


@pytest.mark.asyncio
async def test_live_graph_executor_assembly():
    client = GatewayClient(GatewayConfig(gemini_api_key=None, groq_api_key=None))
    store = GraphStore()
    executor = LiveGraphExecutor(store)

    passed, state_file = await executor.execute_prompt(
        prompt="Bracket with M4 bolt assembly",
        output_dir="artifacts/test_live_graph_assy",
        gateway_client=client
    )

    assert passed is True
    node = store.get_node("node_assembly_verifier")
    assert node is not None
    assert node.status == "PASS"
