"""
GraphStore State Machine for ForgeAgent Live Graph Engine.
Thread-safe in-memory graph state store supporting:
1. Atomic GraphPatch mutations (S13 multi-mutation & legacy single-action)
2. Directed dependency resolution (in-degrees and ready node computation)
3. Durable event journaling
4. GraphSnapshot generation for the Planner
5. JSON state export
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from orchestrator.live_graph.models import (
    GraphNode,
    GraphEdge,
    GraphPatch,
    GraphSnapshot,
    Event,
)


class GraphStore:
    """In-memory reactive graph state store."""

    def __init__(self, run_id: str = "default_run"):
        self.run_id = run_id
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: Dict[str, GraphEdge] = {}
        # Adjacency maps for fast dependency resolution
        self._in_edges: Dict[str, Set[str]] = {}   # node_id -> set of parent node_ids
        self._out_edges: Dict[str, Set[str]] = {}  # node_id -> set of child node_ids
        self._events: List[Event] = []
        self._event_seq: int = 0
        self._finished: bool = False
        self._lock = asyncio.Lock()

    @property
    def is_finished(self) -> bool:
        return self._finished

    async def record_event(self, kind: str, node_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> Event:
        """Records an event into the sequential event journal."""
        async with self._lock:
            self._event_seq += 1
            event = Event(
                sequence=self._event_seq,
                kind=kind,
                node_id=node_id,
                payload=payload or {}
            )
            self._events.append(event)
            return event

    def get_events(self) -> List[Event]:
        return list(self._events)

    async def apply_patch(self, patch: GraphPatch) -> None:
        """Applies an atomic GraphPatch to the store."""
        async with self._lock:
            # 1. Handle S13-style multi-mutation patch
            if patch.finish:
                self._finished = True

            # Process additions
            for task in patch.add:
                node = GraphNode(
                    id=task.id,
                    label=f"{task.role} ({task.id})",
                    agent_role=task.role,
                    status="PENDING",
                    payload={"input": task.input, "metadata": task.metadata}
                )
                self._nodes[task.id] = node
                if task.id not in self._in_edges:
                    self._in_edges[task.id] = set()
                if task.id not in self._out_edges:
                    self._out_edges[task.id] = set()

            # Process connections (parent, child)
            for parent_id, child_id in patch.connect:
                edge_id = f"e_{parent_id}_{child_id}"
                edge = GraphEdge(id=edge_id, source=parent_id, target=child_id, label="DEPENDS_ON")
                self._edges[edge_id] = edge
                self._in_edges.setdefault(child_id, set()).add(parent_id)
                self._out_edges.setdefault(parent_id, set()).add(child_id)

            # Process state transitions
            for nid in patch.cancel:
                if nid in self._nodes:
                    self._nodes[nid].status = "CANCELLED"

            for nid in patch.wait:
                if nid in self._nodes:
                    self._nodes[nid].status = "WAITING"

            for nid in patch.resume:
                if nid in self._nodes:
                    self._nodes[nid].status = "PENDING"

            # 2. Handle backwards-compatible legacy actions
            if patch.action == "ADD_NODE" and patch.node:
                self._nodes[patch.node.id] = patch.node
                self._in_edges.setdefault(patch.node.id, set())
                self._out_edges.setdefault(patch.node.id, set())
            elif patch.action == "UPDATE_NODE" and patch.node:
                if patch.node.id in self._nodes:
                    node = self._nodes[patch.node.id]
                    node.status = patch.node.status
                    node.payload.update(patch.node.payload)
            elif patch.action == "ADD_EDGE" and patch.edge:
                self._edges[patch.edge.id] = patch.edge
                self._in_edges.setdefault(patch.edge.target, set()).add(patch.edge.source)
                self._out_edges.setdefault(patch.edge.source, set()).add(patch.edge.target)
            elif patch.action == "EMIT_EVENT" and patch.event_message:
                self._event_seq += 1
                self._events.append(Event(sequence=self._event_seq, kind="log_event", payload={"message": patch.event_message}))

    def get_ready_nodes(self) -> List[GraphNode]:
        """
        Returns all nodes that are PENDING and whose parent dependencies
        have all successfully finished (status in 'PASS' or 'SUCCEEDED').
        """
        ready = []
        for nid, node in self._nodes.items():
            if node.status != "PENDING":
                continue
            parents = self._in_edges.get(nid, set())
            if not parents:
                ready.append(node)
            else:
                parents_succeeded = all(
                    self._nodes.get(p) and self._nodes[p].is_success
                    for p in parents
                )
                if parents_succeeded:
                    ready.append(node)
        return ready

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self._nodes.get(node_id)

    def set_node_status(self, node_id: str, status: str, payload_update: Optional[Dict[str, Any]] = None) -> None:
        """Helper to transition node status."""
        if node_id in self._nodes:
            self._nodes[node_id].status = status
            if payload_update:
                self._nodes[node_id].payload.update(payload_update)

    def snapshot(self) -> GraphSnapshot:
        """Generates an immutable snapshot for planner inspection."""
        nodes_dict = {
            nid: {
                "id": n.id,
                "role": n.agent_role,
                "status": n.status,
                "payload": dict(n.payload)
            }
            for nid, n in self._nodes.items()
        }
        edges_list = [(e.source, e.target) for e in self._edges.values()]
        return GraphSnapshot(
            run_id=self.run_id,
            finished=self._finished,
            nodes=nodes_dict,
            edges=edges_list
        )

    async def export_json(self, output_path: str) -> str:
        """Exports full graph state snapshot to JSON file."""
        async with self._lock:
            data = {
                "run_id": self.run_id,
                "finished": self._finished,
                "nodes": [n.model_dump() for n in self._nodes.values()],
                "edges": [e.model_dump() for e in self._edges.values()],
                "events": [e.model_dump() for e in self._events]
            }
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return str(path)
