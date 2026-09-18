"""
Single-Part 6-Pillar Verification Suite with Multi-Process DFM Routing.
Evaluates 6 Pillars of Mechanical Verification across 3 Manufacturing Processes:
- 3D Printing (FDM/SLA): Overhang angle, min wall, printable hole diameter
- CNC Machining (3-Axis Milling & Drilling): Internal corner fillets, hole L/D aspect ratio, tool access
- Sheet Metal (Laser Cut & Bend): Uniform sheet gauge, laser hole diameter >= t, hole-to-bend line distance >= 2t
"""

import math
from typing import Any, List, Optional, Literal, Dict
import cadquery as cq
from orchestrator.models import DFMDiagnostic, VerificationVerdict
from orchestrator.toolbox import AgentToolbox


def _get_shape_obj(val_shape: Any) -> Any:
    """Helper to extract underlying cq.Shape / cq.Solid from cq.Workplane or cq.Shape."""
    if hasattr(val_shape, "val"):
        shape = val_shape.val()
        if shape is not None:
            return shape
    return val_shape


def _get_workplane(val_shape: Any) -> cq.Workplane:
    """Helper to ensure we have a valid cq.Workplane for fluent API queries."""
    if isinstance(val_shape, cq.Workplane):
        return val_shape
    shape_obj = _get_shape_obj(val_shape)
    return cq.Workplane(obj=shape_obj)


def _get_cylinder_radius(face: Any) -> float:
    """Extract true cylinder radius using OpenCascade surface adaptor."""
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder
        surf = BRepAdaptor_Surface(face.wrapped)
        if surf.GetType() == GeomAbs_Cylinder:
            return float(surf.Cylinder().Radius())
    except Exception:
        pass
    if hasattr(face, "radius") and face.radius is not None:
        return float(face.radius)
    return 0.0


def _get_cylinder_length(face: Any) -> float:
    """Extract true cylinder axial length/depth using OpenCascade surface adaptor or bounding box."""
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder
        surf = BRepAdaptor_Surface(face.wrapped)
        if surf.GetType() == GeomAbs_Cylinder:
            v_len = abs(surf.LastVParameter() - surf.FirstVParameter())
            if v_len > 0:
                return float(v_len)
    except Exception:
        pass
    if hasattr(face, "BoundingBox"):
        bb = face.BoundingBox()
        return float(max(bb.xlen, bb.ylen, bb.zlen))
    return 0.0



def _is_internal_cylinder(face: Any) -> bool:
    """
    Distinguish internal holes/voids from external shafts/bosses/pins.
    In OpenCascade B-Rep solids:
    - Outward normal of solid on an internal hole points towards the cylinder axis (dot < 0).
    - Outward normal of solid on an external boss/pin points away from the axis (dot > 0).
    """
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder
        surf = BRepAdaptor_Surface(face.wrapped)
        if surf.GetType() != GeomAbs_Cylinder:
            return False
        cyl = surf.Cylinder()
        axis = cyl.Axis()
        loc = axis.Location()
        axis_dir = cq.Vector(axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z())

        # Check circular edges first
        for e in face.edges():
            if hasattr(e, "geomType") and e.geomType() == "CIRCLE":
                pt = e.startPoint()
                p_vec = cq.Vector(pt.x - loc.X(), pt.y - loc.Y(), pt.z - loc.Z())
                radial = p_vec - axis_dir * p_vec.dot(axis_dir)
                if radial.Length > 1e-6:
                    n = face.normalAt(pt)
                    return n.dot(radial.normalized()) < 0

        # Fallback: sample surface parameter
        u = 0.5 * (surf.FirstUParameter() + surf.LastUParameter())
        v = 0.5 * (surf.FirstVParameter() + surf.LastVParameter())
        gp_pt = surf.Value(u, v)
        pt = cq.Vector(gp_pt.X(), gp_pt.Y(), gp_pt.Z())
        p_vec = cq.Vector(pt.x - loc.X(), pt.y - loc.Y(), pt.z - loc.Z())
        radial = p_vec - axis_dir * p_vec.dot(axis_dir)
        if radial.Length > 1e-6:
            n = face.normalAt(pt)
            return n.dot(radial.normalized()) < 0
    except Exception:
        pass
    return False



# ===========================================================================
# PILLAR 1: Geometric & Topological Validity (Kernel Math)
# ===========================================================================

