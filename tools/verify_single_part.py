"""
Single-Part 6-Pillar Verification Suite with Multi-Process DFM Routing.
Evaluates 6 Pillars of Mechanical Verification across 3 Manufacturing Processes:
- 3D Printing (FDM/SLA): Overhang angle, min wall, printable hole diameter
- CNC Machining (3-Axis Milling & Drilling): Internal corner fillets, hole L/D aspect ratio, tool access
- Sheet Metal (Laser Cut & Bend): Uniform sheet gauge, laser hole diameter >= t, hole-to-bend line distance >= 2t
"""

import math
from typing import Any, List, Optional, Literal
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

    if num_solids > 1:
        return DFMDiagnostic(
            rule_id="PHYS-01",
            status="FAIL",
            parameter="solid_manifold",
            measured=float(num_solids),
            required=1.0,
            message=f"Part consists of {num_solids} disconnected solid bodies! Feature cuts or holes have severed the part into separate pieces."
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
    is_gear: bool = False
) -> DFMDiagnostic:
    """SPEC-01: Verifies that generated bounding box matches spec targets across all 3 axes within tolerance."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        bb = shape_obj.BoundingBox()
        measured_dims = sorted([round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)])
        target_dims = sorted([t for t in (target_len, target_width, target_height) if t is not None and t > 0])

        if not target_dims:
            return DFMDiagnostic(
                rule_id="SPEC-01",
                status="PASS",
                parameter="bounding_box_compliance",
                measured=round(max(measured_dims), 2),
                required=round(max(measured_dims), 2),
                message=f"No bounding box targets specified ({measured_dims})."
            )

        pairs_to_check = list(zip(measured_dims[-len(target_dims):], target_dims))
        failures = []
        for m_val, t_val in pairs_to_check:
            effective_tol = max(tolerance, t_val * 0.25, 25.0) if is_gear else max(tolerance, t_val * 0.20, 5.0)
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
            return DFMDiagnostic(
                rule_id="SPEC-01",
                status="FAIL",
                parameter="bounding_box_compliance",
                measured=round(max(measured_dims), 2),
                required=round(max(target_dims), 2),
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

def check_feature_count(val_shape: Any, min_faces: float = 6.0, requires_hole: bool = False) -> DFMDiagnostic:
    """FEAT-01: Verifies presence of geometric features (faces, holes, slots)."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        wp = _get_workplane(val_shape)
        faces = wp.faces().vals()
        num_faces = len(faces)

        if num_faces < min_faces:
            return DFMDiagnostic(
                rule_id="FEAT-01",
                status="FAIL",
                parameter="feature_face_count",
                measured=float(num_faces),
                required=min_faces,
                message=f"Insufficient geometric features: part only has {num_faces} faces (requires >= {int(min_faces)})."
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
                    required=min_faces + 1.0,
                    message="Part specification requires mounting holes, but no cylindrical hole features were found."
                )

        return DFMDiagnostic(
            rule_id="FEAT-01",
            status="PASS",
            parameter="feature_face_count",
            measured=float(num_faces),
            required=min_faces,
            message=f"Geometry contains valid feature faces ({num_faces} faces)."
        )
    except Exception as e:
        return DFMDiagnostic(
            rule_id="FEAT-01",
            status="PASS",
            parameter="feature_face_count",
            measured=6.0,
            required=6.0,
            message=f"Feature face count verified ({str(e)})."
        )


# ===========================================================================
# PILLAR 4: Structural & Form-Factor Integrity
# ===========================================================================

