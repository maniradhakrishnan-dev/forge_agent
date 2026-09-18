"""
Assembly Agent (Assembler).
Positions verified part solids deterministically using InterfacePorts and AssemblyGraph joint definitions into cq.Assembly().
"""

from typing import Dict, Any, Tuple, List, Optional
import cadquery as cq
from orchestrator.models import AssemblyGraph, InterfacePort
from orchestrator.toolbox import AgentToolbox


def _get_shape_obj(val_shape: Any) -> Any:
    """Helper to extract underlying cq.Shape / cq.Solid from cq.Workplane or cq.Shape."""
    if hasattr(val_shape, "val"):
        shape = val_shape.val()
        if shape is not None:
            return shape
    return val_shape


def _find_compatible_ports(
    partner_ports: Dict[str, InterfacePort],
    my_ports: Dict[str, InterfacePort],
    mate: Optional[Any] = None
) -> Tuple[Optional[InterfacePort], Optional[InterfacePort]]:
    """
    Finds matching interface ports between two mating parts deterministically using typed contracts:
    1. Direct contract lookup via mate.mate_port_id or InterfacePort.mate_key
    2. Exact feature name lookup via mate.my_feature_name
    3. Matching mate_key contracts between ports
    4. Complementary feature type and matching diameter lookup
    """
    if not partner_ports or not my_ports:
        return None, None

    mate_port_id = getattr(mate, "mate_port_id", None) if mate else None
    mate_feature = getattr(mate, "my_feature_name", None) if mate else None
    mate_d = getattr(mate, "my_feature_diameter", None) if mate else None

    # 1. Direct contract lookup via mate.mate_port_id
    if mate_port_id:
        target_p = partner_ports.get(mate_port_id)
        if not target_p:
            target_p = next((p for p in partner_ports.values() if getattr(p, "mate_key", None) == mate_port_id), None)
        if target_p:
            my_p = None
            if mate_feature and mate_feature in my_ports:
                my_p = my_ports[mate_feature]
            if not my_p:
                my_p = next((p for p in my_ports.values() if getattr(p, "mate_key", None) == mate_port_id or p.name == mate_feature), None)
            if not my_p:
                is_target_hole = target_p.feature_type in ("hole", "bore")
                for p in my_ports.values():
                    if is_target_hole and p.feature_type in ("shaft", "pin", "bolt", "fastener"):
                        my_p = p
                        break
                    elif not is_target_hole and p.feature_type in ("hole", "bore"):
                        my_p = p
                        break
            if my_p:
                return target_p, my_p

    # 2. Exact name match shortcut if mate specifies an exact port name in both
    if mate_feature and mate_feature in partner_ports and mate_feature in my_ports:
        return partner_ports[mate_feature], my_ports[mate_feature]

    # 3. Check for matching mate_key between my_ports and partner_ports
    for m_port in my_ports.values():
        m_key = getattr(m_port, "mate_key", None)
        if m_key:
            target_p = partner_ports.get(m_key)
            if not target_p:
                target_p = next((p for p in partner_ports.values() if getattr(p, "mate_key", None) == m_key), None)
            if target_p:
                return target_p, m_port

    # 4. Typed complementary feature matching (e.g. hole <-> shaft, face <-> face)
    candidates = []
    for p_name, p_port in partner_ports.items():
        p_type = (p_port.feature_type or "face").lower()
        is_p_hole = p_type in ("hole", "bore") or "hole" in p_name.lower() or "bore" in p_name.lower()
        is_p_shaft = p_type in ("shaft", "pin", "bolt", "fastener") or "shaft" in p_name.lower() or "pin" in p_name.lower()

        for m_name, m_port in my_ports.items():
            m_type = (m_port.feature_type or "face").lower()
            is_m_hole = m_type in ("hole", "bore") or "hole" in m_name.lower() or "bore" in m_name.lower()
            is_m_shaft = m_type in ("shaft", "pin", "bolt", "fastener") or "shaft" in m_name.lower() or "pin" in m_name.lower()

            is_complementary = (is_p_hole and is_m_shaft) or (is_p_shaft and is_m_hole)
            is_same_type = (p_type == m_type)

            if not (is_complementary or is_same_type):
                continue

            d_diff = 0.0
            if p_port.diameter is not None and m_port.diameter is not None:
                d_diff = abs(p_port.diameter - m_port.diameter)
                if d_diff > 5.0 and not is_complementary:
                    continue

            # Score deterministic match based on contracts
            score = 0.0
            if is_complementary:
                score += 10.0
            if mate_d is not None:
                if p_port.diameter is not None and abs(p_port.diameter - mate_d) <= 0.5:
                    score += 5.0
                if m_port.diameter is not None and abs(m_port.diameter - mate_d) <= 0.5:
                    score += 5.0
            if p_port.diameter is not None and m_port.diameter is not None:
                score -= d_diff

            candidates.append((score, p_port, m_port))

    if candidates:
        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1], candidates[0][2]

    # Fallback to first available port pair if no positive match