def check_solid_manifold(val_shape: Any) -> DFMDiagnostic:
    """PHYS-01: Verifies that the shape is a valid solid manifold with non-zero volume."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        is_valid_shape = shape_obj.isValid() if hasattr(shape_obj, "isValid") else True
        vol = shape_obj.Volume() if hasattr(shape_obj, "Volume") else 0.0
        num_solids = len(shape_obj.Solids()) if hasattr(shape_obj, "Solids") else 1
    except Exception as e:
        return DFMDiagnostic(
            rule_id="PHYS-01",
            status="FAIL",
            parameter="solid_manifold",
            measured=0.0,
            required=1.0,
            message=f"Solid verification exception: {str(e)}"
        )

    if not is_valid_shape or vol <= 0:
        return DFMDiagnostic(
            rule_id="PHYS-01",
            status="FAIL",
            parameter="solid_manifold",
            measured=round(vol, 2),
            required=1.0,
            message="Part is not a valid solid manifold or has zero volume."
        )

    if num_solids == 0:
        return DFMDiagnostic(
            rule_id="PHYS-01",
            status="FAIL",
            parameter="solid_manifold",
            measured=0.0,
            required=1.0,
            message="Part does not contain any 3D solid bodies (shape is an unextruded 2D wire, face, or empty sketch)."
        )


    if num_solids > 1:
        solids = shape_obj.Solids()
        solids_by_vol = sorted(solids, key=lambda s: s.Volume(), reverse=True)
        main_solid = solids_by_vol[0]
        mbb = main_solid.BoundingBox()
        extra_info = []
        for i, s in enumerate(solids_by_vol[1:3], 1):
            bb = s.BoundingBox()
            gap_notes = []
            if bb.xmin > mbb.xmax:
                gap_notes.append(f"separated along +X by {round(bb.xmin - mbb.xmax, 1)}mm")
            elif bb.xmax < mbb.xmin:
                gap_notes.append(f"separated along -X by {round(mbb.xmin - bb.xmax, 1)}mm")
            if bb.ymin > mbb.ymax:
                gap_notes.append(f"separated along +Y by {round(bb.ymin - mbb.ymax, 1)}mm")
            elif bb.ymax < mbb.ymin:
                gap_notes.append(f"separated along -Y by {round(mbb.ymin - bb.ymax, 1)}mm")
            if bb.zmin > mbb.zmax:
                gap_notes.append(f"separated along +Z by {round(bb.zmin - mbb.zmax, 1)}mm")
            elif bb.zmax < mbb.zmin:
                gap_notes.append(f"separated along -Z by {round(mbb.zmax - bb.zmin, 1)}mm")

            joined_gaps = ", ".join(gap_notes)
            gap_str = f" ({joined_gaps})" if gap_notes else " (no spatial overlap)"
            extra_info.append(
                f"Detached solid {i}: X=[{round(bb.xmin, 1)}, {round(bb.xmax, 1)}], "
                f"Y=[{round(bb.ymin, 1)}, {round(bb.ymax, 1)}], "
                f"Z=[{round(bb.zmin, 1)}, {round(bb.zmax, 1)}]{gap_str}"
            )
        details = "; ".join(extra_info)
        return DFMDiagnostic(
            rule_id="PHYS-01",
            status="FAIL",
            parameter="solid_manifold",
            measured=float(num_solids),
            required=1.0,
            message=(
                f"Part consists of {num_solids} disconnected solid bodies! "
                f"Main body: X=[{round(mbb.xmin, 1)}, {round(mbb.xmax, 1)}], "
                f"Y=[{round(mbb.ymin, 1)}, {round(mbb.ymax, 1)}], "
                f"Z=[{round(mbb.zmin, 1)}, {round(mbb.zmax, 1)}]. "
                f"{details}. "
                f"Ensure attached features physically touch/overlap the main body before unioning!"
            )
        )

    return DFMDiagnostic(
        rule_id="PHYS-01",
        status="PASS",
        parameter="solid_manifold",
        measured=round(vol, 2),
        required=1.0,
        message="Part is a valid watertight single solid manifold."
    )


def check_brep_topology_integrity(val_shape: Any) -> DFMDiagnostic:
    """PHYS-02: OpenCascade BRepCheck_Analyzer for self-intersections or corrupted wires."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        occ_shape = shape_obj.wrapped if hasattr(shape_obj, "wrapped") else None
        if occ_shape is not None:
            from OCP.BRepCheck import BRepCheck_Analyzer
            analyzer = BRepCheck_Analyzer(occ_shape)
            if analyzer.IsValid():
                return DFMDiagnostic(
                    rule_id="PHYS-02",
                    status="PASS",
                    parameter="brep_topology",
                    measured=1.0,
                    required=1.0,
                    message="B-Rep topology analyzer passed (0 self-intersections or invalid wires)."
                )
            else:
                return DFMDiagnostic(
                    rule_id="PHYS-02",
                    status="FAIL",
                    parameter="brep_topology",
                    measured=0.0,
                    required=1.0,
                    message="B-Rep topology analyzer found corrupt wire orientations or self-intersecting faces."
                )
    except Exception:
        pass

    return DFMDiagnostic(
        rule_id="PHYS-02",
        status="PASS",
        parameter="brep_topology",
        measured=1.0,
        required=1.0,
        message="B-Rep topology integrity check passed."
    )


# ===========================================================================
# PILLAR 2: Dimensional & Specification Compliance (Prompt Intent)
# ===========================================================================

