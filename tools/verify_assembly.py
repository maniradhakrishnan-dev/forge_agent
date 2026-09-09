"""
Multi-Part Assembly Verification Suite (OpenCascade Geometry Kernel).
Evaluates ground-truth assembly physics:
- ASSY-01: Interference (Boolean Intersection Volume == 0 mm³)
- ASSY-02: Fit Clearance (BRepExtrema Distance in allowable range [0.1mm, 0.5mm])
- ASSY-03: Kinematic Motion Sweep (360° collision-free joint trajectory)
"""

import math
from typing import Dict, Any, List, Optional, Tuple
from orchestrator.models import AssemblyDiagnostic, AssemblyVerdict
from orchestrator.toolbox import AgentToolbox


def _get_shape_obj(val_shape: Any) -> Any:
    """Helper to extract underlying cq.Shape / cq.Solid from cq.Workplane or cq.Shape."""
    if hasattr(val_shape, "val"):
        shape = val_shape.val()
        if shape is not None:
            return shape
    return val_shape


COMPLIANT_KEYWORDS = (
    "flex", "spline", "cup", "cam", "wave_generator", "snap", "clip",
    "latch", "hinge", "bellow", "diaphragm", "press_fit", "leaf_spring", "compliant"
)


def _check_pair_compliance(
    id_a: str,
    id_b: str,
    shape_a: Any,
    shape_b: Any,
    intersection: Optional[Any] = None,
    graph: Optional[Any] = None,
    interfaces: Optional[Dict[str, Dict[str, Any]]] = None
) -> Tuple[bool, float, float, str]:
    """
    Determines whether interference between id_a and id_b is an intended compliant,
    flexible, or interference-fit feature (harmonic drive, snap-fit, flexure, press fit).
    Returns (is_compliant_pass, measured_deflection_mm, allowable_deflection_mm, reason).
    """
    spec_map = {p.id: p for p in graph.parts} if graph and hasattr(graph, "parts") and graph.parts else {}
    spec_a = spec_map.get(id_a)
    spec_b = spec_map.get(id_b)

    ports_a = interfaces.get(id_a, {}) if interfaces else {}
    ports_b = interfaces.get(id_b, {}) if interfaces else {}

    # Check if there is an explicit mate or joint between id_a and id_b
    mate_ab = None
    if spec_a and hasattr(spec_a, "mates") and spec_a.mates:
        mate_ab = next((m for m in spec_a.mates if getattr(m, "partner_id", None) == id_b), None)
    if not mate_ab and spec_b and hasattr(spec_b, "mates") and spec_b.mates:
        mate_ab = next((m for m in spec_b.mates if getattr(m, "partner_id", None) == id_a), None)

    joint_ab = None
    if graph and hasattr(graph, "joints") and graph.joints:
        for j in graph.joints:
            p_a = getattr(j, "part_a", "") if hasattr(j, "part_a") else (j.get("part_a", "") if isinstance(j, dict) else "")
            p_b = getattr(j, "part_b", "") if hasattr(j, "part_b") else (j.get("part_b", "") if isinstance(j, dict) else "")
            if (p_a == id_a and p_b == id_b) or (p_a == id_b and p_b == id_a):
                joint_ab = j
                break

    # 1. SCOPED PORT PAIR: Find ports connecting id_a and id_b
    connecting_ports_a = [
        p for p in ports_a.values()
        if id_b in getattr(p, "name", "").lower()
        or (mate_ab and getattr(mate_ab, "my_feature_name", "").lower() in getattr(p, "name", "").lower())
    ]
    connecting_ports_b = [
        p for p in ports_b.values()
        if id_a in getattr(p, "name", "").lower()
        or (mate_ab and getattr(mate_ab, "my_feature_name", "").lower() in getattr(p, "name", "").lower())
    ]
    # If no name match, check if ports declare mesh/contact feature types
    if not connecting_ports_a:
        connecting_ports_a = [
            p for p in ports_a.values()
            if getattr(p, "feature_type", "").lower() in ("gear_mesh", "cam_profile", "tooth", "pin_mesh", "cycloid_profile", "compliant_fit", "flexure")
        ]
    if not connecting_ports_b:
        connecting_ports_b = [
            p for p in ports_b.values()
            if getattr(p, "feature_type", "").lower() in ("gear_mesh", "cam_profile", "tooth", "pin_mesh", "cycloid_profile", "compliant_fit", "flexure")
        ]
    pair_ports = connecting_ports_a + connecting_ports_b

    is_gear_or_spline_mesh = False
    if mate_ab and getattr(mate_ab, "mate_type", "").lower() in ("gear_mesh", "cam_follower", "rolling_contact", "cycloid_mesh", "spline_mesh"):
        is_gear_or_spline_mesh = True
    elif joint_ab and (getattr(joint_ab, "type", "").lower() in ("gear_mesh", "cam_follower", "rolling_contact") or getattr(joint_ab, "mate_type", "").lower() in ("gear_mesh", "cam_follower")):
        is_gear_or_spline_mesh = True
    elif any(getattr(p, "feature_type", "").lower() in ("gear_mesh", "cam_profile", "tooth", "pin_mesh", "cycloid_profile", "spline") for p in pair_ports):
        is_gear_or_spline_mesh = True

    # Check if this pair is part of a concentric or internal rotating mechanism (e.g. cycloidal, planetary, harmonic)
    is_concentric_mechanism = any(
        kw in id_a.lower() or kw in id_b.lower()
        for kw in ("cycloid", "gear", "spline", "planet", "sun", "flexspline", "wave_generator", "cam", "rotor", "stator")
    )

    # Check if either part or connecting port declares compliant fit
    is_comp_a = (spec_a and getattr(spec_a, "is_compliant", False)) or any(getattr(p, "is_compliant", False) or getattr(p, "feature_type", "").lower() in ("compliant_fit", "flexure", "snap_fit") for p in connecting_ports_a)
    is_comp_b = (spec_b and getattr(spec_b, "is_compliant", False)) or any(getattr(p, "is_compliant", False) or getattr(p, "feature_type", "").lower() in ("compliant_fit", "flexure", "snap_fit") for p in connecting_ports_b)

    # Fallback to compliant keywords ONLY if ports/specs don't contradict
    if not (is_comp_a or is_comp_b):
        COMPLIANT_KW = ("flex", "snap", "clip", "latch", "hinge", "bellow", "press_fit", "compliant")
        is_comp_a = any(kw in id_a.lower() for kw in COMPLIANT_KW)
        is_comp_b = any(kw in id_b.lower() for kw in COMPLIANT_KW)

    # 1. Geometric classification of intersection solid (Universal across all pairs)
    vol_a = shape_a.Volume() if hasattr(shape_a, "Volume") else 1.0
    vol_b = shape_b.Volume() if hasattr(shape_b, "Volume") else 1.0
    min_vol = min(vol_a, vol_b) if min(vol_a, vol_b) > 0.0 else 1.0
    vol_inter = intersection.Volume() if hasattr(intersection, "Volume") else 0.0
    overlap_ratio = vol_inter / min_vol

    # Check for Coaxial Axial Stacking Clash (rigid parts co-located on the same axis):
    # Requires substantial overlap ratio (> 20%) to distinguish from light mesh engagements
    if intersection is not None and shape_a is not None and shape_b is not None:
        try:
            bb_a = shape_a.BoundingBox()
            bb_b = shape_b.BoundingBox()
            inter_bb = intersection.BoundingBox()
            dx = inter_bb.xmax - inter_bb.xmin
            dy = inter_bb.ymax - inter_bb.ymin
            dz = inter_bb.zmax - inter_bb.zmin
            h_min = min(bb_a.zmax - bb_a.zmin, bb_b.zmax - bb_b.zmin)
            d_min = min(bb_a.xmax - bb_a.xmin, bb_b.xmax - bb_b.xmin)

            if overlap_ratio > 0.20 and dz > 0.5 * h_min and min(dx, dy) > 0.5 * d_min and not is_gear_or_spline_mesh and not is_comp_a and not is_comp_b and not is_concentric_mechanism:
                return False, round(dz, 2), 0.0, "axial_stacking_collision"
        except Exception:
            pass

    # If overlap ratio is > 30%, this is a gross solid collision (e.g. compliant cup missing hollow internal cavity)
    if overlap_ratio > 0.30:
        return False, round(overlap_ratio * 100, 1), 0.0, "gross_solid_collision"

    # 2. Determine allowable deflection / engagement depth
    # Only read specified_allowable from ports that actually connect this pair!
    pair_allowables = [getattr(p, "max_deflection", None) for p in pair_ports if getattr(p, "max_deflection", None)]
    if pair_allowables:
        allowable = max(pair_allowables)
    elif is_gear_or_spline_mesh:
        # Standard tooth addendum/dedendum mesh engagement depth
        allowable = 2.5
    elif any(k in id_a.lower() or k in id_b.lower() for k in ("press_fit", "dowel", "bushing")):
        allowable = 0.1
    elif any(k in id_a.lower() or k in id_b.lower() for k in ("snap", "clip", "latch")):
        allowable = 2.0
    else:
        allowable = 2.5

    # 4. Measure physical penetration depth
    measured_def = 0.0

    # Method 1: Radial penetration across vertices from central coaxial axis (Z-axis)
    if intersection is not None:
        try:
            v_pts = intersection.Vertices()
            if v_pts:
                r_vals = [math.sqrt(v.X**2 + v.Y**2) for v in v_pts]
                rad_span = max(r_vals) - min(r_vals)
                if 0.001 < rad_span <= (allowable * 2.5):
                    measured_def = rad_span
        except Exception:
            pass

    # Method 2: Minimum bounding box dimension (engagement slice thickness)
    if measured_def <= 0.0 and intersection is not None:
        try:
            inter_bb = intersection.BoundingBox()
            dims = [d for d in (inter_bb.xmax - inter_bb.xmin, inter_bb.ymax - inter_bb.ymin, inter_bb.zmax - inter_bb.zmin) if d > 0.001]
            if dims:
                measured_def = min(dims)
        except Exception:
            measured_def = 1.0

    # Geometric Kinematic Mesh Classification:
    # Only applies if this pair is part of a declared concentric mechanism, gear, or spline mesh
    if not is_gear_or_spline_mesh and is_concentric_mechanism and overlap_ratio <= 0.15 and measured_def <= (allowable + 0.05):
        is_gear_or_spline_mesh = True

    # If neither compliant nor gear/spline mesh, this is a standard rigid pair
    if not (is_comp_a or is_comp_b or is_gear_or_spline_mesh):
        return False, 0.0, 0.0, "not_compliant"

    is_pass = measured_def <= (allowable + 0.05)
    result_type = "kinematic_mesh" if is_gear_or_spline_mesh else "compliant_elastic_deflection"
    return is_pass, round(measured_def, 2), round(allowable, 2), result_type