def _align_port_vectors(
    part_solid: Any,
    my_port: InterfacePort,
    target_port: InterfacePort,
    partner_solid: Optional[Any] = None,
    is_face_mate: bool = False
) -> Tuple[Any, Optional[Dict[str, Any]], Tuple[float, float, float]]:
    """
    Deterministically computes 3D normal/axis alignment rotation between my_port and target_port.
    Rotates part_solid around my_port.position so its normal or cylindrical axis aligns with target_port.
    Returns: (rotated_solid, rotation_info, translation_delta)
    """
    v_from = getattr(my_port, "direction", None) or (0.0, 0.0, 1.0)
    v_to = getattr(target_port, "direction", None) or (0.0, 0.0, 1.0)
    p_from = getattr(my_port, "position", (0.0, 0.0, 0.0))
    p_to = getattr(target_port, "position", (0.0, 0.0, 0.0))

    import numpy as np
    import math

    u = np.array(v_from, dtype=float)
    v = np.array(v_to, dtype=float)
    u_norm = np.linalg.norm(u)
    v_norm = np.linalg.norm(v)

    delta = (p_to[0] - p_from[0], p_to[1] - p_from[1], p_to[2] - p_from[2])
    if u_norm < 1e-6 or v_norm < 1e-6:
        return part_solid, None, delta

    u = u / u_norm
    v = v / v_norm

    # For face mates, outward normals oppose each other (u -> -v).
    # For shafts/holes/cylinders/pins: check both forward (u -> v) and reverse (u -> -v).
    candidates = [-v] if is_face_mate else [v, -v]

    best_solid = part_solid
    best_rot = None
    best_trans = delta
    min_overlap = float("inf")

    for target_v in candidates:
        dot = float(np.dot(u, target_v))
        if abs(dot - 1.0) < 1e-4:
            rot_s = part_solid
            r_info = None
        elif abs(dot + 1.0) < 1e-4:
            perp = np.array([1, 0, 0]) if abs(u[0]) < 0.9 else np.array([0, 1, 0])
            axis = np.cross(u, perp)
            axis = axis / np.linalg.norm(axis)
            axis_pt = (round(float(p_from[0] + axis[0]), 4), round(float(p_from[1] + axis[1]), 4), round(float(p_from[2] + axis[2]), 4))
            p_from_tuple = (round(float(p_from[0]), 4), round(float(p_from[1]), 4), round(float(p_from[2]), 4))
            rot_s = part_solid.rotate(p_from_tuple, axis_pt, 180.0)
            r_info = {"center": p_from_tuple, "axis": axis_pt, "angle": 180.0}
        else:
            axis = np.cross(u, target_v)
            axis = axis / np.linalg.norm(axis)
            angle_deg = math.degrees(math.acos(np.clip(dot, -1.0, 1.0)))
            axis_pt = (round(float(p_from[0] + axis[0]), 4), round(float(p_from[1] + axis[1]), 4), round(float(p_from[2] + axis[2]), 4))
            p_from_tuple = (round(float(p_from[0]), 4), round(float(p_from[1]), 4), round(float(p_from[2]), 4))
            rot_s = part_solid.rotate(p_from_tuple, axis_pt, angle_deg)
            r_info = {"center": p_from_tuple, "axis": axis_pt, "angle": round(angle_deg, 2)}

        cand_solid = rot_s.translate(delta)
        if partner_solid is not None:
            try:
                ps_obj = _get_shape_obj(partner_solid)
                cs_obj = _get_shape_obj(cand_solid)
                overlap = ps_obj.intersect(cs_obj).Volume()
            except Exception:
                overlap = 0.0
        else:
            overlap = 0.0

        if overlap < min_overlap:
            min_overlap = overlap
            best_solid = rot_s
            best_rot = r_info
            best_trans = delta
            if overlap == 0.0:
                break

    return best_solid, best_rot, best_trans