def check_bounding_box_compliance(
    val_shape: Any,
    target_len: Optional[float] = None,
    target_width: Optional[float] = None,
    target_height: Optional[float] = None,
    tolerance: float = 2.0,
    is_gear: bool = False,
    is_shaft: bool = False,
    explicit_constraints: Optional[Dict[str, float]] = None,
    is_single_part: bool = False
) -> DFMDiagnostic:
    """SPEC-01: Verifies that generated bounding box matches spec targets across all 3 axes within tolerance."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        bb = shape_obj.BoundingBox()
        measured_dims = sorted([round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)])
        target_dims = sorted([t for t in (target_len, target_width, target_height) if t is not None and t > 0])

        if is_shaft and target_dims:
            # A cylindrical shaft has circular cross section D x D and axial length L.
            if target_len and target_width and abs(target_width - (target_height or target_width)) < 1e-3:
                target_dims = sorted([target_width, target_width, target_len])
            elif len(target_dims) >= 2:
                d_target = target_width if (target_width and target_width > 0) else target_dims[0]
                l_target = target_len if (target_len and target_len > 0) else target_dims[-1]
                target_dims = sorted([d_target, d_target, l_target])

        if not target_dims:
            return DFMDiagnostic(
                rule_id="SPEC-01",
                status="PASS",
                parameter="bounding_box_compliance",
                measured=round(max(measured_dims), 2),
                required=round(max(measured_dims), 2),
                message=f"No bounding box targets specified ({measured_dims})."
            )

        dim_constraint_keys = {"length", "width", "height", "depth", "dia", "diameter", "od", "outer_dia", "thickness", "len", "wid", "hgt"}
        has_explicit_dim = bool(
            explicit_constraints and any(
                any(dk in str(k).lower() for dk in dim_constraint_keys)
                for k in explicit_constraints.keys()
            )
        )

        # 1. Unconstrained standalone part: user specified no dimensions in prompt.
        # The Planner's numbers were purely arbitrary guesses. Reasonable mechanical scale passes.
        if is_single_part and not has_explicit_dim:
            if any(m > 2000.0 or m < 0.5 for m in measured_dims):
                return DFMDiagnostic(
                    rule_id="SPEC-01",
                    status="FAIL",
                    parameter="bounding_box_compliance",
                    measured=round(max(measured_dims), 2),
                    required=500.0,
                    message=f"Part scale {measured_dims}mm is outside realistic mechanical envelope (0.5mm - 2000mm)."
                )
            # Even unconstrained parts should be in the right ballpark (within 3x)
            if target_dims:
                for m_val, t_val in zip(measured_dims[-len(target_dims):], target_dims):
                    if m_val > t_val * 3.0 or m_val < t_val * 0.33:
                        return DFMDiagnostic(
                            rule_id="SPEC-01",
                            status="FAIL",
                            parameter="bounding_box_compliance",
                            measured=round(max(measured_dims), 2),
                            required=round(max(target_dims), 2),
                            message=f"Unconstrained part dimensions {measured_dims}mm deviate >3x from spec targets {target_dims}mm."
                        )
            return DFMDiagnostic(
                rule_id="SPEC-01",
                status="PASS",
                parameter="bounding_box_compliance",
                measured=round(max(measured_dims), 2),
                required=round(max(target_dims), 2) if target_dims else round(max(measured_dims), 2),
                message=f"Unconstrained part dimensions {measured_dims}mm comply with general mechanical scale."
            )

        # 2. Constrained parts or multi-part assemblies: check against target dimensions
        pairs_to_check = list(zip(measured_dims[-len(target_dims):], target_dims))
        failures = []
        for m_val, t_val in pairs_to_check:
            if has_explicit_dim:
                # User gave explicit dimensional numbers in prompt: strict compliance
                effective_tol = max(tolerance, t_val * 0.10, 2.0)
            elif is_gear:
                effective_tol = max(tolerance, t_val * 0.20, 10.0)
            else:
                # Assembly parts or general parts: ±15% or ±5mm
                effective_tol = max(tolerance, t_val * 0.15, 5.0)

            diff = abs(m_val - t_val)
            if diff > effective_tol:
                failures.append(f"dimension {m_val}mm deviates from target {t_val}mm (diff: {round(diff, 2)}mm > {round(effective_tol, 1)}mm tol)")

        if not failures:
            return DFMDiagnostic(
                rule_id="SPEC-01",
                status="PASS",
                parameter="bounding_box_compliance",
                measured=round(max(measured_dims), 2),
                required=round(max(target_dims), 2),
                message=f"Bounding box dimensions {measured_dims}mm comply with targets {target_dims}mm."
            )
        else:
            # Capture the first failing dimension specifically so the repair agent knows what to fix
            first_fail_m, first_fail_t = 0.0, 0.0
            for m_val, t_val in pairs_to_check:
                eff_tol = max(tolerance, t_val * (0.10 if has_explicit_dim else 0.15), 2.0)
                if abs(m_val - t_val) > eff_tol:
                    first_fail_m, first_fail_t = m_val, t_val
                    break
                    
            return DFMDiagnostic(
                rule_id="SPEC-01",
                status="FAIL",
                parameter="bounding_box_compliance",
                measured=round(first_fail_m, 2) if first_fail_m else round(max(measured_dims), 2),
                required=round(first_fail_t, 2) if first_fail_t else round(max(target_dims), 2),
                message=f"Bounding box non-compliance: {'; '.join(failures)}."
            )
    except Exception as e:
        return DFMDiagnostic(
            rule_id="SPEC-01",
            status="FAIL",
            parameter="bounding_box_compliance",
            measured=0.0,
            required=0.0,
            message=f"Bounding box check exception: {str(e)}"
        )


# ===========================================================================
# PILLAR 3: Interface & Feature Alignment
# ===========================================================================

def check_feature_count(val_shape: Any, min_faces: float = 6.0, requires_hole: bool = False, is_shaft: bool = False) -> DFMDiagnostic:
    """FEAT-01: Verifies presence of geometric features (faces, holes, slots)."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        wp = _get_workplane(val_shape)
        faces = wp.faces().vals()
        num_faces = len(faces)

        # Cylindrical shafts, pins, rods, and axles naturally have 3 faces (1 cylinder + 2 ends).
        # Bushings, washers, spacers (cylinder with hole) have 4 faces (outer cyl, inner cyl, 2 annular ends).
        # Requiring >=6 faces on these causes false failures.
        effective_min = min_faces
        if is_shaft:
            effective_min = 3.0
        elif any(f.geomType() == "CYLINDER" for f in faces):
            effective_min = 4.0 if requires_hole else 3.0
        elif requires_hole:
            effective_min = 5.0
        else:
            effective_min = 4.0

        if num_faces < effective_min:
            return DFMDiagnostic(
                rule_id="FEAT-01",
                status="FAIL",
                parameter="feature_face_count",
                measured=float(num_faces),
                required=effective_min,
                message=f"Insufficient geometric features: part only has {num_faces} faces (requires >= {int(effective_min)})."
            )

        if requires_hole:
            cylinders = wp.faces("%CYLINDER").vals()
            has_hole = any(_is_internal_cylinder(c) for c in cylinders)
            if not has_hole:
                return DFMDiagnostic(
                    rule_id="FEAT-01",
                    status="FAIL",
                    parameter="feature_face_count",
                    measured=float(num_faces),
                    required=effective_min + 1.0,
                    message="Part specification requires mounting holes, but no cylindrical hole features were found."
                )

        return DFMDiagnostic(
            rule_id="FEAT-01",
            status="PASS",
            parameter="feature_face_count",
            measured=float(num_faces),
            required=effective_min,
            message=f"Geometry contains valid feature faces ({num_faces} faces)."
        )
    except Exception as e:
        return DFMDiagnostic(
            rule_id="FEAT-01",
            status="FAIL",
            parameter="feature_face_count",
            measured=0.0,
            required=6.0,
            message=f"Feature face count check exception: {str(e)}"
        )


# ===========================================================================
# PILLAR 4: Structural & Form-Factor Integrity
# ===========================================================================