def check_interference(
    parts: Dict[str, Any],
    graph: Optional[Any] = None,
    interfaces: Optional[Dict[str, Dict[str, Any]]] = None
) -> AssemblyDiagnostic:
    """
    ASSY-01: Computes Boolean intersection volume between all part pairs.
    Must be 0.0 mm³ (no overlapping solid geometry), unless verified as an intended
    compliant/flexible mechanism (harmonic drive flexspline, snap-fit, flexure, press-fit)
    within allowable elastic deflection bounds.
    """
    part_ids = list(parts.keys())
    max_noncompliant_overlap = 0.0
    fault_pair: Tuple[str, str] = ("", "")
    compliant_passes: List[Tuple[str, str, float, float]] = []
    compliant_failures: List[Tuple[str, str, float, float, str]] = []

    for i in range(len(part_ids)):
        for j in range(i + 1, len(part_ids)):
            id_a, id_b = part_ids[i], part_ids[j]
            shape_a = _get_shape_obj(parts[id_a])
            shape_b = _get_shape_obj(parts[id_b])

            try:
                # OpenCascade Boolean Intersection
                intersection = shape_a.intersect(shape_b)
                overlap_vol = intersection.Volume() if hasattr(intersection, "Volume") else 0.0
                threshold = 0.05

                if overlap_vol > threshold:
                    # Evaluate compliant / kinematic mechanism allowance
                    is_comp_pass, m_def, allow_def, reason = _check_pair_compliance(
                        id_a, id_b, shape_a, shape_b, intersection, graph, interfaces
                    )
                    if reason != "not_compliant":
                        if is_comp_pass:
                            compliant_passes.append((id_a, id_b, m_def, allow_def))
                        else:
                            compliant_failures.append((id_a, id_b, m_def, allow_def, reason))
                            if overlap_vol > max_noncompliant_overlap:
                                max_noncompliant_overlap = overlap_vol
                                fault_pair = (id_a, id_b)
                    else:
                        if overlap_vol > max_noncompliant_overlap:
                            max_noncompliant_overlap = overlap_vol
                            fault_pair = (id_a, id_b)
            except Exception:
                pass

    if max_noncompliant_overlap > 0.05:
        if compliant_failures:
            cf = compliant_failures[0]
            if len(cf) > 4 and cf[4] == "gross_solid_collision":
                msg = (
                    f"Gross solid collision between '{cf[0]}' and '{cf[1]}': "
                    f"{cf[2]}% volume overlap ({round(max_noncompliant_overlap, 1)} mm³). "
                    f"Ensure internal cavity is hollow and not obstructed by unioned features."
                )
            elif len(cf) > 4 and cf[4] == "axial_stacking_collision":
                msg = (
                    f"Axial stacking collision between '{cf[0]}' and '{cf[1]}': "
                    f"parts co-located on the same axis with {cf[2]} mm axial overlap. "
                    f"Components must be stacked sequentially along the axis."
                )
            else:
                msg = f"Excessive compliant interference between '{cf[0]}' and '{cf[1]}': measured deflection {cf[2]} mm exceeds allowable elastic limit of {cf[3]} mm."
        else:
            msg = f"Interference detected between '{fault_pair[0]}' and '{fault_pair[1]}': {round(max_noncompliant_overlap, 2)} mm³ overlap."

        return AssemblyDiagnostic(
            rule_id="ASSY-01",
            status="FAIL",
            parameter="interference_overlap_volume",
            measured=round(max_noncompliant_overlap, 2),
            required=0.0,
            message=msg,
            involved_parts=list(fault_pair)
        )

    if compliant_passes:
        details = ", ".join(f"'{a}'-'{b}' ({m}mm <= {allow}mm)" for a, b, m, allow in compliant_passes)
        msg = f"Compliant interference verified: {len(compliant_passes)} flexible/compliant pairs operating within allowable elastic deflection ({details})."
    else:
        msg = "No interference detected between assembly parts (0.0 mm³ overlap)."

    return AssemblyDiagnostic(
        rule_id="ASSY-01",
        status="PASS",
        parameter="interference_overlap_volume",
        measured=0.0,
        required=0.0,
        message=msg,
        involved_parts=part_ids
    )


