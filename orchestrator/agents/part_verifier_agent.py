"""
Part Verifier Agent (Single-Part Inspector).
Executes 6-pillar OpenCascade geometry math checks filtered by verification depth and process.
Pillars:
1. Geometric Validity (PHYS-01, PHYS-02)
2. Specification Compliance (SPEC-01)
3. Interface & Feature Alignment (FEAT-01)
4. Structural Integrity (STRUCT-01, STRUCT-02)
5. Process DFM (DFM-3D, DFM-CNC, DFM-SM)
6. Fastener & Mating Readiness (FAST-01)
"""

from typing import Any, Optional, Literal, List
from orchestrator.models import PartSpec, VerificationVerdict
from tools.verify_single_part import verify_single_part

PROCESS_MIN_WALL = {
    "3d_printing": 1.2,
    "cnc_machining": 1.5,
    "sheet_metal": 0.5,
}


class PartVerifierAgent:
    """Single-part OpenCascade geometric & DFM verification agent."""

    def __init__(self, min_wall_thickness: float = 1.5, min_hole_diameter: float = 2.0):
        self.min_wall = min_wall_thickness
        self.min_hole = min_hole_diameter

    def verify_part_solid(
        self,
        solid_obj: Any,
        spec: Optional[PartSpec] = None,
        process: Optional[Literal["3d_printing", "cnc_machining", "sheet_metal"]] = None,
        depth: Optional[Literal["concept", "functional", "manufacturing", "assembly_ready"]] = None,
        pillars: Optional[List[str]] = None
    ) -> VerificationVerdict:
        """
        Runs 6-pillar OpenCascade math checks for the given solid geometry, depth, and process.
        When pillars is provided, explicitly filters to those rule IDs.
        Enforces process-level minimum wall thickness floors.
        """
        target_process = process or (spec.manufacturing_process if spec else "3d_printing")
        target_depth = depth or (spec.verification_depth if spec else "functional")
        
        target_len = spec.length if spec else None
        target_width = spec.width if spec else None
        target_height = spec.height if spec else None

        # Enforce process minimum wall thickness floor
        process_floor = PROCESS_MIN_WALL.get(target_process, 1.2)
        effective_min_wall = max(self.min_wall, process_floor)

        is_gear = False
        requires_hole = False
        if spec:
            name_lower = spec.name.lower()
            type_lower = spec.part_type.lower()
            id_lower = spec.id.lower()
            is_gear = any(kw in name_lower or kw in type_lower or kw in id_lower for kw in ["gear", "pinion", "casing", "housing", "carrier"])
            # Auto-infer hole requirements from spec or part semantics
            if getattr(spec, "hole_diameter", 0.0) and spec.hole_diameter > 0:
                requires_hole = True
            elif any(kw in name_lower or kw in type_lower or kw in id_lower for kw in ["bracket", "plate", "bushing", "pulley", "arm", "link"]):
                requires_hole = True

        return verify_single_part(
            solid_obj,
            process=target_process,
            depth=target_depth,
            min_wall=effective_min_wall,
            min_hole=self.min_hole,
            target_len=target_len,
            target_width=target_width,
            target_height=target_height,
            is_gear=is_gear,
            requires_hole=requires_hole,
            pillar_filter=pillars
        )


# Backward compatibility aliases
PartCriticAgent = PartVerifierAgent
VerificationAgent = PartVerifierAgent
