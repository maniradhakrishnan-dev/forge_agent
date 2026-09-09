"""
Unit & Integration tests for Reactive Live Graph Engine (orchestrator/live_graph/).
"""

import pytest
from pathlib import Path
from orchestrator.live_graph.store import GraphStore
from orchestrator.live_graph.executor import LiveGraphExecutor
from orchestrator.live_graph.models import GraphNode, GraphEdge, GraphPatch
from orchestrator.run_logger import RunLogger
from orchestrator.gateway_client import GatewayClient


@pytest.mark.asyncio
async def test_live_graph_store_atomic_growth(tmp_path):
    """Verifies that GraphStore dynamically grows nodes, edges, and status transitions."""
    store = GraphStore()

    # 1. Planner node
    await store.apply_patch(GraphPatch(
        action="ADD_NODE",
        node=GraphNode(id="node_planner", label="Architect Planner", agent_role="planner_agent", status="RUNNING")
    ))
    assert store.get_node("node_planner").status == "RUNNING"

    # 2. Dynamic growth: 2 parts emitted
    await store.apply_patch(GraphPatch(
        action="ADD_NODE",
        node=GraphNode(id="node_part_sun", label="Part Designer (sun_gear)", agent_role="code_generator_agent", status="RUNNING")
    ))
    await store.apply_patch(GraphPatch(
        action="ADD_NODE",
        node=GraphNode(id="node_part_ring", label="Part Designer (ring_gear)", agent_role="code_generator_agent", status="RUNNING")
    ))
    await store.apply_patch(GraphPatch(
        action="ADD_EDGE",
        edge=GraphEdge(id="e1", source="node_planner", target="node_part_sun", label="GENERATES")
    ))
    await store.apply_patch(GraphPatch(
        action="ADD_EDGE",
        edge=GraphEdge(id="e2", source="node_planner", target="node_part_ring", label="GENERATES")
    ))

    # 3. Dynamic repair branch emitted for sun_gear
    await store.apply_patch(GraphPatch(
        action="ADD_NODE",
        node=GraphNode(id="node_repair_sun", label="Parametric Repair (sun_gear)", agent_role="part_repair_agent", status="PASS")
    ))
    await store.apply_patch(GraphPatch(
        action="ADD_EDGE",
        edge=GraphEdge(id="e_rep", source="node_part_sun", target="node_repair_sun", label="REPAIRS", edge_type="REPAIRS")
    ))

    # 4. Assembly barrier
    await store.apply_patch(GraphPatch(
        action="ADD_NODE",
        node=GraphNode(id="node_assembly_verifier", label="Assembly Verifier", agent_role="assembly_verifier_agent", status="PASS")
    ))

    # Export snapshot
    out_file = str(tmp_path / "graph_state.json")
    exported = await store.export_json(out_file)
    assert Path(exported).exists()

    assert store.get_node("node_planner") is not None
    assert store.get_node("node_part_sun") is not None
    assert store.get_node("node_part_ring") is not None
    assert store.get_node("node_repair_sun") is not None
    assert store.get_node("node_assembly_verifier").status == "PASS"


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_graph_executor_standalone_part():
    client = GatewayClient()
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


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_graph_executor_assembly():
    client = GatewayClient()
    store = GraphStore()
    executor = LiveGraphExecutor(store)

    passed, state_file = await executor.execute_prompt(
        prompt="Mounting plate 50x40x10mm with two M4 clearance holes and a matching M4 bolt",
        output_dir="artifacts/test_live_graph_assy",
        gateway_client=client
    )

    assert passed is True
    node = store.get_node("node_assembly_verifier")
    assert node is not None
    assert node.status == "PASS"