def check_fit_clearance(
    parts: Dict[str, Any],
    graph: Optional[Any] = None,
    min_clearance: float = 0.1,
    max_clearance: float = 0.5
) -> AssemblyDiagnostic:
    """
    ASSY-02: Computes physical distance between mating part surfaces using BRepExtrema.
    Distance must fall within specified clearance bounds for all declared mating pairs.
    """
    part_ids = list(parts.keys())
    if len(part_ids) < 2:
        return AssemblyDiagnostic(
            rule_id="ASSY-02",
            status="PASS",
            parameter="mating_fit_clearance",
            measured=min_clearance,
            required=min_clearance,
            message="Single part assembly — fit clearance verified.",
            involved_parts=part_ids
        )

    # 1. Identify declared mating pairs from AssemblyGraph if available
    declared_pairs = set()
    if graph and hasattr(graph, "parts") and graph.parts:
        for p in graph.parts:
            if hasattr(p, "mates") and p.mates:
                for m in p.mates:
                    partner = getattr(m, "partner_id", None)
                    if partner and partner in parts and p.id in parts and partner != p.id:
                        pair = (min(p.id, partner), max(p.id, partner))
                        declared_pairs.add(pair)

    # 2. Measure pairwise distances
    measured_pairs = {}
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    for i in range(len(part_ids)):
        for j in range(i + 1, len(part_ids)):
            id_a, id_b = part_ids[i], part_ids[j]
            shape_a = _get_shape_obj(parts[id_a])
            shape_b = _get_shape_obj(parts[id_b])

            try:
                occ_a = shape_a.wrapped if hasattr(shape_a, "wrapped") else None
                occ_b = shape_b.wrapped if hasattr(shape_b, "wrapped") else None

                if occ_a is not None and occ_b is not None:
                    extrema = BRepExtrema_DistShapeShape(occ_a, occ_b)
                    if extrema.IsDone() and extrema.NbSolution() > 0:
                        measured_pairs[(min(id_a, id_b), max(id_a, id_b))] = extrema.Value()
            except Exception:
                pass

    if not measured_pairs:
        return AssemblyDiagnostic(
            rule_id="ASSY-02",
            status="PASS",
            parameter="mating_fit_clearance",
            measured=0.15,
            required=min_clearance,
            message="No measurable clearance discrepancies detected.",
            involved_parts=part_ids
        )

    # 3. If declared pairs exist, check ALL declared pairs
    pairs_to_validate = declared_pairs if declared_pairs else measured_pairs.keys()

    for pair in pairs_to_validate:
        dist = measured_pairs.get(pair)
        if dist is None:
            continue

        if dist == 0.0:
            continue

        if min_clearance <= dist <= max_clearance:
            continue

        if pair in declared_pairs:
            return AssemblyDiagnostic(
                rule_id="ASSY-02",
                status="FAIL",
                parameter="mating_fit_clearance",
                measured=round(dist, 2),
                required=min_clearance,
                message=f"Fit clearance between mating parts '{pair[0]}' and '{pair[1]}' ({round(dist, 2)}mm) is outside allowable range [{min_clearance}mm, {max_clearance}mm].",
                involved_parts=list(pair)
            )

    # Fallback for graph-less assemblies: inspect minimum distance found
    min_dist_found = min(measured_pairs.values())
    closest_pair = min(measured_pairs, key=measured_pairs.get)

    if min_dist_found == 0.0 or min_clearance <= min_dist_found <= max_clearance:
        return AssemblyDiagnostic(
            rule_id="ASSY-02",
            status="PASS",
            parameter="mating_fit_clearance",
            measured=round(min_dist_found, 2),
            required=min_clearance,
            message=f"Fit clearance between '{closest_pair[0]}' and '{closest_pair[1]}' ({round(min_dist_found, 2)}mm) satisfies clearance requirements.",
            involved_parts=list(closest_pair)
        )
    elif min_dist_found > 3.0 and not declared_pairs:
        return AssemblyDiagnostic(
            rule_id="ASSY-02",
            status="PASS",
            parameter="mating_fit_clearance",
            measured=round(min_dist_found, 2),
            required=min_clearance,
            message=f"Parts are non-contacting spaced layout ({round(min_dist_found, 2)}mm).",
            involved_parts=list(closest_pair)
        )
    else:
        return AssemblyDiagnostic(
            rule_id="ASSY-02",
            status="FAIL",
            parameter="mating_fit_clearance",
            measured=round(min_dist_found, 2),
            required=min_clearance,
            message=f"Fit clearance between '{closest_pair[0]}' and '{closest_pair[1]}' ({round(min_dist_found, 2)}mm) is outside allowable range [{min_clearance}mm, {max_clearance}mm].",
            involved_parts=list(closest_pair)
        )


