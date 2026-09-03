"""
Assembly Agent (Assembler).
Positions verified part solids deterministically using InterfacePorts and AssemblyGraph joint definitions into cq.Assembly().
"""

from typing import Dict, Any, Tuple, List, Optional
import cadquery as cq
from orchestrator.models import AssemblyGraph, InterfacePort
from orchestrator.gateway_client import GatewayClient
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
    Finds matching interface ports between two mating parts:
    1. Direct name match (e.g. mate.my_feature_name, "center_hole", "hole_center_1", "shaft_tip")
    2. Semantic feature_type match (hole <-> shaft, bore <-> pin, face <-> face)
    3. Any available port pair
    """
    if not partner_ports or not my_ports:
        return None, None

    # 1. Check exact name matches
    if mate and mate.my_feature_name in partner_ports and mate.my_feature_name in my_ports:
        return partner_ports[mate.my_feature_name], my_ports[mate.my_feature_name]

    # 2. Semantic matching: Find 'hole'/'bore' in partner and 'shaft'/'pin' in my_ports
    target_hole = next(
        (p for p in partner_ports.values() if p.feature_type in ("hole", "bore") or "hole" in p.name.lower()),
        None
    )
    my_shaft = next(
        (p for p in my_ports.values() if p.feature_type in ("shaft", "pin", "bolt") or "shaft" in p.name.lower() or "tip" in p.name.lower() or "bolt" in p.name.lower()),
        None
    )
    if target_hole and my_shaft:
        return target_hole, my_shaft

    # Reverse: shaft in partner and hole in my_ports
    target_shaft = next(
        (p for p in partner_ports.values() if p.feature_type in ("shaft", "pin", "bolt") or "shaft" in p.name.lower() or "tip" in p.name.lower()),
        None
    )
    my_hole = next(
        (p for p in my_ports.values() if p.feature_type in ("hole", "bore") or "hole" in p.name.lower()),
        None
    )
    if target_shaft and my_hole:
        return target_shaft, my_hole

    # 3. Fallback to first available port pair
    p_port = next(iter(partner_ports.values()), None)
    m_port = next(iter(my_ports.values()), None)
    return p_port, m_port


class AssemblyAgent:
    """Mates verified CAD solids deterministically into a single multi-part assembly."""

    def __init__(self, gateway_client: Optional[GatewayClient] = None):
        self.gateway = gateway_client

    async def assemble_parts(
        self,
        graph: AssemblyGraph,
        solids: Dict[str, Any],
        interfaces: Dict[str, Dict[str, InterfacePort]],
        positioning_repair_prompt: str = ""
    ) -> Tuple[Dict[str, Any], Any]:
        """
        Positions verified solids deterministically based on InterfacePorts and returns:
        (Dict of transformed shapes, top-level cq.Assembly object).
        """
        AgentToolbox.enforce("assembly_agent", "cad_kernel_assembly")

        transformed_solids: Dict[str, Any] = {}
        cq_assembly = cq.Assembly()

        if not graph.parts:
            return transformed_solids, cq_assembly

        # 1. Base Part: Central component (sun gear, central housing, or base) remains at origin
        base_part_spec = next(
            (p for p in graph.parts if "sun" in p.id.lower() or "sun" in p.name.lower()),
            None
        )
        if not base_part_spec:
            base_part_spec = next(
                (p for p in graph.parts if any(kw in p.id.lower() or kw in p.name.lower() for kw in ["housing", "casing", "base"])),
                graph.parts[0]
            )

        base_solid = _get_shape_obj(solids.get(base_part_spec.id))
        if base_solid:
            transformed_solids[base_part_spec.id] = base_solid
            cq_assembly.add(base_solid, name=base_part_spec.id, color=cq.Color(0.8, 0.8, 0.8, 1.0))

        # 2. Position Partner Parts relative to Base Part via InterfacePorts
        remaining_parts = [p for p in graph.parts if p.id != base_part_spec.id]
        for part_spec in remaining_parts:
            part_solid = _get_shape_obj(solids.get(part_spec.id))
            if not part_solid:
                continue

            # Look up mate context
            mate = part_spec.mates[0] if part_spec.mates else None
            partner_id = mate.partner_id if mate else base_part_spec.id
            if partner_id not in transformed_solids:
                partner_id = base_part_spec.id

            p_ports = interfaces.get(partner_id, {})
            my_ports = interfaces.get(part_spec.id, {})

            target_port, my_port = _find_compatible_ports(p_ports, my_ports, mate)

            if target_port and my_port:
                # Calculate translation vector from my_port to target_port
                tx = target_port.position[0] - my_port.position[0]
                ty = target_port.position[1] - my_port.position[1]
                tz = target_port.position[2] - my_port.position[2]

                # Specialized kinematic alignment for gear mechanisms
                p_name = part_spec.name.lower()
                p_id = part_spec.id.lower()
                is_ring = any(kw in p_name or kw in p_id for kw in ["ring", "casing", "housing"])
                is_carrier = any(kw in p_name or kw in p_id for kw in ["carrier", "spider"])
                is_planet = any(kw in p_name or kw in p_id for kw in ["planet", "pinion"]) and not is_ring and not is_carrier

                shared_p = graph.shared_parameters or graph.master_skeleton

                if is_ring:
                    # Concentric outer housing: centered at assembly origin (0, 0, 0)
                    tx = 0.0
                    ty = 0.0
                    tz = 0.0

                elif is_carrier:
                    # Carrier plate: centered on central shaft axis (0, 0), plate positioned below gears
                    tx = 0.0
                    ty = 0.0
                    bb = part_solid.BoundingBox()
                    # If carrier plate was extruded upwards from Z=0, shift below Z=0 so its top mates with gear undersides
                    if bb.zmin >= -0.01:
                        tz = -bb.zlen
                    else:
                        tz = 0.0

                elif is_planet:
                    c_dist = float(
                        shared_p.get("center_to_center_distance") or
                        shared_p.get("orbit_radius") or
                        shared_p.get("center_distance") or 0.0
                    )
                    tx = c_dist
                    ty = 0.0
                    tz = 0.0

                    # 1D tooth mesh angle sweep to eliminate tooth tip interference with sun gear
                    partner_solid = transformed_solids.get(partner_id) or transformed_solids.get(base_part_spec.id)
                    if partner_solid:
                        best_angle = 0.0
                        min_overlap = float("inf")
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
                        part_solid = part_solid.rotate((0, 0, 0), (0, 0, 1), best_angle)

                # Apply translation
                moved_solid = part_solid.translate((tx, ty, tz))

                num_planets = int(shared_p.get("num_planets", 1)) if is_planet else 1
                if num_planets > 1:
                    step_deg = 360.0 / num_planets
                    for k in range(num_planets):
                        p_angle = k * step_deg
                        meshed_planet = moved_solid.rotate((0, 0, 0), (0, 0, 1), p_angle)
                        p_id = f"{part_spec.id}_{k+1}" if k > 0 else part_spec.id
                        transformed_solids[p_id] = meshed_planet
                        cq_assembly.add(meshed_planet, name=p_id, color=cq.Color(0.2, 0.6, 0.9, 1.0))
                else:
                    transformed_solids[part_spec.id] = moved_solid
                    cq_assembly.add(moved_solid, name=part_spec.id, color=cq.Color(0.2, 0.6, 0.9, 1.0))
            else:
                # Origin placement (shift carrier plate below gears if applicable)
                p_name = part_spec.name.lower()
                p_id = part_spec.id.lower()
                is_carrier = any(kw in p_name or kw in p_id for kw in ["carrier", "spider"])
                if is_carrier:
                    bb = part_solid.BoundingBox()
                    tz = -bb.zlen if bb.zmin >= -0.01 else 0.0
                    part_solid = part_solid.translate((0, 0, tz))
                transformed_solids[part_spec.id] = part_solid
                cq_assembly.add(part_solid, name=part_spec.id, color=cq.Color(0.5, 0.5, 0.5, 1.0))

        return transformed_solids, cq_assembly
