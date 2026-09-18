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

        explicit_constraints = getattr(spec, "explicit_constraints", {}) if spec else {}
        is_single_part = getattr(spec, "is_single_part", False) if spec else False

        is_gear = False
        is_shaft = False
        requires_hole = False
        if spec:
            name_lower = spec.name.lower()
            type_lower = spec.part_type.lower()
            id_lower = spec.id.lower()
            is_gear = (
                getattr(spec, "geometry_form", "") in ("spur_gear", "pinion", "cycloid_disc") or
                any(kw in name_lower or kw in type_lower or kw in id_lower for kw in ["gear", "pinion", "casing", "housing", "carrier"])
            )
            is_shaft = (
                getattr(spec, "geometry_form", "") in ("stepped_shaft", "shaft", "bolt", "pin") or
                (any(kw in name_lower or kw in type_lower or kw in id_lower for kw in ["shaft", "axle", "rod", "pin", "bolt", "screw"])
                 and not any(kw in name_lower for kw in ["hollow", "sleeve", "carrier"]))
            )
            
            # Explicit user prompt constraints take absolute precedence
            if any("hole" in k.lower() or "bore" in k.lower() for k in explicit_constraints.keys()):
                requires_hole = True
            elif is_shaft:
                requires_hole = False
            elif is_single_part:
                # Standalone single parts must never require holes unless explicitly specified
                requires_hole = bool(getattr(spec, "hole_diameter", 0.0) and spec.hole_diameter > 0)
            else:
                # Assembly part: check typed specification fields (hole_diameter, features, critical_dimensions, mates)
                crit_dims = getattr(spec, "critical_dimensions", {})
                features = getattr(spec, "features", [])
                mates = getattr(spec, "mates", [])
                has_hole_crit = any("hole" in k.lower() or "bore" in k.lower() for k in crit_dims.keys())
                has_hole_feat = any("hole" in f.get("name", "").lower() or "bore" in f.get("name", "").lower() for f in features if isinstance(f, dict))
                has_hole_mate = any(m.mate_type in ("shaft_hole", "hole_shaft") for m in mates)
                has_hole_spec = bool(getattr(spec, "hole_diameter", 0.0) and spec.hole_diameter > 0)
                requires_hole = has_hole_crit or has_hole_feat or (has_hole_spec and has_hole_mate)

            # Axisymmetric geometry targets (shafts, pins, gears, discs)
            crit_dims = getattr(spec, "critical_dimensions", {}) or {}
            if is_shaft:
                od = crit_dims.get("outer_diameter") or crit_dims.get("shaft_diameter") or crit_dims.get("diameter")
                if not od:
                    shaft_mate = next((m for m in getattr(spec, "mates", []) if m.my_feature_diameter), None)
                    if shaft_mate:
                        od = shaft_mate.my_feature_diameter
                if od:
                    target_width = float(od)
                    target_height = float(od)
                if "length" in crit_dims:
                    target_len = float(crit_dims["length"])
            elif is_gear:
                od = crit_dims.get("outer_diameter") or crit_dims.get("pitch_diameter") or crit_dims.get("diameter")
                thick = crit_dims.get("thickness")
                if od:
                    target_len = float(od)
                    target_width = float(od)
                if thick:
                    target_height = float(thick)

        # Extract typed mating contracts and critical dimensions for MATE-01/CRIT-01
        part_mates = getattr(spec, "mates", []) if spec else []
        part_critical_dims = getattr(spec, "critical_dimensions", {}) if spec else {}

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
            is_shaft=is_shaft,
            requires_hole=requires_hole,
            explicit_constraints=explicit_constraints,
            is_single_part=is_single_part,
            pillar_filter=pillars,
            mates=part_mates if part_mates else None,
            critical_dimensions=part_critical_dims if part_critical_dims else None
        )


# Backward compatibility aliases
PartCriticAgent = PartVerifierAgent
VerificationAgent = PartVerifierAgent