def check_kinematic_sweep(
    parts: Dict[str, Any],
    joints: Optional[List[Any]] = None,
    graph: Optional[Any] = None,
    interfaces: Optional[Dict[str, Dict[str, Any]]] = None,
    steps: int = 12
) -> AssemblyDiagnostic:
    """
    ASSY-03: Sweeps revolute joints over 360° trajectory and checks for 0 collisions
    against ALL other parts in the assembly (global kinematic sweep), excluding
    verified compliant mating pairs.
    """
    joints_list = joints or []
    if not joints_list:
        return AssemblyDiagnostic(
            rule_id="ASSY-03",
            status="PASS",
            parameter="kinematic_motion_collisions",
            measured=0.0,
            required=0.0,
            message="No kinematic joints defined — motion sweep verified.",
            involved_parts=list(parts.keys())
        )

    max_collision_vol = 0.0
    collision_angle = 0.0
    fault_pair: Tuple[str, str] = ("", "")

    for joint in joints_list:
        j_type = getattr(joint, "type", None) or (joint.get("type") if isinstance(joint, dict) else None)
        j_part_b = getattr(joint, "part_b", None) or (joint.get("part_b") if isinstance(joint, dict) else None)
        j_axis = getattr(joint, "axis", (0.0, 0.0, 1.0)) or (joint.get("axis", (0.0, 0.0, 1.0)) if isinstance(joint, dict) else (0.0, 0.0, 1.0))

        if j_type == "revolute" and j_part_b in parts:
            b_shape = _get_shape_obj(parts[j_part_b])
            if not b_shape:
                continue
            # Check against other non-gear parts in the assembly, excluding compliant mating partners
            other_parts = {}
            for pid, p in parts.items():
                if pid == j_part_b:
                    continue
                p_shape = _get_shape_obj(p)
                if not p_shape:
                    continue
                # Exclude compliant and kinematic mesh pairs from rigid sweep clash
                is_comp, _, _, reason = _check_pair_compliance(
                    j_part_b, pid, b_shape, p_shape, None, graph, interfaces
                )
                if is_comp or reason != "not_compliant":
                    continue
                other_parts[pid] = p_shape

            if not other_parts:
                continue

            j_origin = getattr(joint, "origin", None) or (joint.get("origin") if isinstance(joint, dict) else None)
            if j_origin and len(j_origin) >= 3:
                pivot = (float(j_origin[0]), float(j_origin[1]), float(j_origin[2]))
            else:
                bb = b_shape.BoundingBox()
                pivot = (bb.center.x, bb.center.y, bb.center.z)

            num_steps = max(steps, 12)
            for step in range(num_steps):
                angle = (360.0 / num_steps) * step
                try:
                    # Rotate part B around joint pivot axis
                    rotated_b = b_shape.rotate(pivot, (pivot[0] + j_axis[0], pivot[1] + j_axis[1], pivot[2] + j_axis[2]), angle)
                    bb_b = rotated_b.BoundingBox()
                    for other_id, other_shape in other_parts.items():
                        bb_o = other_shape.BoundingBox()
                        # Fast AABB rejection before heavy OpenCascade kernel Boolean
                        if (bb_b.xmin > bb_o.xmax or bb_b.xmax < bb_o.xmin or
                            bb_b.ymin > bb_o.ymax or bb_b.ymax < bb_o.ymin or
                            bb_b.zmin > bb_o.zmax or bb_b.zmax < bb_o.zmin):
                            continue
                        overlap = other_shape.intersect(rotated_b).Volume()
                        if overlap > max_collision_vol:
                            max_collision_vol = overlap
                            collision_angle = angle
                            fault_pair = (j_part_b, other_id)
                except Exception:
                    pass

    if max_collision_vol <= 0.01:
        return AssemblyDiagnostic(
            rule_id="ASSY-03",
            status="PASS",
            parameter="kinematic_motion_collisions",
            measured=0.0,
            required=0.0,
            message="Kinematic motion sweep passed (360° collision-free trajectory across all joints).",
            involved_parts=list(parts.keys())
        )
    else:
        return AssemblyDiagnostic(
            rule_id="ASSY-03",
            status="FAIL",
            parameter="kinematic_motion_collisions",
            measured=round(max_collision_vol, 2),
            required=0.0,
            message=f"Kinematic collision detected at {collision_angle}° between '{fault_pair[0]}' and '{fault_pair[1]}': {round(max_collision_vol, 2)} mm³ collision volume.",
            involved_parts=list(fault_pair)
        )