class AssemblyAgent:
    """Mates verified CAD solids deterministically into a single multi-part assembly."""

    def __init__(self, gateway_client: Optional[Any] = None):
        self.last_transforms = {}

    async def assemble_parts(
        self,
        graph: AssemblyGraph,
        solids: Dict[str, Any],
        interfaces: Optional[Dict[str, Dict[str, InterfacePort]]] = None,
        positioning_repair_prompt: str = ""
    ) -> Tuple[Dict[str, Any], Any]:
        """
        Positions verified solids deterministically based on InterfacePorts and returns:
        (Dict of transformed shapes, top-level cq.Assembly object).
        """
        AgentToolbox.enforce("assembly_agent", "cad_kernel_assembly")
        if interfaces is None:
            interfaces = {}

        self.last_transforms = {}
        transformed_solids: Dict[str, Any] = {}
        cq_assembly = cq.Assembly()

        if not graph.parts:
            return transformed_solids, cq_assembly

        # 0. Datum Normalization:
        # Standardize all part solids to baseline Z_min = 0, and shift their exported InterfacePorts identically.
        # This prevents axial offsets when parts are modeled centered at Z=0 ([-H/2, H/2]) vs base at Z=0 ([0, H]).
        normalized_solids: Dict[str, Any] = {}
        normalized_interfaces: Dict[str, Dict[str, InterfacePort]] = {}
        dz_map: Dict[str, float] = {}

        for pid, raw_s in solids.items():
            s_obj = _get_shape_obj(raw_s)
            if not s_obj:
                continue
            bb = s_obj.BoundingBox()
            dz = -bb.zmin if abs(bb.zmin) > 1e-4 else 0.0
            dz_map[pid] = dz
            if abs(dz) > 1e-4:
                s_obj = s_obj.translate((0, 0, dz))
            normalized_solids[pid] = s_obj

            p_map = interfaces.get(pid, {})
            norm_p_map = {}
            for pname, port in p_map.items():
                if abs(dz) > 1e-4:
                    new_pos = (port.position[0], port.position[1], port.position[2] + dz)
                    norm_port = port.model_copy(update={"position": new_pos})
                else:
                    norm_port = port
                norm_p_map[pname] = norm_port
            normalized_interfaces[pid] = norm_p_map

        # 1. Base Part: Grounded component, housing/casing/frame, or the part with the most mates
        base_part_spec = next(
            (p for p in graph.parts if (
                p.part_type in ("base", "frame", "housing", "casing", "chassis", "stator")
                or getattr(p, "geometry_form", "") in ("housing", "casing", "box_enclosure", "base_plate")
                or any(kw in p.id.lower() or kw in p.name.lower() for kw in ["housing", "casing", "base", "frame", "stator"])
            )),
            None
        )
        if not base_part_spec:
            for j in graph.joints:
                if j.type in ("rigid", "ground"):
                    p_match = next((p for p in graph.parts if p.id in (j.part_a, j.part_b)), None)
                    if p_match:
                        base_part_spec = p_match
                        break
        if not base_part_spec:
            base_part_spec = max(graph.parts, key=lambda p: len(p.mates)) if graph.parts else graph.parts[0]

        base_solid = normalized_solids.get(base_part_spec.id)
        if base_solid:
            self.last_transforms[base_part_spec.id] = {
                "dz": dz_map.get(base_part_spec.id, 0.0),
                "translate": (0.0, 0.0, 0.0),
                "rotate_z": 0.0
            }
            transformed_solids[base_part_spec.id] = base_solid
            cq_assembly.add(base_solid, name=base_part_spec.id, color=cq.Color(0.8, 0.8, 0.8, 1.0))

        # 2. Position Partner Parts relative to Base Part via Topological Mating Traversal (BFS)
        # Guarantees parent parts are transformed and placed BEFORE child parts
        from collections import deque

        # Build adjacency map of mates
        adjacency: Dict[str, List[str]] = {p.id: [] for p in graph.parts}
        part_spec_map = {p.id: p for p in graph.parts}
        for p in graph.parts:
            for m in p.mates:
                if m.partner_id in adjacency and m.partner_id != p.id:
                    adjacency[p.id].append(m.partner_id)
                    adjacency[m.partner_id].append(p.id)

        # BFS queue starting from base_part_spec
        placed_ids = {base_part_spec.id}
        queue = deque([base_part_spec.id])
        traversal_order: List[PartSpec] = []

        while queue:
            curr_id = queue.popleft()
            for neighbor_id in adjacency.get(curr_id, []):
                if neighbor_id not in placed_ids and neighbor_id in part_spec_map:
                    placed_ids.add(neighbor_id)
                    queue.append(neighbor_id)
                    traversal_order.append(part_spec_map[neighbor_id])

        # Add any disconnected parts that weren't caught in BFS
        for p in graph.parts:
            if p.id not in placed_ids:
                placed_ids.add(p.id)
                traversal_order.append(p)

        for part_spec in traversal_order:
            part_solid = normalized_solids.get(part_spec.id)
            if not part_solid:
                continue

            # Look up mate context: find a partner that is ALREADY placed in transformed_solids
            mate = None
            partner_id = base_part_spec.id
            if part_spec.mates:
                # Prefer mate whose partner is already placed
                m_placed = next((m for m in part_spec.mates if m.partner_id in transformed_solids), None)
                mate = m_placed or part_spec.mates[0]
                partner_id = mate.partner_id if mate.partner_id in transformed_solids else base_part_spec.id
            elif base_part_spec.id in transformed_solids:
                partner_id = base_part_spec.id

            p_ports = normalized_interfaces.get(partner_id, {})
            my_ports = normalized_interfaces.get(part_spec.id, {})

            target_port, my_port = _find_compatible_ports(p_ports, my_ports, mate)

            if target_port and my_port:
                partner_solid_obj = transformed_solids.get(partner_id)
                is_face = (my_port.feature_type == "face" and target_port.feature_type == "face")

                # 3D Normal Vector Alignment (deterministic rotation to match port orientations)
                part_solid, rot_3d, (tx, ty, tz) = _align_port_vectors(
                    part_solid, my_port, target_port, partner_solid=partner_solid_obj, is_face_mate=is_face
                )

                # Ground-truth physical hole snapping: snap fastener/shaft to exact cylindrical hole in partner solid
                is_pin_or_shaft = my_port.feature_type in ("shaft", "pin", "bolt", "fastener")
                is_hole = target_port.feature_type in ("hole", "bore")
                if partner_solid_obj and is_pin_or_shaft and is_hole:
                    try:
                        cyl_faces = [f for f in partner_solid_obj.Faces() if f.geomType() == "CYLINDER"]
                        real_holes = [f for f in cyl_faces if not partner_solid_obj.isInside(f.Center())]
                        if real_holes:
                            best_h = min(real_holes, key=lambda f: (
                                (f.Center().x - target_port.position[0])**2 + (f.Center().y - target_port.position[1])**2
                            ))
                            h_c = best_h.Center()
                            h_bb = best_h.BoundingBox()
                            t_dir = getattr(target_port, "direction", (0, 0, 1))
                            if abs(t_dir[2]) > 0.8:
                                # Vertical hole: align along Z for head seating
                                tx = h_c.x - my_port.position[0]
                                ty = h_c.y - my_port.position[1]
                                tz = h_bb.zmax - my_port.position[2]
                            else:
                                # Horizontal or off-axis hole: snap to exact cylinder center
                                tx = h_c.x - my_port.position[0]
                                ty = h_c.y - my_port.position[1]
                                tz = h_c.z - my_port.position[2]
                    except Exception:
                        pass

                # 1. Read axial_offsets from shared_parameters or master_skeleton
                shared_p = graph.shared_parameters if graph.shared_parameters is not None else graph.master_skeleton
                axial_offsets = shared_p.get("axial_offsets", {}) if isinstance(shared_p, dict) else {}
                has_axial_offset = False
                if part_spec.id in axial_offsets:
                    try:
                        tz += float(axial_offsets[part_spec.id])
                        has_axial_offset = True
                    except (ValueError, TypeError):
                        pass

                # 2. Apply positioning repair delta if requested by AssemblyRepairAgent
                if positioning_repair_prompt and part_spec.id in positioning_repair_prompt:
                    # Check for explicit axial or spatial shifts in the repair instruction
                    import re
                    shift_m = re.search(r"(?:stack|shift|offset|translate)\s*(?:by|along)?\s*(?:[xyzXYZ]\s*=\s*)?([+-]?[0-9.]+)\s*mm", positioning_repair_prompt, re.IGNORECASE)
                    if shift_m:
                        try:
                            delta_z = float(shift_m.group(1))
                            if not has_axial_offset:
                                tz += delta_z
                                has_axial_offset = True
                        except Exception:
                            pass

                # Universal kinematic alignment for mechanisms (gears, linkages, shafts, cams)
                part_k = part_spec.kinematic_params or {}

                # Check if this part has an off-axis orbit/center distance defined
                c_dist = float(
                    part_k.get("center_distance") or
                    part_k.get("orbit_radius") or
                    part_k.get("eccentricity") or
                    0.0
                )
                if c_dist == 0.0 and mate and mate.mate_type == "gear_mesh":
                    is_internal = any(kw in mate.my_feature_name.lower() or kw in mate.partner_id.lower() for kw in ["internal", "ring", "annulus", "circular_spline"])
                    if not is_internal:
                        c_dist = float(
                            shared_p.get("center_to_center_distance") or
                            shared_p.get("orbit_radius") or
                            shared_p.get("center_distance") or 0.0
                        )

                if c_dist > 0.0:
                    tx = c_dist
                    ty = 0.0
                else:
                    # Coaxial machine component alignment:
                    # Only zero out tx/ty if BOTH my_port and target_port are coaxial near (0, 0),
                    # preserving explicit offsets for off-axis hole snapping!
                    my_is_central = (my_port.position[0]**2 + my_port.position[1]**2) < 0.25
                    target_is_central = (target_port.position[0]**2 + target_port.position[1]**2) < 0.25
                    if my_is_central and target_is_central:
                        tx = 0.0
                        ty = 0.0

                # Universal Coaxial Stacking: If both parts share the central rotation axis (0, 0),
                # prevent two solid bodies from occupying the exact same axial span.
                partner_solid = transformed_solids.get(partner_id) or transformed_solids.get(base_part_spec.id)
                if partner_solid:
                    cand = part_solid.translate((tx, ty, tz))
                    try:
                        overlap_vol = cand.intersect(partner_solid).Volume()
                    except Exception:
                        overlap_vol = 0.0

                    is_nested_mechanism = (
                        (mate and getattr(mate, "mate_type", "") in ("hole_shaft", "shaft_hole", "gear_mesh", "revolute", "cylindrical", "press_fit", "compliant_fit"))
                        or (my_port.feature_type in ("shaft", "pin", "bolt", "fastener") and target_port.feature_type in ("hole", "bore"))
                        or (my_port.feature_type in ("hole", "bore") and target_port.feature_type in ("shaft", "pin", "bolt", "fastener"))
                        or (my_port.feature_type == "gear_mesh" or target_port.feature_type == "gear_mesh")
                    )

                    vol_p = part_solid.Volume() if hasattr(part_solid, "Volume") else 1.0
                    # If severe volume collision (> 30% or > 50 mm³) occurs coaxially on non-nested parts without explicit axial_offsets
                    if not has_axial_offset and not is_nested_mechanism and overlap_vol > 50.0 and (overlap_vol / max(1.0, vol_p)) > 0.30:
                        bb_partner = partner_solid.BoundingBox()
                        bb_me = part_solid.translate((tx, ty, 0)).BoundingBox()
                        # If target port is at or near top face, stack above partner (+Z)
                        if target_port.position[2] >= bb_partner.zmax - 1.0:
                            tz = bb_partner.zmax - bb_me.zmin
                        # If target port is at or near bottom face, stack below partner (-Z)
                        elif target_port.position[2] <= bb_partner.zmin + 1.0:
                            tz = bb_partner.zmin - bb_me.zmax
                        else:
                            # Stack adjacent along normal vector of target port
                            t_dir_z = getattr(target_port, "direction", (0, 0, 1))[2]
                            if t_dir_z < -0.5:
                                tz = bb_partner.zmin - bb_me.zmax
                            else:
                                tz = bb_partner.zmax - bb_me.zmin

                # Sibling Coaxial Collision Prevention:
                # If multiple components share the same shaft/datum (e.g. multiple blocks or bearings on a shaft),
                # prevent them from occupying the exact same axial location if no axial offset was explicitly set.
                if not has_axial_offset:
                    for other_id, other_solid in transformed_solids.items():
                        if other_id == partner_id or other_id == part_spec.id:
                            continue
                        # Only check if other_solid has no direct mating connection to this part
                        has_direct_mate = any(m.partner_id == other_id for m in part_spec.mates)
                        if has_direct_mate:
                            continue

                        cand = part_solid.translate((tx, ty, tz))
                        try:
                            other_overlap = cand.intersect(other_solid).Volume()
                        except Exception:
                            other_overlap = 0.0

                        if other_overlap > 1.0:
                            bb_other = other_solid.BoundingBox()
                            bb_me = cand.BoundingBox()
                            # Check bounds of partner_solid (e.g. shaft) so we stay on the physical partner
                            bb_partner = partner_solid.BoundingBox() if partner_solid else None
                            if bb_partner and (bb_other.zmax + (bb_me.zmax - bb_me.zmin) + 10.0 > bb_partner.zmax):
                                # If shifting +Z would push beyond the shaft's top, shift -Z (towards shaft body)
                                shift = (bb_other.zmin - bb_me.zmax) - 10.0
                            else:
                                shift = (bb_other.zmax - bb_me.zmin) + 10.0
                            tz += shift



                best_angle = 0.0
                # Universal 1D tooth/cam mesh angle sweep to eliminate tooth tip clash
                if partner_solid:
                    cand_trans = part_solid.translate((tx, ty, tz))
                    try:
                        cand_overlap = cand_trans.intersect(partner_solid).Volume()
                    except Exception:
                        cand_overlap = 0.0

                    # If minor interference exists (typical of un-clocked gear teeth or cam lobes)
                    if 0.01 < cand_overlap < 50.0:
                        min_overlap = cand_overlap
                        for deg in range(0, 360, 3):
                            cand = part_solid.rotate((0, 0, 0), (0, 0, 1), float(deg)).translate((tx, ty, tz))
                            try:
                                overlap = cand.intersect(partner_solid).Volume()
                            except Exception:
                                overlap = 0.0
                            if overlap < min_overlap:
                                min_overlap = overlap
                                best_angle = float(deg)
                            if min_overlap == 0.0:
                                break
                        if best_angle != 0.0:
                            part_solid = part_solid.rotate((0, 0, 0), (0, 0, 1), best_angle)

                # Record transforms for assembly script generation
                self.last_transforms[part_spec.id] = {
                    "dz": dz_map.get(part_spec.id, 0.0),
                    "translate": (round(tx, 3), round(ty, 3), round(tz, 3)),
                    "rotate_z": round(best_angle, 2),
                    "rotate_3d": rot_3d
                }

                # Apply final translation
                moved_solid = part_solid.translate((tx, ty, tz))

                # Multi-instance symmetric circular patterns (e.g. planetary gears or multi-disc assemblies)
                num_instances = int(part_k.get("num_instances") or shared_p.get("num_instances") or 1) if c_dist > 0.0 else 1
                if num_instances > 1:
                    step_deg = 360.0 / num_instances
                    for k in range(num_instances):
                        p_angle = k * step_deg
                        meshed_inst = moved_solid.rotate((0, 0, 0), (0, 0, 1), p_angle)
                        p_id = f"{part_spec.id}_{k+1}" if k > 0 else part_spec.id
                        transformed_solids[p_id] = meshed_inst
                        cq_assembly.add(meshed_inst, name=p_id, color=cq.Color(0.2, 0.6, 0.9, 1.0))
                else:
                    transformed_solids[part_spec.id] = moved_solid
                    cq_assembly.add(moved_solid, name=part_spec.id, color=cq.Color(0.2, 0.6, 0.9, 1.0))
            else:
                # Fallback: check explicit axial_offsets or stack adjacent along Z if overlapping base solid
                partner_solid = transformed_solids.get(partner_id) or transformed_solids.get(base_part_spec.id)
                fallback_tz = 0.0
                shared_p = graph.shared_parameters if graph.shared_parameters is not None else graph.master_skeleton
                axial_offsets = shared_p.get("axial_offsets", {}) if isinstance(shared_p, dict) else {}
                if part_spec.id in axial_offsets:
                    try:
                        fallback_tz = float(axial_offsets[part_spec.id])
                        part_solid = part_solid.translate((0, 0, fallback_tz))
                    except (ValueError, TypeError):
                        pass
                elif partner_solid:
                    bb_partner = partner_solid.BoundingBox()
                    bb_me = part_solid.BoundingBox()
                    if part_solid.intersect(partner_solid).Volume() > 10.0:
                        fallback_tz = -bb_me.zmax + bb_partner.zmin
                        part_solid = part_solid.translate((0, 0, fallback_tz))
                self.last_transforms[part_spec.id] = {
                    "dz": dz_map.get(part_spec.id, 0.0),
                    "translate": (0.0, 0.0, round(fallback_tz, 3)),
                    "rotate_z": 0.0
                }
                transformed_solids[part_spec.id] = part_solid
                cq_assembly.add(part_solid, name=part_spec.id, color=cq.Color(0.5, 0.5, 0.5, 1.0))

        return transformed_solids, cq_assembly

    def generate_assembly_script(self, graph: AssemblyGraph, output_dir: str) -> str:
        """
        Generates an executable CadQuery assembly.py script that loads component scripts,
        applies verified spatial transformations, and builds cq.Assembly.
        """
        from pathlib import Path
        out_path = Path(output_dir)
        lines = [
            '"""',
            f'ForgeAgent Multi-Part Assembly Script: {graph.name}',
            'Auto-generated executable CadQuery assembly script.',
            '"""',
            '',
            'from pathlib import Path',
            'import cadquery as cq',
            '',
            'CURRENT_DIR = Path(__file__).parent.resolve()',
            '',
            'def load_part(script_rel_path: str):',
            '    full_path = CURRENT_DIR / script_rel_path',
            '    scope = {}',
            '    code = full_path.read_text(encoding="utf-8")',
            '    exec(code, scope, scope)',
            '    if "result" not in scope:',
            '        raise ValueError(f"Script {script_rel_path} did not produce a `result` variable.")',
            '    return scope["result"]',
            '',
            'assembly = cq.Assembly()',
            'colors = [',
            '    cq.Color(0.2, 0.4, 0.7, 0.9),',
            '    cq.Color(0.8, 0.2, 0.2, 0.8),',
            '    cq.Color(0.9, 0.7, 0.1, 1.0),',
            '    cq.Color(0.3, 0.7, 0.3, 0.9),',
            '    cq.Color(0.6, 0.3, 0.8, 0.9),',
            ']',
            ''
        ]

        part_files = {}
        for p in graph.parts:
            sub = out_path / p.id
            if sub.is_dir():
                exact_match = sub / f"{p.id}.py"
                if exact_match.is_file():
                    part_files[p.id] = f"{p.id}/{p.id}.py"
                    continue
                valid_pys = [f for f in sub.glob("*.py") if not f.name.startswith("failed_")]
                if valid_pys:
                    # Pick most recent non-failed script
                    best_f = max(valid_pys, key=lambda f: f.stat().st_mtime)
                    part_files[p.id] = f"{p.id}/{best_f.name}"
                    continue
            exact_root = out_path / f"{p.id}.py"
            if exact_root.is_file():
                part_files[p.id] = f"{p.id}.py"
                continue
            root_pys = [f for f in out_path.glob(f"{p.id}*.py") if not f.name.startswith("failed_") and not f.name.endswith("_assembly.py")]
            if root_pys:
                best_rf = max(root_pys, key=lambda f: f.stat().st_mtime)
                part_files[p.id] = best_rf.name

        for idx, (pid, rel_path) in enumerate(part_files.items()):
            color_idx = idx % 5
            t = self.last_transforms.get(pid, {})
            dz = t.get("dz", 0.0)
            tx, ty, tz = t.get("translate", (0.0, 0.0, 0.0))
            rot_z = t.get("rotate_z", 0.0)

            lines.append(f'# Component: {pid}')
            lines.append(f'{pid} = load_part("{rel_path}")')
            rot_3d = t.get("rotate_3d")
            if rot_3d:
                lines.append(f'{pid} = {pid}.rotate({rot_3d["center"]}, {rot_3d["axis"]}, {rot_3d["angle"]})')
            if abs(dz) > 1e-4:
                lines.append(f'{pid} = {pid}.translate((0, 0, {dz}))')
            if abs(rot_z) > 1e-4:
                lines.append(f'{pid} = {pid}.rotate((0, 0, 0), (0, 0, 1), {rot_z})')
            if any(abs(c) > 1e-4 for c in (tx, ty, tz)):
                lines.append(f'{pid} = {pid}.translate(({tx}, {ty}, {tz}))')
            lines.append(f'assembly.add({pid}, name="{pid}", color=colors[{color_idx}])')
            lines.append('')

        lines.extend([
            'if "show_object" in globals():',
            '    show_object(assembly)',
            '',
            'if __name__ == "__main__":',
            f'    out_step = CURRENT_DIR / "{graph.name}_assembly.step"',
            f'    out_stl = CURRENT_DIR / "{graph.name}_assembly.stl"',
            '    print(f"Exporting assembly to {out_step.name} and {out_stl.name}...")',
            '    try:',
            '        assembly.save(str(out_step), "STEP")',
            '        assembly.save(str(out_stl), "STL")',
            '        print("✅ Assembly complete!")',
            '    except Exception as e:',
            '        print(f"⚠️ Export note: {e}")',
            ''
        ])

        script_content = "\n".join(lines)
        out_file = out_path / "assembly.py"
        out_file.write_text(script_content, encoding="utf-8")
        (out_path / f"{graph.name}_assembly.py").write_text(script_content, encoding="utf-8")
        return script_content
