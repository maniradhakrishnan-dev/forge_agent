"""
Constraint Consistency Validator for ForgeAgent.
Runs pre-design validation on AssemblyGraph emitted by Planner Agent.
Catches bad mate references, inconsistent clearances, and incompatible mate types
BEFORE wasting code generation iterations.
"""

from typing import List
from orchestrator.models import AssemblyGraph, ValidationResult


class ConstraintValidator:
    """Validates structural and dimensional consistency of an AssemblyGraph before design."""

    @staticmethod
    def _fuzzy_match_id(target: str, candidates: set) -> str:
        """Finds closest matching part ID if LLM used singular/plural or _set suffix."""
        t_clean = target.lower().replace("_set", "").rstrip("s")
        for c in candidates:
            if c.lower().replace("_set", "").rstrip("s") == t_clean:
                return c
        return target

    @staticmethod
    def validate(graph: AssemblyGraph) -> ValidationResult:
        errors: List[str] = []
        part_ids = {p.id for p in graph.parts}

        # 1. Check Part ID Uniqueness
        if len(part_ids) < len(graph.parts):
            errors.append("AssemblyGraph contains duplicate part IDs.")

        # Track validated undirected pairs to avoid duplicate or inverted error messages
        checked_pairs: set = set()

        # 2. Validate Mating Relationships
        for part in graph.parts:
            for mate in part.mates:
                # Fuzzy heal partner ID if minor singular/plural discrepancy
                if mate.partner_id not in part_ids:
                    healed_id = ConstraintValidator._fuzzy_match_id(mate.partner_id, part_ids)
                    if healed_id in part_ids:
                        mate.partner_id = healed_id
                    else:
                        errors.append(
                            f"Part '{part.id}' references non-existent mating partner '{mate.partner_id}'."
                        )
                        continue

                # Find partner part
                partner = next((p for p in graph.parts if p.id == mate.partner_id), None)
                if not partner:
                    continue

                # Undirected pair key
                pair_key = (min(part.id, partner.id), max(part.id, partner.id))

                # Check reciprocal mate existence; auto-synthesize if missing
                reciprocal = next((m for m in partner.mates if m.partner_id == part.id), None)
                if not reciprocal:
                    from orchestrator.models import MatingContext
                    reciprocal_type = (
                        "shaft_hole" if mate.mate_type == "hole_shaft"
                        else ("hole_shaft" if mate.mate_type == "shaft_hole" else mate.mate_type)
                    )
                    c_offset = mate.clearance_mm if mate.clearance_mm > 0 else 0.15
                    if mate.my_feature_diameter is not None:
                        if mate.mate_type == "hole_shaft":
                            # Part has hole -> partner has shaft (shaft_d = hole_d - clearance)
                            reciprocal_d = round(max(0.5, mate.my_feature_diameter - c_offset), 2)
                        elif mate.mate_type == "shaft_hole":
                            # Part has shaft -> partner has hole (hole_d = shaft_d + clearance)
                            reciprocal_d = round(mate.my_feature_diameter + c_offset, 2)
                        else:
                            reciprocal_d = mate.my_feature_diameter
                    else:
                        reciprocal_d = None

                    reciprocal = MatingContext(
                        partner_id=part.id,
                        mate_type=reciprocal_type,
                        my_feature_name=f"mate_to_{part.id}",
                        my_feature_diameter=reciprocal_d,
                        clearance_mm=c_offset
                    )
                    partner.mates.append(reciprocal)

                # Skip clearance validation if this undirected pair has already been evaluated
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)

                # Check clearance consistency for cylindrical mates
                if mate.my_feature_diameter is not None and reciprocal.my_feature_diameter is not None:
                    if mate.mate_type in ("hole_shaft", "shaft_hole"):
                        # Correctly assign hole and shaft roles
                        if mate.mate_type == "hole_shaft":
                            hole_part, shaft_part = part, partner
                            hole_mate, shaft_mate = mate, reciprocal
                        else:
                            hole_part, shaft_part = partner, part
                            hole_mate, shaft_mate = reciprocal, mate

                        hole_d = hole_mate.my_feature_diameter
                        shaft_d = shaft_mate.my_feature_diameter

                        # Case A: Nominal matching dimensions (e.g. 5.0mm pin into 5.0mm bore)
                        # Standard engineering practice: auto-heal by applying clearance to the hole
                        if abs(hole_d - shaft_d) < 0.05:
                            c = hole_mate.clearance_mm if hole_mate.clearance_mm > 0.01 else 0.15
                            hole_d = round(shaft_d + c, 2)
                            hole_mate.my_feature_diameter = hole_d
                            hole_mate.clearance_mm = c
                            shaft_mate.clearance_mm = c
                            if hasattr(hole_part, "hole_diameter") and abs(hole_part.hole_diameter - shaft_d) < 0.05:
                                hole_part.hole_diameter = hole_d

                        # Case B: Inverted small clearance (LLM accidentally swapped shaft and hole clearance)
                        # e.g. hole=5.0mm, shaft=5.2mm -> swap so hole=5.2mm, shaft=5.0mm
                        elif 0 < (shaft_d - hole_d) <= 0.35:
                            c = round(shaft_d - hole_d, 2)
                            hole_mate.my_feature_diameter, shaft_mate.my_feature_diameter = shaft_d, hole_d
                            hole_mate.clearance_mm = c
                            shaft_mate.clearance_mm = c
                            if hasattr(hole_part, "hole_diameter") and hole_part.hole_diameter == hole_d:
                                hole_part.hole_diameter = shaft_d
                            hole_d, shaft_d = shaft_d, hole_d

                        # Case C: True physical interference (shaft is substantially larger than hole)
                        if hole_d < shaft_d:
                            errors.append(
                                f"Physical interference in spec: hole diameter ({hole_d}mm) on '{hole_part.id}' "
                                f"is smaller than shaft diameter ({shaft_d}mm) on '{shaft_part.id}'."
                            )
                        else:
                            measured_c = round(hole_d - shaft_d, 2)
                            # If clearance is realistic (0.05 - 0.6mm), auto-sync to avoid petty rejections
                            if 0.05 <= measured_c <= 0.6:
                                hole_mate.clearance_mm = measured_c
                                shaft_mate.clearance_mm = measured_c
                            elif abs(measured_c - hole_mate.clearance_mm) > 0.2:
                                errors.append(
                                    f"Inconsistent mate clearance between hole '{hole_part.id}' (d={hole_d}mm) "
                                    f"and shaft '{shaft_part.id}' (d={shaft_d}mm). Calculated clearance: {measured_c}mm."
                                )

        # 3. Validate Joint Definitions
        for joint in graph.joints:
            # Fuzzy heal joint part references
            if joint.part_a not in part_ids:
                healed_a = ConstraintValidator._fuzzy_match_id(joint.part_a, part_ids)
                if healed_a in part_ids:
                    joint.part_a = healed_a
                else:
                    errors.append(f"Joint '{joint.id}' references invalid part_a '{joint.part_a}'.")
            if joint.part_b not in part_ids:
                healed_b = ConstraintValidator._fuzzy_match_id(joint.part_b, part_ids)
                if healed_b in part_ids:
                    joint.part_b = healed_b
                else:
                    errors.append(f"Joint '{joint.id}' references invalid part_b '{joint.part_b}'.")

        # 4. Validate Gear / Mesh Center Distance Consistency
        for part in graph.parts:
            for mate in part.mates:
                if mate.mate_type == "gear_mesh":
                    partner = next((p for p in graph.parts if p.id == mate.partner_id), None)
                    if not partner:
                        continue
                    kp_a = part.kinematic_params or {}
                    kp_b = partner.kinematic_params or {}
                    d_a = float(kp_a.get("pitch_diameter") or (kp_a.get("module", 0) * kp_a.get("num_teeth", 0)))
                    d_b = float(kp_b.get("pitch_diameter") or (kp_b.get("module", 0) * kp_b.get("num_teeth", 0)))

                    if d_a > 0 and d_b > 0:
                        is_internal = (
                            kp_a.get("is_internal") or kp_b.get("is_internal") or
                            "internal" in mate.my_feature_name.lower() or "ring" in part.id.lower() or "ring" in partner.id.lower()
                        )
                        c_expected = abs(d_a - d_b) / 2.0 if is_internal else (d_a + d_b) / 2.0

                        # Check against shared_parameters or kinematic_params center distance
                        shared_p = graph.shared_parameters or graph.master_skeleton or {}
                        c_decl = (
                            shared_p.get("center_to_center_distance") or
                            shared_p.get("center_distance") or
                            kp_a.get("center_distance") or
                            kp_b.get("center_distance")
                        )
                        if c_decl is not None and abs(float(c_decl) - c_expected) > 0.2:
                            # Auto-heal center distance in shared parameters to match physical tooth kinematics
                            if "center_to_center_distance" in shared_p:
                                shared_p["center_to_center_distance"] = round(c_expected, 3)
                            elif "center_distance" in shared_p:
                                shared_p["center_distance"] = round(c_expected, 3)
                            else:
                                shared_p["center_to_center_distance"] = round(c_expected, 3)

        # 5. Check Graph Connectivity: ensure no completely disconnected orphan parts
        connected_parts = set()
        for p in graph.parts:
            if p.mates:
                connected_parts.add(p.id)
                for m in p.mates:
                    connected_parts.add(m.partner_id)
        for j in graph.joints:
            connected_parts.add(j.part_a)
            connected_parts.add(j.part_b)

        if len(graph.parts) > 1:
            for p in graph.parts:
                if p.id not in connected_parts:
                    errors.append(f"Orphan part '{p.id}' has no mates or joints connecting it to the assembly graph.")

        is_valid = len(errors) == 0
        return ValidationResult(valid=is_valid, errors=errors)