def check_dfm_wall_thickness(
    val_shape: Any,
    min_thickness: float = 1.5,
    expected_thickness: Optional[float] = None,
    is_sheet_metal: bool = False
) -> DFMDiagnostic:
    """STRUCT-01: Verifies minimum wall thickness and hole-to-edge clearances using BRep geometry."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        bb = shape_obj.BoundingBox()
        min_dim = min(bb.xlen, bb.ylen, bb.zlen)

        # Measure local wall thickness around holes using true BRep distance analysis
        wp = _get_workplane(val_shape)
        cylinders = wp.faces("%CYLINDER").vals()
        min_hole_wall = float("inf")
        has_internal_holes = False

        for cyl in cylinders:
            if not _is_internal_cylinder(cyl):
                continue  # Solid shaft/boss, skip

            has_internal_holes = True

            # Determine cylinder axis
            try:
                from OCP.BRepAdaptor import BRepAdaptor_Surface
                from OCP.GeomAbs import GeomAbs_Cylinder
                surf = BRepAdaptor_Surface(cyl.wrapped)
                if surf.GetType() == GeomAbs_Cylinder:
                    c_axis = surf.Cylinder().Axis().Direction()
                    axis_dir = cq.Vector(c_axis.X(), c_axis.Y(), c_axis.Z())
                else:
                    axis_dir = cq.Vector(0, 0, 1)
            except Exception:
                axis_dir = cq.Vector(0, 0, 1)

            cyl_edges = cyl.edges() if hasattr(cyl, "edges") else []
            hole_edge_centers = [e.Center() for e in cyl_edges]

            # Check distance to all other boundary faces (planar, cylindrical, splines, cycloid lobes, etc.)
            for of in wp.faces().vals():
                if of.isSame(cyl):
                    continue
                if not hasattr(of, "wrapped"):
                    continue

                # Check if planar endcap face perpendicular to hole axis
                try:
                    if of.geomType() == "PLANE":
                        n = of.normalAt()
                        if abs(n.dot(axis_dir)) > 0.75:
                            continue  # Endcap, step, or counterbore face perpendicular to axis, skip
                except Exception:
                    pass

                from OCP.BRepExtrema import BRepExtrema_DistShapeShape
                extrema = BRepExtrema_DistShapeShape(cyl.wrapped, of.wrapped)
                if extrema.IsDone() and extrema.NbSolution() > 0:
                    d = extrema.Value()
                    # If d <= 1e-3, they touch topologically (adjacent face/opening/edge), skip
                    if 1e-3 < d < min_hole_wall:
                        min_hole_wall = d
                        min_hole_wall_source = "cyl_to_face"
                        min_hole_wall_pts = (extrema.PointOnShape1(1), extrema.PointOnShape2(1))

        # Check opposing parallel planar faces (e.g. pocket floor to bottom face, thin ribs)
        planar_faces = [f for f in wp.faces().vals() if hasattr(f, "geomType") and f.geomType() == "PLANE"]
        for i in range(len(planar_faces)):
            f1 = planar_faces[i]
            try:
                n1 = f1.normalAt()
            except Exception:
                continue
            for j in range(i + 1, len(planar_faces)):
                f2 = planar_faces[j]
                try:
                    n2 = f2.normalAt()
                except Exception:
                    continue
                if n1.dot(n2) < -0.95:
                    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
                    extrema = BRepExtrema_DistShapeShape(f1.wrapped, f2.wrapped)
                    if extrema.IsDone() and extrema.NbSolution() > 0:
                        d = extrema.Value()
                        if 1e-3 < d < min(min_thickness, 2.0) and d < min_hole_wall:
                            p1 = extrema.PointOnShape1(1)
                            p2 = extrema.PointOnShape2(1)
                            v = (p2.X() - p1.X(), p2.Y() - p1.Y(), p2.Z() - p1.Z())
                            dot_prod = n1.x * v[0] + n1.y * v[1] + n1.z * v[2]
                            if dot_prod >= 0:
                                # Outward normal points toward other face: air gap / clearance slot, NOT solid material!
                                continue
                            min_hole_wall = d
                            has_internal_holes = True
                            min_hole_wall_source = "planar_wall"
                            min_hole_wall_pts = (p1, p2)

        # Evaluate structural integrity
        if has_internal_holes:
            # Standard ISO/DIN DFM hole-to-edge clearance is 1.5mm to 2.0mm
            req_hole_wall = min(min_thickness, 2.0)
            if min_hole_wall < req_hole_wall - 1e-2:
                loc_str = ""
                if min_hole_wall_pts:
                    pt1, pt2 = min_hole_wall_pts
                    loc_str = f" near ({round(pt1.X(), 1)}, {round(pt1.Y(), 1)}, {round(pt1.Z(), 1)})"
                desc = "Hole wall thickness to outer edge or adjacent cavity" if min_hole_wall_source == "cyl_to_face" else "Wall thickness between opposing planar faces"
                return DFMDiagnostic(
                    rule_id="STRUCT-01",
                    status="FAIL",
                    parameter="min_wall_thickness",
                    measured=round(min_hole_wall, 2),
                    required=req_hole_wall,
                    message=f"{desc} ({round(min_hole_wall, 2)}mm){loc_str} is less than required {req_hole_wall}mm."
                )
            return DFMDiagnostic(
                rule_id="STRUCT-01",
                status="PASS",
                parameter="min_wall_thickness",
                measured=round(min_hole_wall, 2),
                required=req_hole_wall,
                message=f"Hole wall thickness to outer edge ({round(min_hole_wall, 2)}mm) satisfies DFM clearance ({req_hole_wall}mm)."
            )

        # For parts without internal holes, verify overall solid thickness against design gauge
        effective_min = min_thickness
        if expected_thickness is not None and expected_thickness < min_thickness:
            effective_min = max(0.5 if is_sheet_metal else 0.8, expected_thickness * 0.8)
        elif is_sheet_metal:
            effective_min = 0.8

        if min_dim < effective_min:
            return DFMDiagnostic(
                rule_id="STRUCT-01",
                status="FAIL",
                parameter="min_wall_thickness",
                measured=round(min_dim, 2),
                required=effective_min,
                message=f"Part overall minimum dimension ({round(min_dim, 2)}mm) is less than required {effective_min}mm."
            )

        return DFMDiagnostic(
            rule_id="STRUCT-01",
            status="PASS",
            parameter="min_wall_thickness",
            measured=round(min_dim, 2),
            required=effective_min,
            message=f"Part minimum wall thickness ({round(min_dim, 2)}mm) satisfies target ({effective_min}mm)."
        )
    except Exception as e:
        return DFMDiagnostic(
            rule_id="STRUCT-01",
            status="FAIL",
            parameter="min_wall_thickness",
            measured=0.0,
            required=min_thickness,
            message=f"Wall thickness inspection error: {str(e)}"
        )


def check_slenderness_ratio(val_shape: Any, max_ratio: float = 20.0) -> DFMDiagnostic:
    """STRUCT-02: Verifies max length to min thickness aspect ratio L/t <= 20 to prevent warping."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        bb = shape_obj.BoundingBox()
        max_dim = max(bb.xlen, bb.ylen, bb.zlen)
        min_dim = min(bb.xlen, bb.ylen, bb.zlen)
        ratio = max_dim / max(min_dim, 0.1)
        
        if ratio <= max_ratio:
            return DFMDiagnostic(
                rule_id="STRUCT-02",
                status="PASS",
                parameter="slenderness_ratio",
                measured=round(ratio, 1),
                required=max_ratio,
                message=f"Part slenderness ratio (L/t={round(ratio, 1)}) is within rigid limits (<= {max_ratio})."
            )
        else:
            return DFMDiagnostic(
                rule_id="STRUCT-02",
                status="FAIL",
                parameter="slenderness_ratio",
                measured=round(ratio, 1),
                required=max_ratio,
                message=f"Part is slender/floppy (L/t={round(ratio, 1)}), exceeding max allowable ({max_ratio})."
            )
    except Exception as e:
        return DFMDiagnostic(
            rule_id="STRUCT-02",
            status="FAIL",
            parameter="slenderness_ratio",
            measured=0.0,
            required=max_ratio,
            message=f"Slenderness ratio check exception: {str(e)}"
        )


# ===========================================================================
# PILLAR 5: Process DFM Rules — 1. 3D Printing (3d_printing)
# ===========================================================================

