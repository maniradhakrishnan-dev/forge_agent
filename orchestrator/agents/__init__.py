"""
ForgeAgent 8-Agent Module Registry.
"""

from orchestrator.agents.planner_agent import PlannerAgent
from orchestrator.agents.code_generator_agent import CodeGeneratorAgent
from orchestrator.agents.part_verifier_agent import PartVerifierAgent
from orchestrator.agents.part_repair_agent import PartRepairAgent
from orchestrator.agents.assembly_agent import AssemblyAgent
from orchestrator.agents.assembly_verifier_agent import AssemblyVerifierAgent
from orchestrator.agents.assembly_repair_agent import AssemblyRepairAgent
from orchestrator.agents.reporter_agent import ReporterAgent

__all__ = [
    "PlannerAgent",
    "CodeGeneratorAgent",
    "PartVerifierAgent",
    "PartRepairAgent",
    "AssemblyAgent",
    "AssemblyVerifierAgent",
    "AssemblyRepairAgent",
    "ReporterAgent",
]
