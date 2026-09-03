"""
Assembly Repair Agent (Diagnostic Router).
Analyzes failed AssemblyVerdict diagnostics and routes targeted repair instructions:
- Geometry Fault (e.g. feature size mismatch) -> Target Part Designer Agent
- Positioning Fault (e.g. coordinate alignment mismatch) -> Assembly Agent
- Retry Exhaustion -> Planner Agent (Re-decomposition)
"""

from typing import Optional, List
from orchestrator.models import AssemblyVerdict, AssemblyGraph, RepairInstruction
from orchestrator.gateway_client import GatewayClient
from orchestrator.toolbox import AgentToolbox


class AssemblyRepairAgent:
    """Diagnostic router classifying assembly failures and generating targeted repair payloads."""

    def __init__(self, gateway_client: Optional[GatewayClient] = None):
        self.gateway = gateway_client

    def diagnose_repair(
        self,
        verdict: AssemblyVerdict,
        graph: AssemblyGraph,
        retry_count: int = 1
    ) -> RepairInstruction:
        """
        Diagnoses root cause of assembly verification failure and emits a RepairInstruction.
        """
        if retry_count > 5:
            # Escalation to Planner
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

        # Rule 1: Fit Clearance Diagnostics (ASSY-02)
        if first_fail.rule_id == "ASSY-02":
            clearance = first_fail.measured
            # If clearance > 3.0mm, parts missed each other completely -> POSITIONING FAULT
            if clearance > 3.0:
                return RepairInstruction(
                    target_agent="assembly_agent",
                    target_part_id="assembly",
                    fault_type="positioning",
                    failed_diagnostics=[d.model_dump() for d in failed_diags],
                    prompt=(
                        f"Assembly Positioning Failure [ASSY-02]: Mating clearance is {clearance}mm (> 0.5mm limit). "
                        f"Parts '{involved}' are displaced in 3D space. "
                        f"Please align the mating InterfacePorts so features coincide."
                    )
                )
            else:
                # Small tolerance deviation (e.g. 0.05mm tight bind or 0.8mm loose fit) -> GEOMETRY FAULT
                target_part_id = involved[1] if len(involved) > 1 else (involved[0] if involved else "part_1")
                return RepairInstruction(
                    target_agent="code_generator_agent",
                    target_part_id=target_part_id,
                    fault_type="geometry",
                    failed_diagnostics=[d.model_dump() for d in failed_diags],
                    prompt=(
                        f"Assembly Geometry Failure [ASSY-02]: Clearance {clearance}mm is outside [0.1mm, 0.5mm]. "
                        f"Please adjust '{target_part_id}' feature diameter to achieve correct mating fit clearance."
                    )
                )

        # Rule 2: Interference Overlap Diagnostics (ASSY-01)
        if first_fail.rule_id == "ASSY-01":
            overlap = first_fail.measured
            # If overlap is massive (> 500 mm³), parts occupy the same location -> POSITIONING FAULT
            if overlap > 500.0:
                return RepairInstruction(
                    target_agent="assembly_agent",
                    target_part_id="assembly",
                    fault_type="positioning",
                    failed_diagnostics=[d.model_dump() for d in failed_diags],
                    prompt=(
                        f"Assembly Positioning Failure [ASSY-01]: Severe interference detected ({overlap} mm³). "
                        f"Parts '{involved}' are co-located at origin. Translate components to separate mating positions."
                    )
                )
            else:
                target_part_id = involved[1] if len(involved) > 1 else (involved[0] if involved else "part_1")
                return RepairInstruction(
                    target_agent="code_generator_agent",
                    target_part_id=target_part_id,
                    fault_type="geometry",
                    failed_diagnostics=[d.model_dump() for d in failed_diags],
                    prompt=(
                        f"Assembly Geometry Failure [ASSY-01]: Interference {overlap} mm³ between '{involved}'. "
                        f"Please reduce feature size of '{target_part_id}' or increase clearance hole diameter."
                    )
                )

        # Rule 3: Kinematic Sweep & Other Positioning Faults
        return RepairInstruction(
            target_agent="assembly_agent",
            target_part_id="assembly",
            fault_type="positioning",
            failed_diagnostics=[d.model_dump() for d in failed_diags],
            prompt=f"Positioning Failure: {first_fail.message}. Adjust transform vectors for InterfacePorts alignment."
        )