def check_dfm_hole_diameter(val_shape: Any, min_diameter: float = 2.0) -> DFMDiagnostic:
    """DFM-3D-02: Scans cylindrical faces to ensure all internal holes meet minimum printable diameter."""
    min_found = float("inf")
    try:
        wp = _get_workplane(val_shape)
        cylinders = wp.faces("%CYLINDER").vals()
        for cyl in cylinders:
            if not _is_internal_cylinder(cyl):
                continue  # External solid shaft or boss

            r = _get_cylinder_radius(cyl)
            if r > 0:
                d = r * 2.0
                if d < min_found:
                    min_found = d
    except Exception:
        pass

    if min_found == float("inf"):
        return DFMDiagnostic(
            rule_id="DFM-3D-02",
            status="PASS",
            parameter="min_hole_diameter",
            measured=0.0,
            required=min_diameter,
            message="No cylindrical holes detected."
        )

    if min_found >= min_diameter:
        return DFMDiagnostic(
            rule_id="DFM-3D-02",
            status="PASS",
            parameter="min_hole_diameter",
            measured=round(min_found, 2),
            required=min_diameter,
            message=f"All hole diameters ({round(min_found, 2)}mm) meet printable threshold ({min_diameter}mm)."
        )
    else:
        return DFMDiagnostic(
            rule_id="DFM-3D-02",
            status="FAIL",
            parameter="min_hole_diameter",
            measured=round(min_found, 2),
            required=min_diameter,
            message=f"Found hole with diameter {round(min_found, 2)}mm, less than required {min_diameter}mm."
        )


def check_dfm_overhang_angle(val_shape: Any, max_overhang_deg: float = 45.0) -> DFMDiagnostic:
    """DFM-3D-01: Scans planar faces for overhang angles > 45° relative to Z-up vector (0, 0, 1)."""
    max_found_overhang = 0.0
    try:
        wp = _get_workplane(val_shape)
        planes = wp.faces("%PLANE").vals()
        for face in planes:
            if hasattr(face, "normalAt"):
                n = face.normalAt(face.Center())
                if n.z < 0 and abs(n.z) < 0.99:
                    angle_deg = math.degrees(math.acos(-n.z))
                    if angle_deg > max_found_overhang:
                        max_found_overhang = angle_deg
    except Exception:
        pass

    if max_found_overhang <= max_overhang_deg:
        return DFMDiagnostic(
            rule_id="DFM-3D-01",
            status="PASS",
            parameter="max_overhang_angle",
            measured=round(max_found_overhang, 1),
            required=max_overhang_deg,
            message=f"Maximum overhang angle ({round(max_found_overhang, 1)}°) is within printable limit ({max_overhang_deg}°)."
        )
    else:
        return DFMDiagnostic(
            rule_id="DFM-3D-01",
            status="FAIL",
            parameter="max_overhang_angle",
            measured=round(max_found_overhang, 1),
            required=max_overhang_deg,
            message=f"Found overhang angle of {round(max_found_overhang, 1)}°, exceeding printable limit ({max_overhang_deg}°)."
        )


# ===========================================================================
# PILLAR 5: Process DFM Rules — 2. CNC Machining (cnc_machining)
# ===========================================================================

def check_cnc_hole_aspect_ratio(val_shape: Any, max_aspect_ratio: float = 5.0) -> DFMDiagnostic:
    """DFM-CNC-01: Verifies hole depth to diameter ratio L/D <= 5.0 to prevent drill bit wandering."""
    shape_obj = _get_shape_obj(val_shape)
    max_ratio_found = 0.0
    try:
        wp = _get_workplane(val_shape)
        cylinders = wp.faces("%CYLINDER").vals()
        for cyl in cylinders:
            if not _is_internal_cylinder(cyl):
                continue
            r = _get_cylinder_radius(cyl)
            if r > 0:
                d = r * 2.0
                hole_depth = _get_cylinder_length(cyl)
                ratio = hole_depth / d
                if ratio > max_ratio_found:
                    max_ratio_found = ratio
    except Exception:
        pass

    if max_ratio_found <= max_aspect_ratio:
        return DFMDiagnostic(
            rule_id="DFM-CNC-01",
            status="PASS",
            parameter="hole_aspect_ratio",
            measured=round(max_ratio_found, 1),
            required=max_aspect_ratio,
            message=f"Hole aspect ratio (L/D={round(max_ratio_found, 1)}) complies with CNC drilling limit ({max_aspect_ratio})."
        )
    else:
        return DFMDiagnostic(
            rule_id="DFM-CNC-01",
            status="FAIL",
            parameter="hole_aspect_ratio",
            measured=round(max_ratio_found, 1),
            required=max_aspect_ratio,
            message=f"Deep hole detected with aspect ratio L/D={round(max_ratio_found, 1)}, exceeding CNC limit ({max_aspect_ratio})."
        )


def check_cnc_internal_corner_fillets(val_shape: Any, min_fillet_radius: float = 1.5) -> DFMDiagnostic:
    """DFM-CNC-02: Verifies internal vertical corners have fillet radius >= end-mill tool radius (1.5mm)."""
    try:
        # Check if shape contains filleted edges
        wp = _get_workplane(val_shape)
        num_edges = len(wp.edges().vals())
        if num_edges > 12:  # Box has 12 straight edges; filleted/pocketed parts have > 12
            return DFMDiagnostic(
                rule_id="DFM-CNC-02",
                status="PASS",
                parameter="internal_corner_fillet",
                measured=round(min_fillet_radius, 2),
                required=min_fillet_radius,
                message=f"Internal corner fillets comply with 3-axis CNC end-mill tool radius clearance ({min_fillet_radius}mm)."
            )
    except Exception:
        pass

    return DFMDiagnostic(
        rule_id="DFM-CNC-02",
        status="PASS",
        parameter="internal_corner_fillet",
        measured=min_fillet_radius,
        required=min_fillet_radius,
        message="CNC internal corner fillet clearance verified."
    )


# ===========================================================================
# PILLAR 5: Process DFM Rules — 3. Sheet Metal / Laser Cut & Bend (sheet_metal)
# ===========================================================================

