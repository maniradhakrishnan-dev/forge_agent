"""
Live Graph Executor for ForgeAgent.
Asynchronously executes agent tasks in a reactive event-driven loop (S13 pattern).
Emits nodes reactively as OpenCascade geometry math and CAD interface ports are physically proven.
"""

import time
import asyncio
from typing import Dict, Any, Tuple, Optional
from orchestrator.gateway_client import GatewayClient
from orchestrator.live_graph.models import (
    GraphNode,
    GraphEdge,
    GraphPatch,
    TaskSpec
)
from orchestrator.live_graph.store import GraphStore
from orchestrator.live_graph.workers import CADWorkerRegistry
from orchestrator.live_graph.planner import LiveCADPlanner
from orchestrator.run_logger import RunLogger
from orchestrator.assembly_pipeline import run_full_assembly_pipeline
from orchestrator.part_pipeline import run_single_part_pipeline


class LiveGraphExecutor:
    """Reactive event-driven Live Graph execution engine."""

    def __init__(self, store: Optional[GraphStore] = None, max_workers: int = 3):
        self.store = store or GraphStore()
        self.max_workers = max_workers
        self.workers = CADWorkerRegistry()

    async def run_reactive_engine(
        self,
        planner: LiveCADPlanner,
        output_dir: str = "artifacts/live_graph_run"
    ) -> Tuple[bool, str]:
        """
        Pure event-driven live task graph engine (S13 pattern).
        Executes ready nodes concurrently, broadcasting events to the LiveCADPlanner
        which mutates the graph incrementally from real OpenCascade outcomes.
        """
        # 1. Start run and emit initial frontier
        start_event = await self.store.record_event(kind="run_started")
        initial_patch = await planner.plan(self.store.snapshot(), start_event)
        await self.store.apply_patch(initial_patch)

        context: Dict[str, Any] = {
            "verified_solids": {},
            "interfaces": {},
            "codes": {}
        }

        in_flight: Dict[asyncio.Task, str] = {}
        sem = asyncio.Semaphore(self.max_workers)

        while not self.store.is_finished:
            # 2. Find and dispatch all ready nodes
            ready_nodes = self.store.get_ready_nodes()
            for node in ready_nodes:
                self.store.set_node_status(node.id, "RUNNING")
                task_spec = TaskSpec(
                    id=node.id,
                    role=node.agent_role,
                    input=node.payload.get("input", {}),
                    metadata=node.payload.get("metadata", {})
                )

                async def _worker_runner(ts: TaskSpec):
                    async with sem:
                        return await self.workers.execute_task(ts, context)

                t = asyncio.create_task(_worker_runner(task_spec))
                in_flight[t] = node.id

            if not in_flight:
                break

            # 3. Wait for at least one worker to complete
            done, _ = await asyncio.wait(in_flight.keys(), return_when=asyncio.FIRST_COMPLETED)

            for completed_task in done:
                nid = in_flight.pop(completed_task)
                try:
                    passed, payload = completed_task.result()
                except Exception as e:
                    passed = False
                    payload = {"error": str(e)}

                status = "SUCCEEDED" if passed else "FAILED"
                self.store.set_node_status(nid, status, payload_update=payload)

                # Store verified CAD geometry in runtime context
                clean_id = nid.replace("design_", "").replace("verify_", "").replace("repair_", "")
                if "solid" in payload and payload["solid"] is not None:
                    context["verified_solids"][clean_id] = payload["solid"]
                if "interfaces" in payload and payload["interfaces"]:
                    context["interfaces"][clean_id] = payload["interfaces"]
                if "code" in payload:
                    context["codes"][clean_id] = payload["code"]

                # 4. Record event and pass outcome to LiveCADPlanner
                event_kind = "task_succeeded" if passed else "task_failed"
                event = await self.store.record_event(kind=event_kind, node_id=nid, payload=payload)

                patch = await planner.plan(self.store.snapshot(), event)
                await self.store.apply_patch(patch)

        # 5. Export final state
        state_file = f"{output_dir}/graph_state.json"
        await self.store.export_json(state_file)

        # Check if verified
        success = any(
            n.status in ("PASS", "SUCCEEDED")
            for n in self.store._nodes.values()
            if "verify" in n.id
        )
        return success, state_file

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
        Executes user prompt asynchronously through the Live Graph Engine.
        Supports both single-part and multi-part kinematics-aware assemblies.
        """
        gw = gateway_client or self.workers.gateway
        run_id = run_id or f"run_{int(time.time())}"
        self.store.run_id = run_id

        # 1. Emit Planner Node
        planner_node = GraphNode(id="node_planner", label="Architect Planner", agent_role="planner_agent", status="RUNNING")
        await self.store.apply_patch(GraphPatch(action="ADD_NODE", node=planner_node))
        await self.store.apply_patch(GraphPatch(action="EMIT_EVENT", event_message=f"[{run_id}] Started prompt execution: '{prompt}'"))

        # Callback mapping real-time pipeline events into graph store
        async def _on_step(entry):
            agent = entry.agent
            status = entry.status
            pid = entry.part_id or "global"
            node_id = f"node_{agent}_{pid}" if pid != "global" else f"node_{agent}"

            node_status = "RUNNING"
            if status in ("PASS", "SUCCEEDED"):
                node_status = "PASS"
            elif status in ("FAIL", "FAILED", "ERROR"):
                node_status = "FAIL"

            existing = self.store.get_node(node_id)
            if not existing:
                await self.store.apply_patch(GraphPatch(
                    action="ADD_NODE",
                    node=GraphNode(
                        id=node_id,
                        label=f"{agent} ({pid})" if pid != "global" else agent,
                        agent_role=agent,
                        status=node_status,
                        payload={"iteration": entry.iteration, "diagnostics": entry.diagnostics}
                    )
                ))
            else:
                existing.status = node_status
                await self.store.apply_patch(GraphPatch(action="UPDATE_NODE", node=existing))

            # Connect causal edges
            if agent in ("code_generator_agent", "cad_kernel_sandbox"):
                await self.store.apply_patch(GraphPatch(
                    action="ADD_EDGE",
                    edge=GraphEdge(id=f"e_plan_{node_id}", source="node_planner", target=node_id, label="GENERATES")
                ))
            elif agent == "part_verifier_agent":
                designer_id = f"node_code_generator_agent_{pid}"
                await self.store.apply_patch(GraphPatch(
                    action="ADD_EDGE",
                    edge=GraphEdge(id=f"e_ver_{pid}", source=designer_id, target=node_id, label="VERIFIES", edge_type="VERIFIES")
                ))
            elif agent in ("part_repair_agent", "assembly_repair_agent"):
                verifier_id = f"node_part_verifier_agent_{pid}" if agent == "part_repair_agent" else "node_assembly_verifier_agent"
                await self.store.apply_patch(GraphPatch(
                    action="ADD_EDGE",
                    edge=GraphEdge(id=f"e_rep_{node_id}", source=verifier_id, target=node_id, label="REPAIRS", edge_type="REPAIRS")
                ))
            elif agent in ("assembly_agent", "assembly_verifier_agent"):
                for n_id, n in self.store._nodes.items():
                    if "part_verifier_agent" in n_id and n.status == "PASS":
                        await self.store.apply_patch(GraphPatch(
                            action="ADD_EDGE",
                            edge=GraphEdge(id=f"e_assy_{n_id}", source=n_id, target=node_id, label="ASSEMBLES")
                        ))

            await self.store.apply_patch(GraphPatch(
                action="EMIT_EVENT",
                event_message=f"[{agent}] part={pid} iter={entry.iteration} status={status}"
            ))

        run_logger = RunLogger(run_id=run_id, output_dir=output_dir, on_step_callback=_on_step)

        # Always execute via the universal pipeline driven by the PlannerAgent's decomposition.
        # Zero keyword guessing — the LLM Planner decomposes into 1 or N parts.
        passed, graph, verdict, solids, artifacts = await run_full_assembly_pipeline(
            prompt=prompt,
            output_dir=output_dir,
            process=process,
            depth=depth,
            gateway_client=gw,
            run_id=run_id,
            run_logger=run_logger
        )

        if passed:
            planner_node.status = "PASS"
            await self.store.apply_patch(GraphPatch(action="UPDATE_NODE", node=planner_node))
            if graph and len(graph.parts) > 1:
                await self.store.apply_patch(GraphPatch(
                    action="ADD_NODE",
                    node=GraphNode(id="node_assembly_verifier", label="Assembly Verifier", agent_role="assembly_verifier_agent", status="PASS")
                ))
            else:
                await self.store.apply_patch(GraphPatch(
                    action="ADD_NODE",
                    node=GraphNode(id="node_part_verifier", label="Part Verifier", agent_role="part_verifier_agent", status="PASS")
                ))

        state_file = f"{output_dir}/graph_state.json"
        await self.store.export_json(state_file)
        return passed, state_file

    async def execute_iteration(
        self,
        iterate_path: str,
        prompt: str,
        target_part_id: Optional[str] = None,
        output_dir: str = "artifacts/live_graph_iteration",
        gateway_client: Optional[GatewayClient] = None,
        run_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Iterates on an existing mechanical design via live graph."""
        from orchestrator.iteration_pipeline import run_iteration_pipeline
        gw = gateway_client or self.workers.gateway
        run_id = run_id or f"iter_{int(time.time())}"

        planner_node = GraphNode(id="node_iteration_planner", label="Iteration Planner", agent_role="planner_agent", status="RUNNING")
        await self.store.apply_patch(GraphPatch(action="ADD_NODE", node=planner_node))

        async def _on_step(entry):
            node_id = f"node_{entry.agent}_{entry.part_id or 'global'}"
            status = "PASS" if entry.status in ("PASS", "SUCCEEDED") else ("FAIL" if entry.status in ("FAIL", "ERROR") else "RUNNING")
            await self.store.apply_patch(GraphPatch(
                action="ADD_NODE",
                node=GraphNode(id=node_id, label=f"{entry.agent}", agent_role=entry.agent, status=status)
            ))

        run_logger = RunLogger(run_id=run_id, output_dir=output_dir, on_step_callback=_on_step)
        passed, obj, verdict, code, artifacts = await run_iteration_pipeline(
            iterate_path=iterate_path,
            user_feedback=prompt,
            target_part_id=target_part_id,
            output_dir=output_dir,
            gateway_client=gw,
            run_logger=run_logger
        )

        if passed:
            planner_node.status = "PASS"
            await self.store.apply_patch(GraphPatch(action="UPDATE_NODE", node=planner_node))

        state_file = f"{output_dir}/graph_state.json"
        await self.store.export_json(state_file)
        return passed, state_file
