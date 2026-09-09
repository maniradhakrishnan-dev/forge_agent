"""
Reactive Live Graph Engine Models for ForgeAgent.
Defines NodeState, TaskSpec, Event, GraphPatch, GraphSnapshot, GraphNode, and GraphEdge contracts.
Combines S13's event-driven live task graph contracts with CAD-specific payload semantics.
"""

from enum import StrEnum
from typing import List, Dict, Any, Optional, Literal, Tuple
from pydantic import BaseModel, Field


class NodeState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING = "waiting"


class TaskSpec(BaseModel):
    """A named unit of agent work emitted by the planner."""
    id: str
    role: str  # e.g., "code_generator_agent", "part_verifier_agent", "part_repair_agent", "assembly_agent"
    input: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Event(BaseModel):
    """An event emitted by the live graph runtime upon execution outcomes."""
    sequence: int = 0
    kind: str  # e.g. "run_started", "task_started", "task_succeeded", "task_failed", "interference_detected"
    node_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class GraphNode(BaseModel):
    """Represents a single node in the reactive execution graph."""
    id: str
    label: str
    agent_role: str
    status: str = "PENDING"  # PENDING, RUNNING, PASS, FAIL, SUCCEEDED, FAILED, WAITING, CANCELLED
    iteration: int = 1
    payload: Dict[str, Any] = Field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("PASS", "FAIL", "SUCCEEDED", "FAILED", "CANCELLED")

    @property
    def is_success(self) -> bool:
        return self.status in ("PASS", "SUCCEEDED")


class GraphEdge(BaseModel):
    """Represents a directed relationship between graph nodes."""
    id: str
    source: str
    target: str
    label: str = ""
    edge_type: Literal["FLOW", "VERIFIES", "REPAIRS", "EMITS", "ASSEMBLES"] = "FLOW"


class GraphPatch(BaseModel):
    """
    Atomic mutation patch applied to the GraphStore.
    Supports both S13-style multi-mutation sets (add, connect, cancel, wait, resume, finish)
    and single-action mutations for backwards compatibility.
    """
    # S13 multi-mutation fields
    add: List[TaskSpec] = Field(default_factory=list)
    connect: List[Tuple[str, str]] = Field(default_factory=list)
    cancel: List[str] = Field(default_factory=list)
    wait: List[str] = Field(default_factory=list)
    resume: List[str] = Field(default_factory=list)
    finish: bool = False
    reason: str = ""

    # Backwards compatibility action fields
    action: Optional[Literal["ADD_NODE", "UPDATE_NODE", "ADD_EDGE", "EMIT_EVENT"]] = None
    node: Optional[GraphNode] = None
    edge: Optional[GraphEdge] = None
    event_message: Optional[str] = None


class GraphSnapshot(BaseModel):
    """Immutable view of graph state inspected by the planner."""
    run_id: str
    finished: bool = False
    nodes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    edges: List[Tuple[str, str]] = Field(default_factory=list)