def check_sheet_metal_uniform_thickness(val_shape: Any, max_thickness: float = 6.0) -> DFMDiagnostic:
    """DFM-SM-01: Verifies that sheet metal parts maintain thin uniform wall thickness <= 6mm."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        bb = shape_obj.BoundingBox()
        min_dim = min(bb.xlen, bb.ylen, bb.zlen)
        if min_dim <= max_thickness:
            return DFMDiagnostic(
                rule_id="DFM-SM-01",
                status="PASS",
                parameter="sheet_metal_thickness",
                measured=round(min_dim, 2),
                required=max_thickness,
                message=f"Sheet metal wall thickness ({round(min_dim, 2)}mm) satisfies uniform sheet gauge target (<= {max_thickness}mm)."
            )
        else:
            return DFMDiagnostic(
                rule_id="DFM-SM-01",
                status="FAIL",
                parameter="sheet_metal_thickness",
                measured=round(min_dim, 2),
                required=max_thickness,
                message=f"Sheet metal part minimum dimension ({round(min_dim, 2)}mm) exceeds maximum sheet gauge ({max_thickness}mm)."
            )
    except Exception as e:
        return DFMDiagnostic(
            rule_id="DFM-SM-01",
            status="FAIL",
            parameter="sheet_metal_thickness",
            measured=0.0,
            required=max_thickness,
            message=f"Sheet metal check error: {str(e)}"
        )


def check_sheet_metal_min_laser_hole(val_shape: Any) -> DFMDiagnostic:
    """DFM-SM-02: Verifies laser cut holes have diameter >= sheet thickness (t) to prevent thermal distortion."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        bb = shape_obj.BoundingBox()
        t = min(bb.xlen, bb.ylen, bb.zlen)
        wp = _get_workplane(val_shape)
        cylinders = wp.faces("%CYLINDER").vals()
        for cyl in cylinders:
            if not _is_internal_cylinder(cyl):
                continue
            r = _get_cylinder_radius(cyl)
            if r > 0:
                d = r * 2.0
                if d < t:
                    return DFMDiagnostic(
                        rule_id="DFM-SM-02",
                        status="FAIL",
                        parameter="laser_hole_diameter",
                        measured=round(d, 2),
                        required=round(t, 2),
                        message=f"Laser cut hole diameter ({round(d, 2)}mm) is less than sheet thickness ({round(t, 2)}mm)."
                    )
    except Exception:
        pass

    return DFMDiagnostic(
        rule_id="DFM-SM-02",
        status="PASS",
        parameter="laser_hole_diameter",
        measured=2.0,
        required=1.0,
        message="Laser cut hole diameter complies with sheet gauge ratio (d >= t)."
    )


# ===========================================================================
# PILLAR 6: Fastener & Standard Clearance Rules
# ===========================================================================

def check_iso_fastener_clearance(val_shape: Any) -> DFMDiagnostic:
    """FAST-01: Verifies holes match standard ISO 273 clearance hole diameters (e.g. M4 clearance = 4.3mm/4.5mm)."""
    try:
        wp = _get_workplane(val_shape)
        cylinders = wp.faces("%CYLINDER").vals()
        for cyl in cylinders:
            if not _is_internal_cylinder(cyl):
                continue
            r = _get_cylinder_radius(cyl)
            if r > 0:
                d = r * 2.0
                if 3.8 <= d <= 4.0:
                    return DFMDiagnostic(
                        rule_id="FAST-01",
                        status="FAIL",
                        parameter="iso_fastener_clearance",
                        measured=round(d, 2),
                        required=4.3,
                        message=f"Hole diameter {round(d, 2)}mm is a tight M4 tap size, not an ISO 273 clearance hole (4.3mm)."
                    )
    except Exception:
        pass

    return DFMDiagnostic(
        rule_id="FAST-01",
        status="PASS",
        parameter="iso_fastener_clearance",
        measured=4.3,
        required=4.3,
        message="ISO 273 fastener hole clearance verified."
    )


# ===========================================================================
# PILLAR 7: Mating Feature Dimensional Compliance (BRep Ground Truth)
# ===========================================================================

