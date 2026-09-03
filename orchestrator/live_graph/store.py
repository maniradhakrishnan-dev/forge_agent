"""
GraphStore State Machine for ForgeAgent Live Graph Engine.
Thread-safe in-memory graph state store supporting atomic GraphPatch mutations
and JSON snapshot exports.
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional
from orchestrator.live_graph.models import GraphNode, GraphEdge, GraphPatch


class GraphStore:
    """In-memory reactive graph state store."""

    def __init__(self):
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: Dict[str, GraphEdge] = {}
        self._events: List[str] = []
        self._lock = asyncio.Lock()

    async def apply_patch(self, patch: GraphPatch) -> None:
        """Applies an atomic GraphPatch to the store."""
        async with self._lock:
            if patch.action == "ADD_NODE" and patch.node:
                self._nodes[patch.node.id] = patch.node
            elif patch.action == "UPDATE_NODE" and patch.node:
                if patch.node.id in self._nodes:
                    node = self._nodes[patch.node.id]
                    node.status = patch.node.status
                    node.payload.update(patch.node.payload)
            elif patch.action == "ADD_EDGE" and patch.edge:
                self._edges[patch.edge.id] = patch.edge
            elif patch.action == "EMIT_EVENT" and patch.event_message:
                self._events.append(patch.event_message)

    async def export_json(self, output_path: str) -> str:
        """Exports full graph state snapshot to JSON file."""
        async with self._lock:
            data = {
                "nodes": [n.model_dump() for n in self._nodes.values()],
                "edges": [e.model_dump() for e in self._edges.values()],
                "events": self._events
            }
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return str(path)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self._nodes.get(node_id)
