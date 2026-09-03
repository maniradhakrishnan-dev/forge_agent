"""
Part Repair Agent.
Formats diagnostic failure JSON from Part Critic Agent into targeted repair instructions for Part Designer.
"""

import json
from typing import List, Dict, Any
from orchestrator.models import VerificationVerdict


class PartRepairAgent:
    """Formats single-part DFM diagnostic feedback into actionable repair prompts."""

    def generate_repair_instructions(self, verdict: VerificationVerdict) -> str:
        """
        Extracts failed DFM diagnostics and formats an actionable, parametric repair prompt.
        """
        failed_diagnostics = [d for d in verdict.diagnostics if d.status == "FAIL"]
        if not failed_diagnostics:
            return ""

        instructions = ["The previous CadQuery script failed the following ground-truth geometric checks:"]
        for diag in failed_diagnostics:
            instructions.append(
                f"- [{diag.rule_id}] {diag.parameter}: Measured {diag.measured}mm, Required {diag.required}mm. Message: {diag.message}"
            )
            # Add actionable parametric advice
            if diag.rule_id == "SPEC-01":
                if diag.measured > diag.required:
                    diff = round(diag.measured - diag.required, 2)
                    instructions.append(
                        f"  -> ACTION: The part is {diff}mm too large. Reduce outer dimensions (e.g. decrease pitch_dia, outer radius, or length/width) so the physical bounding box is <= {diag.required}mm."
                    )
                else:
                    diff = round(diag.required - diag.measured, 2)
                    instructions.append(
                        f"  -> ACTION: The part is {diff}mm too small. Increase outer dimensions by {diff}mm to match target {diag.required}mm."
                    )
            elif diag.rule_id == "PHYS-01":
                instructions.append(
                    f"  -> ACTION: The part severed into {diag.measured} disconnected solid bodies! "
                    f"Holes or cuts sliced completely through walls or gear tooth roots. "
                    f"Increase the outer casing/flange radius, reduce hole diameters, or ensure mounting holes are located on an outer flange beyond tooth roots."
                )
            elif diag.rule_id == "STRUCT-01":
                instructions.append(
                    f"  -> ACTION: Minimum wall thickness is too thin ({diag.measured}mm). Increase wall/feature thickness to >= {diag.required}mm."
                )
            elif diag.rule_id == "DFM-3D-02":
                instructions.append(
                    f"  -> ACTION: Hole diameter {diag.measured}mm is too small for 3D printing. Increase hole diameter to >= {diag.required}mm."
                )

        instructions.append(
            "\nPlease adjust the CadQuery parameters in the PREVIOUS CODE to satisfy these exact constraints."
        )

        return "\n".join(instructions)

    def generate_syntax_repair_instructions(self, exec_error: str, code: str = "") -> str:
        """Formats CadQuery execution traceback with targeted debugging guidance."""
        guidance = ""
        if ("Standard_Failure" in exec_error or "StdFail_NotDone" in exec_error or "BRep_API" in exec_error) and ("fillet" in exec_error or "chamfer" in exec_error):
            guidance = (
                "\n  -> CRITICAL HINT: OpenCascade fillet/chamfer failed (BRep_API / StdFail_NotDone). Avoid chamfering or filleting "
                "tight gear tooth profiles, tooth root edges, or top/bottom faces that intersect teeth! "
                "Either remove the chamfer/fillet completely, or restrict it only to the circular bore/outer rim via .faces('>Z').edges('%CIRCLE').chamfer(0.3)."
            )
        elif "TypeError" in exec_error and "polarArray" in exec_error:
            guidance = (
                "\n  -> CRITICAL HINT: Workplane.polarArray(radius, startAngle, angle, count) takes 'radius' as its first argument, NOT 'startRadius'! "
                "Use positional arguments: .polarArray(radius, 0, 360, count)."
            )
        elif "AttributeError" in exec_error and "filterBy" in exec_error:
            guidance = (
                "\n  -> CRITICAL HINT: CadQuery Workplane does NOT have a .filterBy() method! "
                "Remove .filterBy(...) completely. Use standard selectors like .faces('>Z').edges('%CIRCLE') or omit unnecessary edge fillets/chamfers."
            )
        elif "Standard_Failure" in exec_error and "suitable edges" in exec_error:
            guidance = (
                "\n  -> CRITICAL HINT: OpenCASCADE cannot fillet/chamfer these edges! "
                "Remove .edges('|Z').fillet(...) or face fillets completely. Cylindrical discs, carrier plates, gears, and drilled through-holes have no linear vertical edges to fillet."
            )
        elif "ParseException" in exec_error and "and" in exec_error:
            guidance = (
                "\n  -> CRITICAL HINT: Invalid CadQuery selector syntax! Never use English words like 'and' or 'or' inside string selectors. "
                "Chain selectors or filter edges with Python list comprehensions."
            )
        elif "TypeError" in exec_error and "indices must be integers" in exec_error:
            guidance = (
                "\n  -> CRITICAL HINT: An index selector passed a float instead of an integer. Use integer indices."
            )

        return f"CadQuery Execution Error:\n{exec_error}{guidance}"


# Backward compatibility alias
RepairAgent = PartRepairAgent