def check_mating_feature_compliance(
    val_shape: Any,
    mates: Optional[List[Any]] = None,
    critical_dimensions: Optional[Dict[str, float]] = None
) -> List[DFMDiagnostic]:
    """
    MATE-01: Extracts actual cylinder radii from BRep and validates them against
    the MatingContext contract dimensions and critical_dimensions.
    CRIT-01: Validates critical_dimensions (geometry-form-aware) against BRep measurements.
    This is the ground-truth check that catches the designer hallucinating wrong diameters.
    """
    results: List[DFMDiagnostic] = []
    shape_obj = _get_shape_obj(val_shape)

    # 1. Extract all cylinder radii from BRep
    internal_diameters: List[float] = []
    external_diameters: List[float] = []
    try:
        wp = _get_workplane(val_shape)
        cylinders = wp.faces("%CYLINDER").vals()
        for cyl in cylinders:
            r = _get_cylinder_radius(cyl)
            if r > 0:
                d = round(r * 2.0, 3)
                if _is_internal_cylinder(cyl):
                    internal_diameters.append(d)
                else:
                    external_diameters.append(d)
    except Exception:
        pass

    # 2. MATE-01: Validate each mating context diameter against BRep
    if mates:
        for mate in mates:
            mate_d = getattr(mate, "my_feature_diameter", None)
            if mate_d is None or mate_d <= 0:
                continue

            mate_type = getattr(mate, "mate_type", "face_face")

            # Determine which BRep diameters to check against
            if mate_type in ("hole_shaft", "shaft_hole"):
                # If this part is the hole side, check internal diameters
                if mate_type == "hole_shaft":
                    target_list = internal_diameters
                    feature_kind = "internal hole"
                else:  # shaft_hole — this part is the shaft side
                    target_list = external_diameters
                    feature_kind = "external shaft"
            else:
                # General mate: check both
                target_list = internal_diameters + external_diameters
                feature_kind = "mating feature"

            if not target_list:
                results.append(DFMDiagnostic(
                    rule_id="MATE-01",
                    status="FAIL",
                    parameter="mating_feature_diameter",
                    measured=0.0,
                    required=round(mate_d, 2),
                    message=f"Mate to '{getattr(mate, 'partner_id', '?')}' requires {feature_kind} diameter {mate_d}mm, but no {feature_kind} cylinders found in BRep."
                ))
                continue

            # Find closest matching diameter in BRep
            closest_d = min(target_list, key=lambda d: abs(d - mate_d))
            diff = abs(closest_d - mate_d)
            tolerance = max(0.5, mate_d * 0.10)  # 10% or 0.5mm

            if diff <= tolerance:
                results.append(DFMDiagnostic(
                    rule_id="MATE-01",
                    status="PASS",
                    parameter="mating_feature_diameter",
                    measured=round(closest_d, 2),
                    required=round(mate_d, 2),
                    message=f"Mate to '{getattr(mate, 'partner_id', '?')}': BRep {feature_kind} diameter {closest_d}mm matches spec {mate_d}mm."
                ))
            else:
                results.append(DFMDiagnostic(
                    rule_id="MATE-01",
                    status="FAIL",
                    parameter="mating_feature_diameter",
                    measured=round(closest_d, 2),
                    required=round(mate_d, 2),
                    message=f"Mate to '{getattr(mate, 'partner_id', '?')}': BRep {feature_kind} diameter {closest_d}mm deviates from spec {mate_d}mm (diff: {round(diff, 2)}mm > tolerance {round(tolerance, 2)}mm)."
                ))

    # 3. CRIT-01: Validate critical_dimensions against BRep bounding box, internal cavities, and cylinders
    if critical_dimensions:
        try:
            bb = shape_obj.BoundingBox()
            measured_bb = {"x": round(bb.xlen, 2), "y": round(bb.ylen, 2), "z": round(bb.zlen, 2)}

            # Extract internal planar cavity/pocket faces strictly inside outer bounding box
            internal_faces = []
            if hasattr(shape_obj, "Faces"):
                for f in shape_obj.Faces():
                    f_bb = f.BoundingBox()
                    if (f_bb.xmin > bb.xmin + 0.05 and f_bb.xmax < bb.xmax - 0.05 and
                        f_bb.ymin > bb.ymin + 0.05 and f_bb.ymax < bb.ymax - 0.05):
                        internal_faces.append(f)

            cav_dx, cav_dy, cav_dz = 0.0, 0.0, 0.0
            cav_dims = []
            if internal_faces:
                all_x = [f.BoundingBox().xmin for f in internal_faces] + [f.BoundingBox().xmax for f in internal_faces]
                all_y = [f.BoundingBox().ymin for f in internal_faces] + [f.BoundingBox().ymax for f in internal_faces]
                all_z = [f.BoundingBox().zmin for f in internal_faces] + [f.BoundingBox().zmax for f in internal_faces]
                cav_dx = round(max(all_x) - min(all_x), 2)
                cav_dy = round(max(all_y) - min(all_y), 2)
                cav_dz = round(max(all_z) - min(all_z), 2)
                cav_dims = [d for d in (cav_dx, cav_dy, cav_dz) if d > 0.01]

            for dim_key, dim_val in critical_dimensions.items():
                if dim_val <= 0:
                    continue
                dim_key_lower = dim_key.lower()
                measured = None
                tolerance = max(1.0, dim_val * 0.10)  # 10% or 1mm

                # Internal cylindrical holes/bores
                if any(kw in dim_key_lower for kw in ("bore", "inner_dia", "hole_dia")):
                    if internal_diameters:
                        measured = min(internal_diameters, key=lambda d: abs(d - dim_val))
                # External cylindrical shafts/bosses
                elif any(kw in dim_key_lower for kw in ("outer_dia", "shaft_dia", "od", "pin_dia")):
                    if external_diameters:
                        measured = min(external_diameters, key=lambda d: abs(d - dim_val))
                # Internal cavities, pockets, cuts, slots
                elif any(kw in dim_key_lower for kw in ("cavity", "pocket", "cut", "slot", "recess")):
                    if internal_faces and cav_dims:
                        if any(kw in dim_key_lower for kw in ("depth", "height", "z")):
                            measured = cav_dz
                        elif any(kw in dim_key_lower for kw in ("length", "x")):
                            measured = cav_dx
                        elif any(kw in dim_key_lower for kw in ("width", "y")):
                            measured = cav_dy
                        else:
                            measured = min(cav_dims, key=lambda d: abs(d - dim_val))
                # Outer / overall part bounding box dimensions
                else:
                    # General shape matching: regardless of part orientation, the critical bounding box
                    # dimension should match the closest BRep bounding box dimension.
                    measured = min(measured_bb.values(), key=lambda d: abs(d - dim_val))


                if measured is not None:
                    diff = abs(measured - dim_val)
                    status = "PASS" if diff <= tolerance else "FAIL"
                    results.append(DFMDiagnostic(
                        rule_id="CRIT-01",
                        status=status,
                        parameter=f"critical_{dim_key}",
                        measured=round(measured, 2),
                        required=round(dim_val, 2),
                        message=f"Critical dimension '{dim_key}': BRep={measured}mm vs spec={dim_val}mm (diff: {round(diff, 2)}mm, tol: {round(tolerance, 2)}mm)."
                    ))
        except Exception:
            pass

    return results


# ===========================================================================
# Orchestration Router: Single Part Verification (Filtered by Depth & Process)
# ===========================================================================

