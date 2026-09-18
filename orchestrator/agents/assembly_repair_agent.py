"""
Assembly Repair Agent (Diagnostic Router & Graph Patcher).
Analyzes failed AssemblyVerdict diagnostics with 3-way triage:

  (a) Graph/Port Mismatch   → Directly patches the AssemblyGraph (zero LLM)
  (b) Tolerance/Fit Mismatch → Patches graph clearances + code variables (zero LLM)
  (c) True Geometry Defect   → Routes to PartRepairAgent (parametric fix first, Designer as last resort)

LLM: NO — this agent never calls the LLM.
Tools: graph_editor, code_editor
"""

import copy
from typing import Optional, List, Dict, Any
from orchestrator.models import AssemblyVerdict, AssemblyGraph, RepairInstruction
from orchestrator.agents.part_repair_agent import PartRepairAgent


class AssemblyRepairAgent:
    """
    Diagnostic router with direct graph and code patching capabilities.
    100% deterministic — no LLM dependency.
    """

    def __init__(self, gateway_client: Optional[Any] = None):
        self._part_repair = PartRepairAgent()

    def diagnose_repair(
        self,
        verdict: AssemblyVerdict,
        graph: AssemblyGraph,
        retry_count: int = 1,
        part_codes: Optional[Dict[str, str]] = None
    ) -> RepairInstruction:
        """
        3-way triage on assembly verification failure:
        1. Try graph/port patch (zero LLM tokens)
        2. Try tolerance/clearance patch (zero LLM tokens)
        3. Fall back to geometry repair via PartRepairAgent → Designer escalation
        """
        if retry_count > 5:
            return RepairInstruction(
                target_agent="planner_agent",
                target_part_id=graph.parts[0].id if graph.parts else "part_1",
                fault_type="geometry",
                failed_diagnostics=[d.model_dump() for d in verdict.diagnostics if d.status == "FAIL"],
                prompt="Assembly retries exhausted. Please re-decompose AssemblyGraph with modified part specs."
            )

        failed_diags = [d for d in verdict.diagnostics if d.status == "FAIL"]
        if not failed_diags:
            return RepairInstruction(
                target_agent="assembly_agent",
                target_part_id="assembly",
                fault_type="positioning",
                prompt="Assembly passed."
            )

        first_fail = failed_diags[0]
        involved = first_fail.involved_parts

        # ===================================================================
        # Triage Branch (b): Fit Clearance / Tolerance Mismatch (ASSY-02)
        # ===================================================================
        if first_fail.rule_id == "ASSY-02":
            clearance = first_fail.measured

            # Large clearance (>3mm) = positioning fault, not tolerance
            if clearance > 3.0:
                return self._positioning_fault(failed_diags, involved,
                    f"Mating clearance is {clearance}mm (> 0.5mm limit). "
                    f"Parts '{involved}' are displaced in 3D space. "
                    f"Translate by Z=-{clearance}mm to close the gap and align the InterfacePorts."
                )

            # Small clearance deviation → try tolerance patch
            patch = self._try_tolerance_fix(first_fail, graph, part_codes)
            if patch:
                return patch

            # Fall through to geometry fix
            target_part_id = involved[1] if len(involved) > 1 else (involved[0] if involved else "part_1")
            return RepairInstruction(
                target_agent="part_repair_agent",
                target_part_id=target_part_id,
                fault_type="geometry",
                failed_diagnostics=[d.model_dump() for d in failed_diags],
                prompt=(
                    f"Assembly Geometry Failure [ASSY-02]: Clearance {clearance}mm is outside [0.1mm, 0.5mm]. "
                    f"Please adjust '{target_part_id}' feature diameter to achieve correct mating fit clearance."
                )
            )

        # ===================================================================
        # Triage Branch (a) / (c): Interference Overlap (ASSY-01)
        # ===================================================================
        if first_fail.rule_id == "ASSY-01":
            overlap = first_fail.measured
            msg_lower = first_fail.message.lower()

            # Case A: Gross solid collision (internal cavity filled)
            if "gross solid collision" in msg_lower or "internal cavity" in msg_lower or "hollow" in msg_lower:
                target_part_id = self._pick_container_part(involved, graph)
                counterpart = [p for p in involved if p != target_part_id][0] if len(involved) > 1 else "mating part"
                return RepairInstruction(
                    target_agent="part_repair_agent",
                    target_part_id=target_part_id,
                    fault_type="geometry",
                    failed_diagnostics=[d.model_dump() for d in failed_diags],
                    prompt=(
                        f"Assembly Gross Solid Interference [ASSY-01]: Severe overlap detected between '{involved}'. "
                        f"The internal cavity of '{target_part_id}' appears to be filled with solid material instead of being hollow. "
                        f"Please ensure '{target_part_id}' has an internal cavity or bore sized to accept '{counterpart}'. "
                        f"Ensure the cavity penetrates cleanly and does not obstruct mating components, while maintaining adequate wall thickness to preserve part integrity."
                    )
                )

            # Case B: Axial stacking collision → GRAPH PATCH (positioning fix)
            if "axial stacking collision" in msg_lower or "stacked sequentially" in msg_lower:
                # Try to fix by patching the graph port offsets
                patch = self._try_axial_stack_fix(first_fail, graph)
                if patch:
                    return patch
                # Fallback to positioning repair
                return self._positioning_fault(failed_diags, involved,
                    f"Severe axial overlap between '{involved}'. "
                    f"Parts are co-located on the same axis. They must be stacked sequentially along the axis."
                )

            # Case C: Minor interference → try graph patch first (port offset adjustment)
            if overlap > 50.0 and "compliant" not in msg_lower and "mesh" not in msg_lower and retry_count <= 1:
                # Large rigid overlap on first try → likely a positioning issue
                patch = self._try_port_offset_fix(first_fail, graph)
                if patch:
                    return patch
                return self._positioning_fault(failed_diags, involved,
                    f"Severe interference detected ({overlap} mm³). "
                    f"Parts '{involved}' are co-located. Translate components to correct mating positions."
                )
            else:
                # Compliant/gear mesh or small interference → geometry fix via PartRepairAgent
                if retry_count % 2 == 1:
                    target_part_id = involved[1] if len(involved) > 1 else (involved[0] if involved else "part_1")
                else:
                    target_part_id = involved[0] if involved else "part_1"

                return RepairInstruction(
                    target_agent="part_repair_agent",
                    target_part_id=target_part_id,
                    fault_type="geometry",
                    failed_diagnostics=[d.model_dump() for d in failed_diags],
                    prompt=(
                        f"Assembly Geometry Interference [ASSY-01]: Interference {overlap} mm³ between '{involved}'. "
                        f"Parts are correctly positioned coaxially. Do NOT translate them away in space. "
                        f"Please adjust feature dimensions of '{target_part_id}' (e.g. reduce outer dimension/tooth radius or increase mating clearance/bore) to eliminate solid collision."
                    )
                )

        # Default: Positioning fault
        return self._positioning_fault(failed_diags, involved,
            f"Positioning Failure: {first_fail.message}. Adjust transform vectors for InterfacePorts alignment."
        )

    # ------------------------------------------------------------------
    # Graph Patching Methods (Zero LLM)
    # ------------------------------------------------------------------

    def _try_port_offset_fix(
        self,
        diag,
        graph: AssemblyGraph
    ) -> Optional[RepairInstruction]:
        """
        Attempts to fix interference by adjusting port offsets / shared_parameters
        in the AssemblyGraph directly.  Zero LLM tokens.
        """
        involved = diag.involved_parts
        if len(involved) < 2:
            return None

        shared = graph.shared_parameters or {}
        # If there's a center_distance that could be wrong, try incrementing it
        c_key = next((k for k in shared if "center" in k.lower() and "distance" in k.lower()), None)
        if c_key and shared[c_key]:
            patched_graph = copy.deepcopy(graph)
            old_val = float(patched_graph.shared_parameters[c_key])
            # Increase center distance by 10% to clear interference
            new_val = round(old_val * 1.1, 2)
            patched_graph.shared_parameters[c_key] = new_val
            return RepairInstruction(
                target_agent="assembly_agent",
                target_part_id="assembly",
                fault_type="graph_patch",
                failed_diagnostics=[diag.model_dump()],
                prompt=(
                    f"Graph Patch [ASSY-01]: Adjusted {c_key} from {old_val} to {new_val}mm "
                    f"to clear interference between '{involved}'."
                ),
                patched_graph=patched_graph
            )
        return None

    def _try_axial_stack_fix(
        self,
        diag,
        graph: AssemblyGraph
    ) -> Optional[RepairInstruction]:
        """
        Attempts to fix axial stacking collision by adjusting port Z-offsets
        in shared_parameters.  Zero LLM tokens.
        """
        involved = diag.involved_parts
        if len(involved) < 2:
            return None

        # Look for parts involved and check if we can compute a stacking offset
        p_specs = {p.id: p for p in graph.parts if p.id in involved}
        if len(p_specs) >= 2:
            part_a = p_specs.get(involved[0])
            part_b = p_specs.get(involved[1])
            if part_a and part_b:
                # Stack part_b on top of part_a with clearance spacing
                patched_graph = copy.deepcopy(graph)
                if "axial_offsets" not in patched_graph.shared_parameters:
                    patched_graph.shared_parameters["axial_offsets"] = {}
                current_offset = float(patched_graph.shared_parameters["axial_offsets"].get(involved[1], 0.0))
                step = part_a.height if part_a.height > 0 else 10.0
                if current_offset < step:
                    z_offset = step
                else:
                    z_offset = current_offset + step
                patched_graph.shared_parameters["axial_offsets"][involved[1]] = z_offset

                return RepairInstruction(
                    target_agent="assembly_agent",
                    target_part_id="assembly",
                    fault_type="graph_patch",
                    failed_diagnostics=[diag.model_dump()],
                    prompt=(
                        f"Graph Patch [ASSY-01]: Added axial offset Z={z_offset}mm for '{involved[1]}' "
                        f"to stack above '{involved[0]}'."
                    ),
                    patched_graph=patched_graph
                )
        return None

    def _try_tolerance_fix(
        self,
        diag,
        graph: AssemblyGraph,
        part_codes: Optional[Dict[str, str]] = None
    ) -> Optional[RepairInstruction]:
        """
        Attempts to fix fit clearance by patching both graph clearance values
        and CadQuery variable assignments.  Zero LLM tokens.
        """
        involved = diag.involved_parts
        clearance = diag.measured
        required_range = (0.1, 0.5)

        if clearance < required_range[0]:
            # Too tight — need to increase hole diameter or decrease shaft
            delta = round(required_range[0] - clearance + 0.05, 3)  # Add margin
        elif clearance > required_range[1]:
            # Too loose — need to decrease hole diameter or increase shaft
            delta = round(required_range[1] - clearance - 0.05, 3)  # Negative delta
        else:
            return None  # Within range

        # Patch graph clearances
        patched_graph = copy.deepcopy(graph)
        patched_code: Dict[str, str] = {}

        for part in patched_graph.parts:
            if part.id in involved:
                for mate in part.mates:
                    if mate.partner_id in involved:
                        mate.clearance_mm = round(mate.clearance_mm + delta, 3)
                        if mate.my_feature_diameter:
                            if mate.mate_type in ("hole_shaft", "shaft_hole"):
                                # Adjust the hole side
                                if "hole" in mate.mate_type.split("_")[0]:
                                    mate.my_feature_diameter = round(mate.my_feature_diameter + delta, 3)
                                    part.hole_diameter = mate.my_feature_diameter

        # Try to patch code variables if available
        if part_codes:
            for pid in involved:
                code = part_codes.get(pid)
                if not code:
                    continue
                # Find diameter variables and adjust
                variables = self._part_repair._parse_variables(code)
                for vname, (val, line_no, old_line) in variables.items():
                    if any(kw in vname.lower() for kw in ("hole_dia", "bore_dia", "inner_dia", "shaft_dia")):
                        new_val = round(val + delta, 3)
                        patched_code[pid] = self._part_repair._replace_variable(code, vname, old_line, new_val)
                        break

        return RepairInstruction(
            target_agent="assembly_agent",
            target_part_id="assembly",
            fault_type="tolerance_patch",
            failed_diagnostics=[diag.model_dump()],
            prompt=(
                f"Tolerance Patch [ASSY-02]: Adjusted clearance by {delta}mm for '{involved}' "
                f"to bring fit within [{required_range[0]}, {required_range[1]}]mm range."
            ),
            patched_graph=patched_graph,
            patched_code=patched_code if patched_code else None
        )

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------

    def _pick_container_part(self, involved: List[str], graph: AssemblyGraph) -> str:
        """Picks the larger/outer container part from the involved parts."""
        if not involved:
            return "part_1"
        if len(involved) < 2:
            return involved[0]
        p_specs = {p.id: p for p in graph.parts if p.id in involved}
        if len(p_specs) >= 2:
            return max(p_specs.keys(), key=lambda pid: getattr(p_specs[pid], "width", 0.0) * getattr(p_specs[pid], "length", 0.0))
        return involved[0]

    def _positioning_fault(
        self,
        failed_diags,
        involved: List[str],
        message: str
    ) -> RepairInstruction:
        """Creates a positioning fault RepairInstruction."""
        return RepairInstruction(
            target_agent="assembly_agent",
            target_part_id="assembly",
            fault_type="positioning",
            failed_diagnostics=[d.model_dump() for d in failed_diags],
            prompt=f"Assembly Positioning Failure: {message}"
        )


# Backward compatibility alias
AssemblyCriticAgent = AssemblyRepairAgent
