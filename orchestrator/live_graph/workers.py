"""
Decoupled CAD Agent Worker Registry for LiveGraphExecutor.
Executes individual skill tasks in sandbox environments and returns outcome payloads.
"""

import time
from typing import Dict, Any, Tuple, Optional, Callable, Awaitable
from orchestrator.models import PartSpec, AssemblyGraph
from orchestrator.agents.code_generator_agent import CodeGeneratorAgent
from orchestrator.agents.part_verifier_agent import PartVerifierAgent
from orchestrator.agents.part_repair_agent import PartRepairAgent
from orchestrator.agents.assembly_agent import AssemblyAgent
from orchestrator.agents.assembly_verifier_agent import AssemblyVerifierAgent
from tools.cad_kernel import execute_cadquery_code
from orchestrator.gateway_client import GatewayClient
from orchestrator.live_graph.models import TaskSpec


SkillHandler = Callable[[TaskSpec, Dict[str, Any]], Awaitable[Tuple[bool, Dict[str, Any]]]]


class CADWorkerRegistry:
    """Registry of asynchronous worker handlers mapped to agent roles."""

    def __init__(self, gateway_client: Optional[GatewayClient] = None):
        self.gateway = gateway_client or GatewayClient()
        self.code_gen = CodeGeneratorAgent(self.gateway)
        self.part_verifier = PartVerifierAgent()
        self.part_repair = PartRepairAgent()
        self.assembler = AssemblyAgent(self.gateway)
        self.assembly_verifier = AssemblyVerifierAgent()

    async def execute_task(self, task: TaskSpec, context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Dispatches a TaskSpec to the matching agent worker."""
        role = task.role
        handler = getattr(self, f"_handle_{role}", None)
        if handler:
            return await handler(task, context)
        raise ValueError(f"Unknown task role: {role}")

    async def _handle_code_generator_agent(self, task: TaskSpec, context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Generates CadQuery code and executes it in sandbox."""
        spec_data = task.input.get("spec")
        if isinstance(spec_data, dict):
            spec = PartSpec(**spec_data)
        elif isinstance(spec_data, PartSpec):
            spec = spec_data
        else:
            raise ValueError(f"Missing PartSpec in task input for {task.id}")

        partner_interfaces = task.input.get("partner_interfaces") or context.get("partner_interfaces")
        master_skeleton = task.input.get("master_skeleton") or context.get("master_skeleton")
        previous_code = task.input.get("previous_code")
        repair_prompt = task.input.get("repair_prompt", "")

        t0 = time.time()
        designer_out = await self.code_gen.generate_designer_output(
            spec=spec,
            mates=spec.mates,
            repair_prompt=repair_prompt,
            previous_code=previous_code,
            master_skeleton=master_skeleton,
            partner_interfaces=partner_interfaces
        )

        solid_obj, exec_err = await execute_cadquery_code(designer_out.code)
        latency_ms = (time.time() - t0) * 1000

        if exec_err:
            return False, {
                "code": designer_out.code,
                "error": exec_err,
                "latency_ms": latency_ms,
                "status": "SANDBOX_ERROR"
            }

        return True, {
            "code": designer_out.code,
            "solid": solid_obj,
            "interfaces": designer_out.interfaces,
            "latency_ms": latency_ms,
            "status": "PASS"
        }

    async def _handle_part_verifier_agent(self, task: TaskSpec, context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Runs 6-pillar OpenCascade geometry math verification."""
        solid_obj = task.input.get("solid") or context.get("solid")
        spec_data = task.input.get("spec") or context.get("spec")
        spec = PartSpec(**spec_data) if isinstance(spec_data, dict) else spec_data
        pillars = task.input.get("pillars")

        t0 = time.time()
        verdict = self.part_verifier.verify_part_solid(solid_obj, spec=spec, pillars=pillars)
        latency_ms = (time.time() - t0) * 1000

        return verdict.passed, {
            "passed": verdict.passed,
            "verdict": verdict,
            "diagnostics": [d.model_dump() for d in verdict.diagnostics],
            "solid": solid_obj,
            "bounding_box": verdict.bounding_box,
            "volume": verdict.volume,
            "latency_ms": latency_ms
        }

    async def _handle_part_repair_agent(self, task: TaskSpec, context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Attempts zero-LLM parametric repair or syntax fix."""
        code = task.input.get("code") or context.get("code", "")
        verdict = task.input.get("verdict")
        exec_err = task.input.get("error")

        if exec_err:
            fixed_code, was_fixed, notes = self.part_repair.attempt_syntax_fix(code, exec_err)
            if was_fixed:
                solid_re, err_re = await execute_cadquery_code(fixed_code)
                if not err_re:
                    return True, {"fixed_code": fixed_code, "solid": solid_re, "notes": notes, "fix_type": "syntax"}
            repair_instructions = self.part_repair.generate_syntax_repair_instructions(exec_err, code)
            return False, {"repair_instructions": repair_instructions, "notes": notes}

        if verdict:
            fixed_code, was_fixed, notes = self.part_repair.attempt_parametric_fix(code, verdict)
            if was_fixed:
                solid_re, err_re = await execute_cadquery_code(fixed_code)
                if not err_re:
                    return True, {"fixed_code": fixed_code, "solid": solid_re, "notes": notes, "fix_type": "parametric"}
            repair_instructions = self.part_repair.generate_repair_instructions(verdict)
            return False, {"repair_instructions": repair_instructions, "notes": notes}

        return False, {"error": "Missing verdict or execution error in repair input"}

    async def _handle_assembly_agent(self, task: TaskSpec, context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Mates verified parts into CadQuery assembly using proven InterfacePorts."""
        graph_data = task.input.get("graph") or context.get("graph")
        graph = AssemblyGraph(**graph_data) if isinstance(graph_data, dict) else graph_data
        verified_solids = task.input.get("verified_solids") or context.get("verified_solids", {})
        interfaces = task.input.get("interfaces") or context.get("interfaces", {})
        pos_prompt = task.input.get("positioning_repair_prompt", "")

        t0 = time.time()
        transformed, cq_assy = await self.assembler.assemble_parts(
            graph, verified_solids, interfaces, positioning_repair_prompt=pos_prompt
        )
        latency_ms = (time.time() - t0) * 1000

        return True, {
            "transformed_solids": transformed,
            "cq_assembly": cq_assy,
            "latency_ms": latency_ms
        }

    async def _handle_assembly_verifier_agent(self, task: TaskSpec, context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Runs assembly interference, clearance, and kinematic sweep verification."""
        transformed = task.input.get("transformed_solids") or context.get("transformed_solids", {})
        graph_data = task.input.get("graph") or context.get("graph")
        graph = AssemblyGraph(**graph_data) if isinstance(graph_data, dict) else graph_data
        interfaces = task.input.get("interfaces") or context.get("interfaces", {})

        t0 = time.time()
        verdict = self.assembly_verifier.verify_assembly_solids(
            transformed,
            joints=graph.joints,
            graph=graph,
            interfaces=interfaces
        )
        latency_ms = (time.time() - t0) * 1000

        # Scan for unmated clearance holes to discover fastener requirements
        unmated_holes = []
        for pid, ports in interfaces.items():
            for port_name, port in ports.items():
                p_type = getattr(port, "feature_type", "")
                p_dia = getattr(port, "diameter", None)
                if p_type == "hole" and p_dia and p_dia >= 2.0:
                    unmated_holes.append({
                        "part_id": pid,
                        "port_name": port_name,
                        "diameter": p_dia,
                        "position": getattr(port, "position", (0, 0, 0))
                    })

        return verdict.passed, {
            "passed": verdict.passed,
            "verdict": verdict,
            "diagnostics": [d.model_dump() for d in verdict.diagnostics],
            "interference_volume": verdict.interference_volume,
            "unmated_holes": unmated_holes,
            "latency_ms": latency_ms
        }
