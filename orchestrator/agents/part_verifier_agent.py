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

from typing import Tuple, Any, Optional, Literal
from orchestrator.models import PartSpec, VerificationVerdict
from tools.verify_single_part import verify_single_part


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
        depth: Optional[Literal["concept", "functional", "manufacturing", "assembly_ready"]] = None
    ) -> VerificationVerdict:
        """
        Runs 6-pillar OpenCascade math checks for the given solid geometry, depth, and process.
        """
        target_process = process or (spec.manufacturing_process if spec else "3d_printing")
        target_depth = depth or (spec.verification_depth if spec else "functional")
        
        target_len = spec.length if spec else None
        target_width = spec.width if spec else None
        target_height = spec.height if spec else None

        is_gear = False
        if spec:
            name_lower = spec.name.lower()
            type_lower = spec.part_type.lower()
            id_lower = spec.id.lower()
            is_gear = any(kw in name_lower or kw in type_lower or kw in id_lower for kw in ["gear", "pinion", "casing", "housing", "carrier"])

        return verify_single_part(
            solid_obj,
            process=target_process,
            depth=target_depth,
            min_wall=self.min_wall,
            min_hole=self.min_hole,
            target_len=target_len,
            target_width=target_width,
            target_height=target_height,
            is_gear=is_gear
        )


# Backward compatibility aliases
PartCriticAgent = PartVerifierAgent
VerificationAgent = PartVerifierAgent
