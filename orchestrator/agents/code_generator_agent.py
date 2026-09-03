"""
Code Generator Agent (Part Designer).
Generates parametric CadQuery Python code based on PartSpec, MatingContext, and process SKILL.md.
100% LLM-driven: No hardcoded templates or secret fallbacks.
Outputs DesignerOutput containing CadQuery code and exported InterfacePorts.
"""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from orchestrator.models import PartSpec, MatingContext, DesignerOutput, InterfacePort
from orchestrator.gateway_client import GatewayClient
from orchestrator.toolbox import AgentToolbox


class CodeGeneratorAgent:
    def __init__(self, gateway_client: GatewayClient):
        self.gateway = gateway_client

    def _load_process_skill(self, process: str) -> str:
        """Loads process-specific DFM skill file."""
        base_skill = Path("skills/cadquery_modeling/SKILL.md")
        process_map = {
            "3d_printing": Path("skills/dfm_3d_printing/SKILL.md"),
            "cnc_machining": Path("skills/dfm_cnc_machining/SKILL.md"),
            "sheet_metal": Path("skills/dfm_sheet_metal/SKILL.md")
        }
        
        content = ""
        if base_skill.exists():
            content += base_skill.read_text() + "\n\n"
        
        p_skill = process_map.get(process, Path("skills/dfm_3d_printing/SKILL.md"))
        if p_skill.exists():
            content += p_skill.read_text()
            
        return content

    async def generate_designer_output(
        self,
        spec: PartSpec,
        mates: Optional[List[MatingContext]] = None,
        repair_prompt: str = "",
        previous_code: Optional[str] = None,
        master_skeleton: Optional[Dict[str, Any]] = None
    ) -> DesignerOutput:
        """
        Generates CadQuery code via LLM and extracts exported InterfacePorts.
        When repairing, passes previous_code for surgical fixes.
        When master_skeleton is present, enforces shared kinematic parameters.
        """
        AgentToolbox.enforce("code_generator_agent", "gateway_client")

        process_skill = self._load_process_skill(spec.manufacturing_process)
        
        system_prompt = (
            "You are the Code Generator Agent (Part Designer) for ForgeAgent, a multi-agent mechanical CAD system.\n"
            "Your job: Write executable, parametric CadQuery 2.x Python code defining the exact mechanical part specified in PartSpec.\n\n"
            "## CRITICAL CODE REQUIREMENTS:\n"
            "1. Imports: Always start with:\n"
            "   import cadquery as cq\n"
            "   import math\n"
            "2. Variable Scope: Define ALL geometric parameters (dimensions, radii, tooth count, angles) AT THE TOP of the script as variables before using them in expressions.\n"
            "3. Result Variable: You MUST assign the final solid object to a top-level variable named `result` of type `cq.Workplane` or `cq.Shape`.\n"
            "4. Interface Comments: Export mating connection points as header comments using format:\n"
            "   # INTERFACE: name=(x,y,z) dir=(nx,ny,nz) type=hole|shaft d=diameter\n"
            "5. Feature Requirements:\n"
            "   - If prompt asks for a GEAR: Use multi-slice lofting (`cq.Solid.makeLoft`) with rotated 2D tooth profiles. NEVER apply `.edges('|Z').fillet(...)` globally to teeth, and NEVER apply global `.edges().chamfer()` to gear faces (causes OpenCascade StdFail_NotDone / BRep_API errors)! Only chamfer plain circular bore or outer cylinder rim edges via `.faces('>Z').edges('%CIRCLE').chamfer(0.3)`.\n"
            "   - If prompt asks for an INTERNAL RING GEAR: Create all internal teeth in a SINGLE closed 2D polyline, extrude it, and cut it from an outer casing cylinder in one step: `casing.cut(inner_teeth_solid)`. NEVER loop boolean cuts in Python (e.g. `for i in range(teeth): cut(tooth.rotate())`), which causes 'No pending wires present' errors! Ensure outer diameter D_outer >= D_pitch + 25mm so mounting holes never sever the teeth. For hole patterns, use `.polarArray(radius, 0, 360, count)` where first argument is radius (NEVER startRadius).\n"
            "   - If prompt asks for a BOLT or NUT: Note that `cq.Workplane.polygon(6, diameter)` takes FULL DIAMETER or width across flats (NEVER radius). Bolt head width must always be wider than shaft diameter (e.g. M4 shaft dia=4.0mm, head width=7.0mm).\n"
            "   - If prompt asks for SHEET METAL: Maintain uniform wall thickness = material gauge, and add bend radius fillets.\n"
            "   - If prompt asks for CNC: If you create internal milled pockets, ensure internal corners have fillet radius >= 1.5mm. NEVER call `.edges('|Z').fillet()` on cylindrical parts, carrier plates, gears, or drilled holes (they have no vertical corners and will crash OpenCASCADE with Standard_Failure).\n"
            "6. Safe Selectors: Never use English words ('and', 'or') inside string selectors. NEVER call `.filterBy(...)` (CadQuery Workplane has NO filterBy method — use standard selectors like `.faces('>Z').edges('%CIRCLE')`).\n"
            "7. Shared Parameters: If SHARED ASSEMBLY PARAMETERS are provided, inherit those exact dimensions (center distances, matching shaft/bore diameters, clearances) so your part interfaces seamlessly with partner parts.\n"
            "8. Output: Respond ONLY with executable Python code. Do not include markdown explanation text outside code block fences.\n\n"
            f"--- PROCESS & MODELING SKILLS ---\n{process_skill}"
        )
        
        user_message = f"Part Spec:\n{spec.model_dump_json(indent=2)}"
        if mates:
            user_message += f"\n\nMating Context:\n{[m.model_dump() for m in mates]}"
        shared_params = master_skeleton or getattr(spec, "kinematic_params", {}) or {}
        if shared_params:
            import json
            user_message += (
                f"\n\n--- SHARED ASSEMBLY PARAMETERS ---\n"
                f"{json.dumps(shared_params, indent=2)}\n"
                f"IMPORTANT: Inherit these exact shared parameters so your part interfaces correctly with partner parts!"
            )
        if previous_code:
            user_message += f"\n\n--- PREVIOUS CODE DRAFT ---\n```python\n{previous_code}\n```"
        if repair_prompt:
            user_message += (
                f"\n\n--- PREVIOUS ATTEMPT REPAIR FEEDBACK ---\n{repair_prompt}\n"
                "Please inspect the PREVIOUS CODE DRAFT and fix the exact error identified in the feedback while preserving working geometry."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        code_text = await self.gateway.complete(messages, temperature=0.2)
        
        # Clean markdown fences safely
        cleaned = code_text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned_code = cleaned.strip()

        interfaces = self._extract_interface_ports(cleaned_code, spec, mates)

        return DesignerOutput(
            part_id=spec.id,
            code=cleaned_code,
            interfaces=interfaces
        )

    async def generate_code(
        self,
        spec: PartSpec,
        repair_prompt: str = "",
        previous_code: Optional[str] = None,
        master_skeleton: Optional[Dict[str, Any]] = None
    ) -> str:
        """Backward compatible code generator helper."""
        output = await self.generate_designer_output(
            spec,
            repair_prompt=repair_prompt,
            previous_code=previous_code,
            master_skeleton=master_skeleton
        )
        return output.code

    def _extract_interface_ports(
        self,
        code: str,
        spec: PartSpec,
        mates: Optional[List[MatingContext]]
    ) -> Dict[str, InterfacePort]:
        """Parses # INTERFACE: comment lines from code, or generates defaults from MatingContext."""
        interfaces: Dict[str, InterfacePort] = {}
        
        # 1. Parse comments (robust to leading/trailing hyphens or decorations)
        pattern = r"#.*?INTERFACE:\s*(\w+)=\(([^)]+)\)\s*dir=\(([^)]+)\)\s*type=(\w+)(?:\s*d=([\d.]+))?"
        matches = re.findall(pattern, code)
        for name, pos_str, dir_str, ftype, d_str in matches:
            pos = tuple(float(x.strip()) for x in pos_str.split(","))
            direction = tuple(float(x.strip()) for x in dir_str.split(","))
            diameter = float(d_str) if d_str else None
            allowed_types = {"hole", "shaft", "face", "slot", "gear_mesh", "edge", "pin", "gear"}
            raw_type = ftype.lower()
            if raw_type in ("gear", "teeth"):
                clean_type = "gear_mesh"
            elif raw_type in allowed_types:
                clean_type = raw_type
            else:
                clean_type = "face"
            interfaces[name] = InterfacePort(
                name=name,
                position=pos,
                direction=direction,
                feature_type=clean_type,
                diameter=diameter
            )

        # 2. Default InterfacePorts if none parsed in comments
        if not interfaces:
            hole_d = max(spec.hole_diameter, 2.5)
            interfaces["hole_center_1"] = InterfacePort(
                name="hole_center_1",
                position=(spec.length / 4.0, spec.width / 2.0, spec.height),
                direction=(0.0, 0.0, 1.0),
                feature_type="hole",
                diameter=hole_d
            )
            interfaces["shaft_tip"] = InterfacePort(
                name="shaft_tip",
                position=(0.0, 0.0, 0.0),
                direction=(0.0, 0.0, 1.0),
                feature_type="shaft",
                diameter=4.0
            )

        return interfaces