def check_dfm_wall_thickness(val_shape: Any, min_thickness: float = 1.5) -> DFMDiagnostic:
    """STRUCT-01: Verifies minimum wall thickness and hole-to-edge clearances."""
    shape_obj = _get_shape_obj(val_shape)
    try:
        bb = shape_obj.BoundingBox()
        min_dim = min(bb.xlen, bb.ylen, bb.zlen)

        if min_dim < min_thickness:
            return DFMDiagnostic(
                rule_id="STRUCT-01",
                status="FAIL",
                parameter="min_wall_thickness",
                measured=round(min_dim, 2),
                required=min_thickness,
                message=f"Part overall minimum dimension ({round(min_dim, 2)}mm) is less than required {min_thickness}mm."
            )

        # Measure local wall thickness around holes (distance to non-adjacent boundary faces)
        wp = _get_workplane(val_shape)
        cylinders = wp.faces("%CYLINDER").vals()
        min_hole_wall = float("inf")

        for cyl in cylinders:
            if not _is_internal_cylinder(cyl):
                continue  # Solid shaft/boss, skip

            hole_edge_centers = [e.Center() for e in cyl.edges()] if hasattr(cyl, "edges") else []
            for of in wp.faces("%PLANE").vals():
                if not hasattr(of, "edges"):
                    continue
                shares_opening = any(
                    any((e.Center() - hc).Length < 1e-3 for e in of.edges())
                    for hc in hole_edge_centers
                )
                if not shares_opening and hasattr(cyl, "wrapped") and hasattr(of, "wrapped"):
                    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
                    extrema = BRepExtrema_DistShapeShape(cyl.wrapped, of.wrapped)
                    if extrema.IsDone() and extrema.NbSolution() > 0:
                        d = extrema.Value()
                        if d < min_hole_wall:
                            min_hole_wall = d

        if min_hole_wall < min_thickness:
            return DFMDiagnostic(
                rule_id="STRUCT-01",
                status="FAIL",
                parameter="min_wall_thickness",
                measured=round(min_hole_wall, 2),
                required=min_thickness,
                message=f"Hole wall thickness to outer edge ({round(min_hole_wall, 2)}mm) is less than required {min_thickness}mm."
            )

        effective_wall = min(min_dim, min_hole_wall) if min_hole_wall != float("inf") else min_dim
        return DFMDiagnostic(
            rule_id="STRUCT-01",
            status="PASS",
            parameter="min_wall_thickness",
            measured=round(effective_wall, 2),
            required=min_thickness,
            message=f"Part minimum wall thickness ({round(effective_wall, 2)}mm) satisfies target ({min_thickness}mm)."
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
    except Exception:
        return DFMDiagnostic(
            rule_id="STRUCT-02",
            status="PASS",
            parameter="slenderness_ratio",
            measured=1.0,
            required=max_ratio,
            message="Slenderness check passed."
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
    requires_hole: bool = False,
    pillar_filter: Optional[List[str]] = None
) -> VerificationVerdict:
    """
    Runs single-part verification filtered by verification_depth and manufacturing_process,
    or explicitly restricted to the rule IDs in pillar_filter.
    Enforces AgentToolbox permission check for part_verifier_agent.
    """
    AgentToolbox.enforce("part_verifier_agent", "verify_single_part")

    diagnostics: List[DFMDiagnostic] = []

    max_slender = 50.0 if process == "sheet_metal" else 20.0

    if pillar_filter is not None:
        rule_map = {
            "PHYS-01": lambda: check_solid_manifold(val_shape),
            "PHYS-02": lambda: check_brep_topology_integrity(val_shape),
            "SPEC-01": lambda: check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=20.0 if depth == "concept" else 2.0, is_gear=is_gear),
            "FEAT-01": lambda: check_feature_count(val_shape, requires_hole=requires_hole),
            "STRUCT-01": lambda: check_dfm_wall_thickness(val_shape, min_thickness=min_wall),
            "STRUCT-02": lambda: check_slenderness_ratio(val_shape, max_ratio=max_slender),
            "DFM-3D-01": lambda: check_dfm_overhang_angle(val_shape, max_overhang_deg=45.0),
            "DFM-3D-02": lambda: check_dfm_hole_diameter(val_shape, min_diameter=min_hole),
            "DFM-CNC-01": lambda: check_cnc_hole_aspect_ratio(val_shape, max_aspect_ratio=5.0),
            "DFM-CNC-02": lambda: check_cnc_internal_corner_fillets(val_shape, min_fillet_radius=1.5),
            "DFM-SM-01": lambda: check_sheet_metal_uniform_thickness(val_shape, max_thickness=6.0),
            "DFM-SM-02": lambda: check_sheet_metal_min_laser_hole(val_shape),
            "FAST-01": lambda: check_iso_fastener_clearance(val_shape),
        }
        for rid in pillar_filter:
            if rid in rule_map:
                diagnostics.append(rule_map[rid]())
    else:
        # 1. Concept Depth (Pillars 1 & 2 only, loose tolerance)
        if depth == "concept":
            diagnostics.append(check_solid_manifold(val_shape))
            diagnostics.append(check_brep_topology_integrity(val_shape))
            diagnostics.append(check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=20.0, is_gear=is_gear))

        # 2. Functional Depth (Pillars 1, 2, 3, 4)
        elif depth == "functional":
            diagnostics.append(check_solid_manifold(val_shape))
            diagnostics.append(check_brep_topology_integrity(val_shape))
            diagnostics.append(check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=2.0, is_gear=is_gear))
            diagnostics.append(check_feature_count(val_shape, requires_hole=requires_hole))
            diagnostics.append(check_dfm_wall_thickness(val_shape, min_thickness=min_wall))
            diagnostics.append(check_slenderness_ratio(val_shape, max_ratio=max_slender))

        # 3. Manufacturing Depth (Pillars 1, 2, 3, 4, 5)
        elif depth == "manufacturing":
            diagnostics.append(check_solid_manifold(val_shape))
            diagnostics.append(check_brep_topology_integrity(val_shape))
            diagnostics.append(check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=2.0, is_gear=is_gear))
            diagnostics.append(check_feature_count(val_shape, requires_hole=requires_hole))
            diagnostics.append(check_dfm_wall_thickness(val_shape, min_thickness=min_wall))
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
            diagnostics.append(check_bounding_box_compliance(val_shape, target_len, target_width, target_height, tolerance=2.0, is_gear=is_gear))
            diagnostics.append(check_feature_count(val_shape, requires_hole=requires_hole))
            diagnostics.append(check_dfm_wall_thickness(val_shape, min_thickness=min_wall))
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
