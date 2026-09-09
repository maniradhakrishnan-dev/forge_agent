"""
Strict Pydantic Data Contracts for ForgeAgent.
Every agent input, output, diagnostic, and run log entry is defined here.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Literal
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 1. Mating & Assembly Graph Models (Planner Output)
# ---------------------------------------------------------------------------

class MatingContext(BaseModel):
    """Defines a mating relationship between two parts before design begins."""
    partner_id: str
    mate_type: Literal[
        "hole_shaft", "shaft_hole", "face_face", "slot_tab", "gear_mesh", "edge_edge",
        "compliant_fit", "press_fit", "snap_fit"
    ]
    my_feature_name: str = "primary_mate"
    my_feature_diameter: Optional[float] = None
    clearance_mm: float = 0.15
    tolerance_mm: float = 0.05


class PartSpec(BaseModel):
    """Specification for a single mechanical part."""
    id: str = "part_1"
    name: str = "mounting_bracket"
    description: str = ""
    part_type: str = "mounting_bracket"
    manufacturing_process: Literal["3d_printing", "cnc_machining", "sheet_metal"] = "3d_printing"
    verification_depth: Literal["concept", "functional", "manufacturing", "assembly_ready"] = "functional"
    length: float = 40.0
    width: float = 30.0
    height: float = 10.0
    hole_diameter: float = 4.3
    wall_thickness: float = 4.0
    mates: List[MatingContext] = Field(default_factory=list)
    kinematic_params: Dict[str, Any] = Field(default_factory=dict)
    is_compliant: bool = False
    max_deflection_mm: Optional[float] = None

    @field_validator("verification_depth", mode="before")
    @classmethod
    def normalize_verification_depth(cls, v: Any) -> str:
        valid = {"concept", "functional", "manufacturing", "assembly_ready"}
        if isinstance(v, str) and v.lower() in valid:
            return v.lower()
        return "functional"

    @field_validator("manufacturing_process", mode="before")
    @classmethod
    def normalize_mfg_process(cls, v: Any) -> str:
        valid = {"3d_printing", "cnc_machining", "sheet_metal"}
        if isinstance(v, str) and v.lower() in valid:
            return v.lower()
        return "3d_printing"


class JointDef(BaseModel):
    """Kinematic joint definition between two parts in an assembly."""
    id: str = "joint_1"
    type: Literal["rigid", "revolute", "prismatic", "cylindrical"] = "rigid"
    part_a: str
    part_b: str
    axis: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    limits: Tuple[float, float] = (0.0, 360.0)  # Angle or translation limits


class AssemblyGraph(BaseModel):
    """Complete specification of a multi-part mechanical assembly with shared parameters."""
    name: str = "assembly"
    description: str = ""
    mechanism_type: str = "custom"
    shared_parameters: Dict[str, Any] = Field(default_factory=dict)
    master_skeleton: Dict[str, Any] = Field(default_factory=dict)
    parts: List[PartSpec] = Field(default_factory=list)
    joints: List[JointDef] = Field(default_factory=list)




# ---------------------------------------------------------------------------
# 2. Interface Ports (Designer Output)
# ---------------------------------------------------------------------------

class InterfacePort(BaseModel):
    """Named mating feature coordinate exported by Designer for deterministic assembly."""
    name: str  # e.g., "hole_center_1"
    position: Tuple[float, float, float]  # (x, y, z)
    direction: Tuple[float, float, float] = (0.0, 0.0, 1.0)  # Face normal vector
    feature_type: str = "face"
    diameter: Optional[float] = None
    max_deflection: Optional[float] = None
    is_compliant: bool = False


class DesignerInput(BaseModel):
    """Input contract for Part Designer Agent."""
    spec: PartSpec
    mates: List[MatingContext] = Field(default_factory=list)
    shared_parameters: Dict[str, Any] = Field(default_factory=dict)
    master_skeleton: Dict[str, Any] = Field(default_factory=dict)
    repair_prompt: Optional[str] = None


class DesignerOutput(BaseModel):
    """Output contract for Part Designer Agent."""
    part_id: str
    code: str
    interfaces: Dict[str, InterfacePort] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 3. Single-Part Diagnostics & Verification Contracts
# ---------------------------------------------------------------------------

class DFMDiagnostic(BaseModel):
    """Single diagnostic rule result from OpenCascade Part Critic."""
    rule_id: str  # e.g., "PHYS-01", "DFM-3D-01", "FAST-01"
    status: Literal["PASS", "FAIL"]
    parameter: str
    measured: float
    required: float
    message: str


class CriticInput(BaseModel):
    """Input contract for Part Critic Agent."""
    part_id: str
    solid_obj: Any  # cq.Workplane or cq.Shape object


class VerificationVerdict(BaseModel):
    """Complete pass/fail verdict from Part Critic Agent."""
    passed: bool
    diagnostics: List[DFMDiagnostic] = Field(default_factory=list)
    volume: float = 0.0
    bounding_box: Dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 4. Multi-Part Diagnostics & Verification Contracts
# ---------------------------------------------------------------------------

class AssemblyDiagnostic(BaseModel):
    """Single diagnostic result from OpenCascade Assembly Critic."""
    rule_id: str  # e.g., "ASSY-01" (Interference), "ASSY-02" (Fit Clearance)
    status: Literal["PASS", "FAIL"]
    parameter: str
    measured: float
    required: float
    message: str
    involved_parts: List[str] = Field(default_factory=list)


class AssemblyCriticInput(BaseModel):
    """Input contract for Assembly Critic Agent."""
    parts: Dict[str, Any]  # part_id -> cq.Shape/Solid
    transforms: Dict[str, Any] = Field(default_factory=dict)
    joints: List[JointDef] = Field(default_factory=list)


class AssemblyVerdict(BaseModel):
    """Complete pass/fail verdict from Assembly Critic Agent."""
    passed: bool
    diagnostics: List[AssemblyDiagnostic] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5. Repair & Escalation Contracts
# ---------------------------------------------------------------------------

class RepairInstruction(BaseModel):
    """Instruction generated by Part Repair or Assembly Repair (Diagnostic Router)."""
    target_agent: Literal["code_generator_agent", "assembly_agent", "planner_agent", "part_repair_agent"]
    target_part_id: str
    fault_type: Literal["dfm", "geometry", "positioning", "graph_patch", "tolerance_patch"]
    failed_diagnostics: List[Any] = Field(default_factory=list)
    prompt: str
    patched_graph: Optional[Any] = None  # Modified AssemblyGraph for graph_patch fault_type
    patched_code: Optional[Dict[str, str]] = None  # part_id → fixed CadQuery code for tolerance_patch


class ValidationResult(BaseModel):
    """Result of pre-design Constraint Consistency Validation."""
    valid: bool
    errors: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 6. Observability & Run Log Contract
# ---------------------------------------------------------------------------

class RunEntry(BaseModel):
    """Structured record of a single agent execution step."""
    run_id: str
    agent: str
    part_id: Optional[str] = None
    iteration: int = 1
    status: Literal["PASS", "FAIL", "ERROR", "ESCALATE"]
    diagnostics: List[Any] = Field(default_factory=list)
    latency_ms: float = 0.0
    llm_tokens_used: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
