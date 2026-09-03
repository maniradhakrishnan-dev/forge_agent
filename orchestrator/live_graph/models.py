"""
Reactive Live Graph Engine Models for ForgeAgent.
Defines GraphNode, GraphEdge, and GraphPatch state contracts.
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """Represents a single node in the reactive execution graph."""
    id: str
    label: str
    agent_role: str
    status: Literal["PENDING", "RUNNING", "PASS", "FAIL", "REPAIR", "ESCALATE"] = "PENDING"
    payload: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """Represents a directed relationship between graph nodes."""
    id: str
    source: str
    target: str
    label: str = ""
    edge_type: Literal["FLOW", "VERIFIES", "REPAIRS", "EMITS"] = "FLOW"


class GraphPatch(BaseModel):
    """Atomic mutation patch applied to the GraphStore."""
    action: Literal["ADD_NODE", "UPDATE_NODE", "ADD_EDGE", "EMIT_EVENT"]
    node: Optional[GraphNode] = None
    edge: Optional[GraphEdge] = None
    event_message: Optional[str] = None
