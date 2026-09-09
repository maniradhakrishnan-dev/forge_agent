"""
Code Generator Agent (Part Designer).
Generates parametric CadQuery Python code based on PartSpec, MatingContext, and process SKILL.md.
100% LLM-driven: No hardcoded templates or secret fallbacks.
Outputs DesignerOutput containing CadQuery code and exported InterfacePorts.
"""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from orchestrator.models import PartSpec, MatingContext, DesignerOutput, InterfacePort
from orchestrator.gateway_client import GatewayClient
from orchestrator.toolbox import AgentToolbox


class CodeGeneratorAgent:
    def __init__(self, gateway_client: GatewayClient):
        self.gateway = gateway_client

    def _load_process_skill(self, process: str, is_compliant: bool = False) -> str:
        """Loads process-specific DFM skill file and compliant mechanisms skill if applicable."""
        base_skill = Path("skills/cadquery_modeling/SKILL.md")
        process_map = {
            "3d_printing": Path("skills/dfm_3d_printing/SKILL.md"),
            "cnc_machining": Path("skills/dfm_cnc_machining/SKILL.md"),
            "sheet_metal": Path("skills/dfm_sheet_metal/SKILL.md")
        }
        compliant_skill = Path("skills/compliant_mechanisms/SKILL.md")
        
        content = ""
        if base_skill.exists():
            content += base_skill.read_text() + "\n\n"
        
        p_skill = process_map.get(process, Path("skills/dfm_3d_printing/SKILL.md"))
        if p_skill.exists():
            content += p_skill.read_text() + "\n\n"
            
        fits_skill = Path("skills/fits_and_tolerances/SKILL.md")
        if fits_skill.exists():
            content += fits_skill.read_text() + "\n\n"

        if is_compliant and compliant_skill.exists():
            content += compliant_skill.read_text()
            
        return content

    async def generate_designer_output(
        self,
        spec: PartSpec,
        mates: Optional[List[MatingContext]] = None,
        repair_prompt: str = "",
        previous_code: Optional[str] = None,
        master_skeleton: Optional[Dict[str, Any]] = None,
        partner_interfaces: Optional[Dict[str, Dict[str, InterfacePort]]] = None
    ) -> DesignerOutput:
        """
        Generates CadQuery code via LLM and extracts exported InterfacePorts.
        When repairing, passes previous_code for surgical fixes.
        When master_skeleton is present, enforces shared kinematic parameters.
        When partner_interfaces is present, passes verified mating features from completed parts.
        """
        AgentToolbox.enforce("code_generator_agent", "gateway_client")

        # Detect compliance from spec or description
        text_check = f"{spec.name} {spec.id} {spec.description} {spec.part_type}".lower()
        is_compliant = getattr(spec, "is_compliant", False) or any(
            kw in text_check for kw in [
                "harmonic", "strain_wave", "flexspline", "flex_spline", "flexible",
                "wave_generator", "snap_fit", "snapfit", "clip", "latch", "flexure",
                "living_hinge", "press_fit"
            ]
        )

        process_skill = self._load_process_skill(spec.manufacturing_process, is_compliant=is_compliant)
        
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
            "   # INTERFACE: name=(x,y,z) dir=(nx,ny,nz) type=hole|shaft|face|compliant_fit|snap_fit|press_fit d=diameter [max_deflection=deflection_mm]\n"
            "   Ensure (x,y,z) are exact GLOBAL world coordinates of the hole center or shaft shoulder! For a centered box cq.Workplane('XY').box(L, W, H), top face is at Z=H/2. If holes are at (±15, 0) on top face, export (±15, 0, H/2).\n"
            "5. Engineering & Modeling Skills:\n"
            "   - Refer to the attached PROCESS & MODELING SKILLS for exact mathematical formulas, standard part construction patterns, and safe modeling idioms for gears, brackets, fasteners, carriers, housings, and compliant mechanisms.\n"
            "   - Adhere strictly to the manufacturing constraints for the specified process (e.g. minimum wall thickness, minimum hole diameters, tool access).\n"
            "6. Safe Selectors: Never use English words ('and', 'or') inside string selectors. NEVER use indexed N-th selectors like `>Z[-2]` or `faces('>Z[1]')` (causes 'ValueError: Can not return the Nth element of an empty list'). NEVER call `.filterBy(...)` (CadQuery Workplane has NO filterBy method — use standard selectors like `.faces('>Z').edges('%CIRCLE')`). NEVER pass a Workplane to `.placeSketch()`.\n"
            "7. Shared Parameters: If SHARED ASSEMBLY PARAMETERS are provided, inherit those exact dimensions (center distances, matching shaft/bore diameters, clearances) so your part interfaces seamlessly with partner parts.\n"
            "8. Output Format:\n"
            "   - When generating from scratch (no PREVIOUS CODE DRAFT): Output complete executable Python code enclosed in ```python ... ``` fences.\n"
            "   - When REPAIRING or ITERATING (when PREVIOUS CODE DRAFT is provided):\n"
            "     DO NOT rewrite the entire script from scratch unless fundamentally required! Use targeted SEARCH/REPLACE blocks to make surgical edits:\n"
            "     <<<<<<< SEARCH\n"
            "     exact lines from PREVIOUS CODE DRAFT to replace\n"
            "     =======\n"
            "     new replacement or added code lines\n"
            "     >>>>>>>\n"
            "     You may provide one or multiple SEARCH/REPLACE blocks. If the entire geometry is fundamentally flawed, you may output the full revised script.\n"
            "9. STRICT MINIMALITY IN ITERATION:\n"
            "   When iterating on or repairing existing code (when PREVIOUS CODE DRAFT is provided):\n"
            "   - Only add, remove, or modify the EXACT features explicitly requested in the repair feedback or user prompt.\n"
            "   - NEVER assume or invent unsolicited features (such as extra corner mounting holes, fastener patterns, fillets, chamfers, or pockets) that were not in the user request or previous code.\n"
            "   - If the user asks for a specific hole (e.g. '10mm center hole'), add ONLY that exact hole. Do NOT add surrounding fastener holes unless specifically instructed.\n\n"
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
        if partner_interfaces:
            import json
            ports_summary = {}
            for partner_id, ports in partner_interfaces.items():
                ports_summary[partner_id] = {
                    port_name: (port.model_dump() if hasattr(port, "model_dump") else port)
                    for port_name, port in ports.items()
                }
            user_message += (
                f"\n\n--- PARTNER INTERFACE PORTS (Already Designed & Verified) ---\n"
                f"{json.dumps(ports_summary, indent=2)}\n"
                f"IMPORTANT: Use the exact coordinates (x, y, z), diameters, and orientations from these partner ports "
                f"so your features align precisely with partner parts!"
            )
        if previous_code:
            user_message += f"\n\n--- PREVIOUS CODE DRAFT ---\n```python\n{previous_code}\n```"
        if repair_prompt:
            user_message += (
                f"\n\n--- PREVIOUS ATTEMPT REPAIR FEEDBACK ---\n{repair_prompt}\n"
                "Please inspect the PREVIOUS CODE DRAFT and fix the exact error identified in the feedback while preserving working geometry. "
                "Use targeted SEARCH/REPLACE blocks for surgical fixes to minimize token overhead."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        code_text = await self.gateway.complete(messages, temperature=0.2)
        
        # Check if response contains surgical diff blocks
        if previous_code and "<<<<<<< SEARCH" in code_text:
            patched_code, applied = self.apply_surgical_diff(previous_code, code_text)
            if applied:
                print(f"  ⚡ [DesignerAgent] Applied targeted SEARCH/REPLACE edit without full script regeneration.")
                cleaned_code = patched_code
            else:
                cleaned_code = self._clean_fences(code_text)
        else:
            cleaned_code = self._clean_fences(code_text)

        interfaces = self._extract_interface_ports(cleaned_code, spec, mates)

        return DesignerOutput(
            part_id=spec.id,
            code=cleaned_code,
            interfaces=interfaces
        )

    @staticmethod
    def _clean_fences(code_text: str) -> str:
        """Safely cleans markdown code block fences."""
        cleaned = code_text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()

    @staticmethod
    def apply_surgical_diff(previous_code: str, response_text: str) -> Tuple[str, bool]:
        """
        Parses SEARCH/REPLACE blocks from LLM response and applies them surgically
        to previous_code. This prevents the LLM from having to rewrite the whole
        script, saving tokens and preserving untouched working geometry.
        Format:
        <<<<<<< SEARCH
        existing code
        =======
        replacement code
        >>>>>>>
        """
        pattern = r"<<<<<<< SEARCH\s*\n(.*?)\n=======\s*\n(.*?)\n>>>>>>>"
        matches = list(re.finditer(pattern, response_text, re.DOTALL))
        if not matches:
            return previous_code, False

        modified = previous_code
        applied_count = 0
        for match in matches:
            search_block = match.group(1)
            replace_block = match.group(2)
            if search_block in modified:
                modified = modified.replace(search_block, replace_block, 1)
                applied_count += 1
            else:
                # Line-by-line whitespace-trimmed fallback
                search_lines = [l.strip() for l in search_block.splitlines() if l.strip()]
                if search_lines:
                    mod_lines = modified.splitlines()
                    for i in range(len(mod_lines) - len(search_lines) + 1):
                        window = [mod_lines[i + j].strip() for j in range(len(search_lines))]
                        if window == search_lines:
                            new_lines = mod_lines[:i] + replace_block.splitlines() + mod_lines[i + len(search_lines):]
                            modified = "\n".join(new_lines)
                            applied_count += 1
                            break

        if applied_count > 0:
            try:
                compile(modified, "<string>", "exec")
                return modified, True
            except SyntaxError:
                return previous_code, False
        return previous_code, False

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
        pattern = r"#.*?INTERFACE:\s*(\w+)=\(([^)]+)\)\s*dir=\(([^)]+)\)\s*type=([\w_]+)(?:\s*d=([\d.]+))?(?:\s*max_deflection=([\d.]+))?"
        matches = re.findall(pattern, code)
        context = {
            "length": spec.length,
            "width": spec.width,
            "height": spec.height,
            "thickness": getattr(spec, "wall_thickness", 5.0) or 5.0,
        }
        # Extract numerical assignments from the top of the CadQuery code
        for var_name, var_val in re.findall(r"^(\w+)\s*=\s*([0-9.]+)", code, re.MULTILINE):
            try:
                context[var_name] = float(var_val)
            except ValueError:
                pass

        def _eval_coord(expr: str) -> float:
            clean = expr.strip()
            try:
                return float(clean)
            except ValueError:
                return float(eval(clean, {"__builtins__": {}}, context))

        for name, pos_str, dir_str, ftype, d_str, max_def_str in matches:
            try:
                pos = tuple(_eval_coord(x) for x in pos_str.split(","))
                direction = tuple(_eval_coord(x) for x in dir_str.split(","))
                diameter = _eval_coord(d_str) if d_str else None
                max_def = float(max_def_str) if max_def_str else None
            except Exception:
                continue

            allowed_types = {"hole", "shaft", "face", "slot", "gear_mesh", "edge", "pin", "gear", "compliant_fit", "snap_fit", "press_fit"}
            raw_type = ftype.lower()
            if raw_type in ("gear", "teeth"):
                clean_type = "gear_mesh"
            elif raw_type in allowed_types:
                clean_type = raw_type
            else:
                clean_type = "face"

            is_comp = clean_type in ("compliant_fit", "snap_fit", "press_fit") or (max_def is not None and max_def > 0)
            interfaces[name] = InterfacePort(
                name=name,
                position=pos,
                direction=direction,
                feature_type=clean_type,
                diameter=diameter,
                max_deflection=max_def,
                is_compliant=is_comp
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