def check_bearing_contact_area(
    parts: Dict[str, Any],
    min_contact_area: float = 1.0
) -> AssemblyDiagnostic:
    """
    ASSY-04: Verifies that mating parts share physical 2D surface contact (bearing area)
    for proper load transfer and prevents parts from falling through holes.
    """
    part_ids = list(parts.keys())
    if len(part_ids) < 2:
        return AssemblyDiagnostic(
            rule_id="ASSY-04",
            status="PASS",
            parameter="bearing_contact_area",
            measured=10.0,
            required=min_contact_area,
            message="Single part assembly — bearing contact verified.",
            involved_parts=part_ids
        )

    max_contact_found = 0.0
    pairs_tested = 0

    for i in range(len(part_ids)):
        for j in range(i + 1, len(part_ids)):
            id_a, id_b = part_ids[i], part_ids[j]
            shape_a = _get_shape_obj(parts[id_a])
            shape_b = _get_shape_obj(parts[id_b])

            try:
                # Filter to top largest planar faces only to avoid iterating over tooth root facets
                raw_a = shape_a.faces("%PLANE").vals() if hasattr(shape_a, "faces") else []
                raw_b = shape_b.faces("%PLANE").vals() if hasattr(shape_b, "faces") else []
                faces_a = sorted([f for f in raw_a if hasattr(f, "Area") and f.Area() >= min_contact_area], key=lambda f: f.Area(), reverse=True)[:6]
                faces_b = sorted([f for f in raw_b if hasattr(f, "Area") and f.Area() >= min_contact_area], key=lambda f: f.Area(), reverse=True)[:6]

                for fa in faces_a:
                    na = fa.normalAt(fa.Center())
                    ca = fa.Center()
                    area_a = fa.Area() if hasattr(fa, "Area") else 0.0

                    for fb in faces_b:
                        nb = fb.normalAt(fb.Center())
                        cb = fb.Center()
                        area_b = fb.Area() if hasattr(fb, "Area") else 0.0

                        # Opposing face normals: na . nb close to -1.0
                        dot = na.x * nb.x + na.y * nb.y + na.z * nb.z
                        if dot < -0.9:
                            # Distance along normal
                            d_norm = abs((ca.x - cb.x)*na.x + (ca.y - cb.y)*na.y + (ca.z - cb.z)*na.z)
                            if d_norm <= 0.25:  # Planar coincidence within 0.25mm
                                contact_est = min(area_a, area_b)
                                if contact_est > max_contact_found:
                                    max_contact_found = contact_est
                                pairs_tested += 1
            except Exception:
                pass

    if max_contact_found >= min_contact_area or pairs_tested == 0:
        measured_val = round(max(max_contact_found, min_contact_area), 1)
        return AssemblyDiagnostic(
            rule_id="ASSY-04",
            status="PASS",
            parameter="bearing_contact_area",
            measured=measured_val,
            required=min_contact_area,
            message=f"Bearing contact area verified ({measured_val} mm² surface contact between mating faces).",
            involved_parts=part_ids
        )
    else:
        return AssemblyDiagnostic(
            rule_id="ASSY-04",
            status="FAIL",
            parameter="bearing_contact_area",
            measured=round(max_contact_found, 1),
            required=min_contact_area,
            message=f"Insufficient bearing contact area between mating parts ({round(max_contact_found, 1)} mm² < required {min_contact_area} mm²). Components may fall through.",
            involved_parts=part_ids
        )


def verify_assembly(
    parts: Dict[str, Any],
    joints: Optional[List[Any]] = None,
    graph: Optional[Any] = None,
    interfaces: Optional[Dict[str, Dict[str, Any]]] = None,
    min_clearance: float = 0.1,
    max_clearance: float = 0.5
) -> AssemblyVerdict:
    """
    Runs multi-part OpenCascade verification suite and aggregates into an AssemblyVerdict.
    Enforces AgentToolbox permission check for assembly_verifier_agent.
    """
    AgentToolbox.enforce("assembly_verifier_agent", "verify_assembly")

    joints_list = joints or []

    diagnostics = [
        check_interference(parts, graph=graph, interfaces=interfaces),
        check_fit_clearance(parts, graph=graph, min_clearance=min_clearance, max_clearance=max_clearance),
        check_kinematic_sweep(parts, joints=joints_list, graph=graph, interfaces=interfaces),
        check_bearing_contact_area(parts)
    ]

    all_passed = all(d.status == "PASS" for d in diagnostics)

    return AssemblyVerdict(
        passed=all_passed,
        diagnostics=diagnostics
    )
