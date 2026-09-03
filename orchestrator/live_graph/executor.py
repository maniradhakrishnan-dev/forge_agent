"""
Live Graph Executor for ForgeAgent.
Asynchronously executes agent tasks, applying atomic patches to GraphStore and emitting
nodes reactively as OpenCascade geometry math ground truth is proven.
"""

import time
import asyncio
from typing import Dict, Any, Tuple, Optional
from orchestrator.gateway_client import GatewayClient
from orchestrator.live_graph.models import GraphNode, GraphEdge, GraphPatch
from orchestrator.live_graph.store import GraphStore
from orchestrator.assembly_pipeline import run_full_assembly_pipeline
from orchestrator.goal1_loop import run_goal1_pipeline


class LiveGraphExecutor:
    """Reactive event-driven Live Graph execution engine."""

    def __init__(self, store: Optional[GraphStore] = None):
        self.store = store or GraphStore()

    async def execute_prompt(
        self,
        prompt: str,
        output_dir: str = "artifacts/live_graph_run",
        process: str = "3d_printing",
        depth: str = "functional",
        gateway_client: Optional[GatewayClient] = None,
        run_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Executes user prompt asynchronously through the Live Graph Engine,
        emitting nodes dynamically to GraphStore and saving graph_state.json.
        """
        # 1. Emit Planner Node
        planner_node = GraphNode(id="node_planner", label="Architect Planner", agent_role="planner_agent", status="RUNNING")
        await self.store.apply_patch(GraphPatch(action="ADD_NODE", node=planner_node))
        await self.store.apply_patch(GraphPatch(action="EMIT_EVENT", event_message=f"[run:{run_id}] Started prompt execution: '{prompt}'"))

        # Route to assembly or single-part pipeline based on mechanism/assembly intent
        p_lower = prompt.lower()
        is_assembly = any(kw in p_lower for kw in [
            "assembly", "bolt", "nut", "washer", "joint", "connect",
            "mate", "fasten", "screw", "rivet", "gearbox", "gear box",
            "planetary", "transmission", "reducer", "speed reducer",
            "mechanism", "differential", "stage"
        ])

        if is_assembly:
            # 2. Multi-Part Assembly Pipeline Execution
            planner_node.status = "PASS"
            await self.store.apply_patch(GraphPatch(action="UPDATE_NODE", node=planner_node))

            # Pre-allocate generic part nodes (will be updated after planner runs)
            part_nodes = []
            for i in range(1, 3):  # Pre-allocate 2 nodes; planner will determine actual count
                node = GraphNode(id=f"node_part_{i}", label=f"Part Designer ({i})", agent_role="code_generator_agent", status="RUNNING")
                await self.store.apply_patch(GraphPatch(action="ADD_NODE", node=node))
                await self.store.apply_patch(GraphPatch(action="ADD_EDGE", edge=GraphEdge(id=f"e{i}", source="node_planner", target=f"node_part_{i}")))
                part_nodes.append(node)

            passed, graph, verdict, solids, artifacts = await run_full_assembly_pipeline(
                prompt=prompt,
                output_dir=output_dir,
                gateway_client=gateway_client,
                run_id=run_id
            )

            if passed:
                for node in part_nodes:
                    node.status = "PASS"
                    await self.store.apply_patch(GraphPatch(action="UPDATE_NODE", node=node))

                assy_node = GraphNode(id="node_assembly_verifier", label="Assembly Verifier (Interference=0mm³)", agent_role="assembly_verifier_agent", status="PASS")
                await self.store.apply_patch(GraphPatch(action="ADD_NODE", node=assy_node))
                for i, node in enumerate(part_nodes):
                    await self.store.apply_patch(GraphPatch(action="ADD_EDGE", edge=GraphEdge(id=f"ev{i}", source=node.id, target="node_assembly_verifier", edge_type="VERIFIES")))
            else:
                for node in part_nodes:
                    node.status = "FAIL"
                    await self.store.apply_patch(GraphPatch(action="UPDATE_NODE", node=node))

        else:
            # 3. Single-Part Pipeline Execution
            planner_node.status = "PASS"
            await self.store.apply_patch(GraphPatch(action="UPDATE_NODE", node=planner_node))

            designer_node = GraphNode(id="node_part_designer", label="Part Designer", agent_role="code_generator_agent", status="RUNNING")
            await self.store.apply_patch(GraphPatch(action="ADD_NODE", node=designer_node))
            await self.store.apply_patch(GraphPatch(action="ADD_EDGE", edge=GraphEdge(id="e1", source="node_planner", target="node_part_designer")))

            passed, spec, verdict, code, artifacts = await run_goal1_pipeline(
                prompt=prompt,
                output_dir=output_dir,
                gateway_client=gateway_client
            )

            if passed:
                designer_node.status = "PASS"
                await self.store.apply_patch(GraphPatch(action="UPDATE_NODE", node=designer_node))

                verifier_node = GraphNode(id="node_part_verifier", label="Part Verifier (6-Pillar DFM)", agent_role="part_verifier_agent", status="PASS")
                await self.store.apply_patch(GraphPatch(action="ADD_NODE", node=verifier_node))
                await self.store.apply_patch(GraphPatch(action="ADD_EDGE", edge=GraphEdge(id="e2", source="node_part_designer", target="node_part_verifier", edge_type="VERIFIES")))
            else:
                designer_node.status = "FAIL"
                await self.store.apply_patch(GraphPatch(action="UPDATE_NODE", node=designer_node))

        # 4. Save graph_state.json
        state_file = f"{output_dir}/graph_state.json"
        await self.store.export_json(state_file)
        return passed, state_file