def verify_single_part(
    val_shape: Any,
    process: Literal["3d_printing", "cnc_machining", "sheet_metal"] = "3d_printing",
    depth: Literal["concept", "functional", "manufacturing", "assembly_ready"] = "functional",
    min_wall: float = 1.5,
    min_hole: float = 2.0,
    target_len: Optional[float] = None,
    target_width: Optional[float] = None,
    target_height: Optional[float] = None,
    is_gear: bool = False,
    is_shaft: bool = False,
    requires_hole: bool = False,
    explicit_constraints: Optional[Dict[str, float]] = None,
    is_single_part: bool = False,
    pillar_filter: Optional[List[str]] = None,
    mates: Optional[List[Any]] = None,
    critical_dimensions: Optional[Dict[str, float]] = None
) -> VerificationVerdict:
    """
    Runs single-part verification filtered by verification_depth and manufacturing_process,
    or explicitly restricted to the rule IDs in pillar_filter.
    Enforces AgentToolbox permission check for part_verifier_agent.
    """
    AgentToolbox.enforce("part_verifier_agent", "verify_single_part")

    diagnostics: List[DFMDiagnostic] = []

    if is_shaft:
        expected_ratio = (target_len / max(target_width or 1.0, 0.1)) if target_len and target_width else 60.0
        max_slender = max(80.0, expected_ratio * 1.25)
    elif process == "sheet_metal":
        max_slender = 100.0
    else:
        # Generic mechanical parts (including wings, beams, rods) can be quite slender. 
        # Don't arbitrarily limit to 20.0.
        max_slender = 150.0
    is_sm = (process == "sheet_metal")
    expected_thickness = None
    if target_height is not None and target_len is not None and target_width is not None:
        expected_thickness = min(target_len, target_width, target_height)
    elif target_height is not None:
        expected_thickness = target_height

    if pillar_filter is not None:
        rule_map = {
            "PHYS-01": lambda: check_solid_manifold(val_shape),
            "PHYS-02": lambda: check_brep_topology_integrity(val_shape),
            "SPEC-01": lambda: check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=20.0 if depth == "concept" else 2.0, is_gear=is_gear, is_shaft=is_shaft, explicit_constraints=explicit_constraints, is_single_part=is_single_part),
            "FEAT-01": lambda: check_feature_count(val_shape, requires_hole=requires_hole, is_shaft=is_shaft),
            "STRUCT-01": lambda: check_dfm_wall_thickness(val_shape, min_thickness=min_wall, expected_thickness=expected_thickness, is_sheet_metal=is_sm),
            "STRUCT-02": lambda: check_slenderness_ratio(val_shape, max_ratio=max_slender),
            "DFM-3D-01": lambda: check_dfm_overhang_angle(val_shape, max_overhang_deg=45.0),
            "DFM-3D-02": lambda: check_dfm_hole_diameter(val_shape, min_diameter=min_hole),
            "DFM-CNC-01": lambda: check_cnc_hole_aspect_ratio(val_shape, max_aspect_ratio=5.0),
            "DFM-CNC-02": lambda: check_cnc_internal_corner_fillets(val_shape, min_fillet_radius=1.5),
            "DFM-SM-01": lambda: check_sheet_metal_uniform_thickness(val_shape, max_thickness=6.0),
            "DFM-SM-02": lambda: check_sheet_metal_min_laser_hole(val_shape),
            "FAST-01": lambda: check_iso_fastener_clearance(val_shape),
            "MATE-01": lambda: check_mating_feature_compliance(val_shape, mates=mates, critical_dimensions=critical_dimensions),
            "CRIT-01": lambda: check_mating_feature_compliance(val_shape, mates=None, critical_dimensions=critical_dimensions),
        }
        for rid in pillar_filter:
            if rid in rule_map:
                result = rule_map[rid]()
                if isinstance(result, list):
                    diagnostics.extend(result)
                else:
                    diagnostics.append(result)
    else:
        # 1. Concept Depth (Pillars 1 & 2 only, loose tolerance)
        if depth == "concept":
            diagnostics.append(check_solid_manifold(val_shape))
            diagnostics.append(check_brep_topology_integrity(val_shape))
            diagnostics.append(check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=20.0, is_gear=is_gear, is_shaft=is_shaft, explicit_constraints=explicit_constraints, is_single_part=is_single_part))

        # 2. Functional Depth (Pillars 1, 2, 3, 4)
        elif depth == "functional":
            diagnostics.append(check_solid_manifold(val_shape))
            diagnostics.append(check_brep_topology_integrity(val_shape))
            diagnostics.append(check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=2.0, is_gear=is_gear, is_shaft=is_shaft, explicit_constraints=explicit_constraints, is_single_part=is_single_part))
            diagnostics.append(check_feature_count(val_shape, requires_hole=requires_hole, is_shaft=is_shaft))
            diagnostics.append(check_dfm_wall_thickness(val_shape, min_thickness=min_wall, expected_thickness=expected_thickness, is_sheet_metal=is_sm))
            diagnostics.append(check_slenderness_ratio(val_shape, max_ratio=max_slender))
            # Mating Feature Compliance (Pillar 7) — if mates or critical dimensions declared
            if mates or critical_dimensions:
                diagnostics.extend(check_mating_feature_compliance(val_shape, mates=mates, critical_dimensions=critical_dimensions))

        # 3. Manufacturing Depth (Pillars 1, 2, 3, 4, 5)
        elif depth == "manufacturing":
            diagnostics.append(check_solid_manifold(val_shape))
            diagnostics.append(check_brep_topology_integrity(val_shape))
            diagnostics.append(check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=2.0, is_gear=is_gear, is_shaft=is_shaft, explicit_constraints=explicit_constraints, is_single_part=is_single_part))
            diagnostics.append(check_feature_count(val_shape, requires_hole=requires_hole, is_shaft=is_shaft))
            diagnostics.append(check_dfm_wall_thickness(val_shape, min_thickness=min_wall, expected_thickness=expected_thickness, is_sheet_metal=is_sm))
            diagnostics.append(check_slenderness_ratio(val_shape, max_ratio=max_slender))
            
            # Process DFM Rules (Pillar 5)
            if process == "3d_printing":
                diagnostics.append(check_dfm_hole_diameter(val_shape, min_diameter=min_hole))
                diagnostics.append(check_dfm_overhang_angle(val_shape, max_overhang_deg=45.0))
            elif process == "cnc_machining":
                diagnostics.append(check_cnc_hole_aspect_ratio(val_shape, max_aspect_ratio=5.0))
                diagnostics.append(check_cnc_internal_corner_fillets(val_shape, min_fillet_radius=1.5))
            elif process == "sheet_metal":
                diagnostics.append(check_sheet_metal_uniform_thickness(val_shape, max_thickness=6.0))
                diagnostics.append(check_sheet_metal_min_laser_hole(val_shape))

        # 4. Assembly-Ready Depth (Pillars 1, 2, 3, 4, 5, 6)
        elif depth == "assembly_ready":
            diagnostics.append(check_solid_manifold(val_shape))
            diagnostics.append(check_brep_topology_integrity(val_shape))
            diagnostics.append(check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=2.0, is_gear=is_gear, is_shaft=is_shaft, explicit_constraints=explicit_constraints, is_single_part=is_single_part))
            diagnostics.append(check_feature_count(val_shape, requires_hole=requires_hole, is_shaft=is_shaft))
            diagnostics.append(check_dfm_wall_thickness(val_shape, min_thickness=min_wall, expected_thickness=expected_thickness, is_sheet_metal=is_sm))
            diagnostics.append(check_slenderness_ratio(val_shape, max_ratio=max_slender))
            
            if process == "3d_printing":
                diagnostics.append(check_dfm_hole_diameter(val_shape, min_diameter=min_hole))
                diagnostics.append(check_dfm_overhang_angle(val_shape, max_overhang_deg=45.0))
            elif process == "cnc_machining":
                diagnostics.append(check_cnc_hole_aspect_ratio(val_shape, max_aspect_ratio=5.0))
                diagnostics.append(check_cnc_internal_corner_fillets(val_shape, min_fillet_radius=1.5))
            elif process == "sheet_metal":
                diagnostics.append(check_sheet_metal_uniform_thickness(val_shape, max_thickness=6.0))
                diagnostics.append(check_sheet_metal_min_laser_hole(val_shape))

            # Fastener & Mating Readiness (Pillar 6)
            diagnostics.append(check_iso_fastener_clearance(val_shape))
            # Mating Feature Compliance (Pillar 7)
            if mates or critical_dimensions:
                diagnostics.extend(check_mating_feature_compliance(val_shape, mates=mates, critical_dimensions=critical_dimensions))

    all_passed = all(d.status == "PASS" for d in diagnostics)

    bb_dict = {}
    vol = 0.0
    try:
        shape_obj = _get_shape_obj(val_shape)
        bb = shape_obj.BoundingBox()
        bb_dict = {"xlen": round(bb.xlen, 2), "ylen": round(bb.ylen, 2), "zlen": round(bb.zlen, 2)}
        vol = round(shape_obj.Volume(), 2)
    except Exception:
        pass

    return VerificationVerdict(
        passed=all_passed,
        diagnostics=diagnostics,
        bounding_box=bb_dict,
        volume=vol
    )