@pytest.mark.asyncio
async def test_graph_store_ready_node_resolution():
    """Verifies that child nodes are only marked ready when all parent dependencies succeed."""
    from orchestrator.live_graph.models import TaskSpec, GraphPatch
    store = GraphStore()

    patch = GraphPatch(
        add=[
            TaskSpec(id="task_parent", role="code_generator_agent"),
            TaskSpec(id="task_child", role="part_verifier_agent")
        ],
        connect=[("task_parent", "task_child")]
    )
    await store.apply_patch(patch)

    # Initially, only parent is ready (has 0 dependencies)
    ready = store.get_ready_nodes()
    assert len(ready) == 1
    assert ready[0].id == "task_parent"

    # Parent running -> child still not ready
    store.set_node_status("task_parent", "RUNNING")
    assert len(store.get_ready_nodes()) == 0

    # Parent succeeds -> child becomes ready!
    store.set_node_status("task_parent", "SUCCEEDED")
    ready_after = store.get_ready_nodes()
    assert len(ready_after) == 1
    assert ready_after[0].id == "task_child"


@pytest.mark.asyncio
async def test_live_cad_planner_dynamic_frontier_growth():
    """
    Verifies that LiveCADPlanner starts with envelope datum only,
    and sprouts dependent internal parts ONLY when interface ports are proven.
    """
    from orchestrator.models import AssemblyGraph, PartSpec, MatingContext
    from orchestrator.live_graph.planner import LiveCADPlanner
    from orchestrator.live_graph.models import Event

    bracket = PartSpec(id="bracket", name="Mounting Bracket Base")
    bolt = PartSpec(id="bolt_m4", name="M4 Bolt", mates=[MatingContext(partner_id="bracket", mate_type="hole_shaft")])
    blueprint = AssemblyGraph(name="bracket_assembly", parts=[bracket, bolt])

    planner = LiveCADPlanner(blueprint)
    store = GraphStore()

    # Step 1: run_started -> emits only bracket (envelope/datum)
    start_event = await store.record_event(kind="run_started")
    p1 = await planner.plan(store.snapshot(), start_event)
    await store.apply_patch(p1)

    assert "design_bracket" in store._nodes
    assert "verify_bracket" in store._nodes
    assert "design_bolt_m4" not in store._nodes  # Bolt is NOT guessed yet!

    # Step 2: Bracket finishes in sandbox
    d_event = await store.record_event(
        kind="task_succeeded",
        node_id="design_bracket",
        payload={"interfaces": {"hole_1": {"position": (0, 0, 5), "diameter": 4.3}}}
    )
    p2 = await planner.plan(store.snapshot(), d_event)
    await store.apply_patch(p2)

    # Step 3: Bracket verification passes -> Planner sprouts bolt with proven port!
    v_event = await store.record_event(
        kind="task_succeeded",
        node_id="verify_bracket",
        payload={"solid": "solid_bracket_mesh"}
    )
    p3 = await planner.plan(store.snapshot(), v_event)
    await store.apply_patch(p3)

    assert "design_bolt_m4" in store._nodes
    assert "verify_bolt_m4" in store._nodes
    # Check that bolt received bracket's proven port
    bolt_node = store.get_node("design_bolt_m4")
    assert "partner_interfaces" in bolt_node.payload["input"]
    assert "bracket" in bolt_node.payload["input"]["partner_interfaces"]

    # Step 4: Bolt finishes and passes verification -> Planner emits assembly
    v_bolt = await store.record_event(
        kind="task_succeeded",
        node_id="verify_bolt_m4",
        payload={"solid": "solid_bolt_mesh"}
    )
    p4 = await planner.plan(store.snapshot(), v_bolt)
    await store.apply_patch(p4)

    assert "assemble" in store._nodes
    assert "verify_assembly" in store._nodes

    # Step 5: Assembly passes verification -> Finished!
    v_assy = await store.record_event(
        kind="task_succeeded",
        node_id="verify_assembly",
        payload={"passed": True, "interference_volume": 0.0}
    )
    p5 = await planner.plan(store.snapshot(), v_assy)
    assert p5.finish is True

