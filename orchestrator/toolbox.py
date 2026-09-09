"""
Agent Guardrail Toolbox Enforcement for ForgeAgent.
Isolates tools and skills per agent role to prevent tool leakage or unauthorized execution.
"""

from typing import Dict, Set


class AgentToolboxError(PermissionError):
    """Raised when an agent attempts to execute an unapproved tool."""
    pass


class AgentToolbox:
    """Runtime guardrail enforcing tool permission boundaries per agent role."""

    ALLOWED_TOOLS: Dict[str, Set[str]] = {
        "planner_agent": {"gateway_client"},
        "code_generator_agent": {"gateway_client", "skills_cadquery", "skills_assembly", "code_editor"},
        "part_verifier_agent": {"verify_single_part"},  # Read-only OpenCascade math
        "part_repair_agent": {"code_reader", "code_editor", "cad_kernel_sandbox", "verify_single_part"},
        "assembly_agent": {"cad_kernel_assembly"},
        "assembly_verifier_agent": {"verify_assembly"},  # Read-only OpenCascade assembly math
        "assembly_repair_agent": {"graph_editor", "code_editor"},
        "reporter_agent": {"cad_kernel_export", "run_logger"},
    }

    @classmethod
    def can_use(cls, agent_role: str, tool_name: str) -> bool:
        """Returns True if agent_role is permitted to execute tool_name."""
        allowed = cls.ALLOWED_TOOLS.get(agent_role, set())
        return tool_name in allowed

    @classmethod
    def enforce(cls, agent_role: str, tool_name: str) -> None:
        """Raises AgentToolboxError if agent_role attempts to execute an unapproved tool."""
        if not cls.can_use(agent_role, tool_name):
            raise AgentToolboxError(
                f"Security Guardrail Violation: Agent '{agent_role}' is not authorized to execute tool '{tool_name}'. "
                f"Allowed tools for '{agent_role}': {sorted(list(cls.ALLOWED_TOOLS.get(agent_role, set())))}"
            )
