"""
Assembly Verifier Agent (Multi-Part Inspector).
Executes ground-truth OpenCascade math checks for interference, fit clearance, and kinematic motion sweep.
"""

from typing import Dict, Any, List, Optional
from orchestrator.models import AssemblyVerdict
from tools.verify_assembly import verify_assembly


class AssemblyVerifierAgent:
    """Multi-part OpenCascade verification agent."""

    def __init__(self, min_clearance: float = 0.1, max_clearance: float = 0.5):
        self.min_clearance = min_clearance
        self.max_clearance = max_clearance

    def verify_assembly_solids(
        self,
        parts: Dict[str, Any],
        joints: Optional[List[Any]] = None,
        graph: Optional[Any] = None,
        interfaces: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> AssemblyVerdict:
        """
        Runs multi-part OpenCascade math checks and returns an AssemblyVerdict.
        """
        return verify_assembly(
            parts,
            joints=joints,
            graph=graph,
            interfaces=interfaces,
            min_clearance=self.min_clearance,
            max_clearance=self.max_clearance
        )


# Backward compatibility alias
AssemblyCriticAgent = AssemblyVerifierAgent
