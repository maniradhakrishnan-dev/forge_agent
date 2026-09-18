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

        joints_skill = Path("skills/kinematic_joints/SKILL.md")
        if joints_skill.exists():
            content += joints_skill.read_text() + "\n\n"

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

        # Dynamically load skills declared in spec and always resolve through SkillRegistry
        # to ensure base cadquery_modeling and process skills are always included!
        from orchestrator.skills.registry import default_registry
        skills_to_load = default_registry.resolve_skills(
            explicit_skills=list(getattr(spec, "skills", [])),
            prompt=f"{spec.name} {spec.description}",
            part_type=spec.part_type,
            process=spec.manufacturing_process,
            is_compliant=getattr(spec, "is_compliant", False)
        )
        skills_content = default_registry.format_skills_for_prompt(skills_to_load)
        
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
            "6b. Workplane & Thread Safety:\n"
            "   - NO HELIX: CadQuery Workplane has NO `.helix()` method! NEVER call `.helix()` on a Workplane (AttributeError). Fasteners must be modeled as a nominal cylinder diameter with standard lead-in chamfer at `<Z` or cosmetic annular grooves.\n"
            "   - Workplane CenterOption: When creating a workplane on a face of a solid (e.g. `faces('>Z').workplane(...)` or `faces('>X').workplane(...)`), CadQuery by default re-projects the previous plane origin, causing holes to drill along outer edges/corners. ALWAYS specify `centerOption='CenterOfMass'` (e.g. `.faces('>X').workplane(centerOption='CenterOfMass').hole(...)`) so features are centered on that face!\n"
            "   - Workplane Offset & Transforms: NEVER pass a tuple to `.workplane(offset=...)`! `.workplane(offset=float)` takes ONLY a single float scalar distance along the face normal. For 3D translation/positioning, use `.transformed(offset=(x, y, z))`.\n"
            "   - Through Holes on Cubes/Blocks: Calling `.hole(d)` cuts through the entire solid. Drilling `>Z` penetrates both +Z and -Z. Do NOT duplicate drill `<Z`.\n"
            "6c. Pockets, Cavities & Blind Cuts:\n"
            "   - To cut a cavity/pocket, chain directly on the solid: `.faces('>Z').workplane(centerOption='CenterOfMass').rect(L, W).cutBlind(-depth)`.\n"
            "   - NEVER assign an intermediate sketch to `result` (e.g. `result = result.faces('>Z').workplane().rect(...)`). `result` must ALWAYS remain a 3D solid!\n"
            "   - NEVER call `.edges().fillet()` on a 2D sketch (causes 'ValueError: Fillets requires that edges be selected'). Do NOT add unsolicited fillets to internal cut corners when mating with square insert blocks!\n"
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
            "   - If the user asks for a specific hole (e.g. '10mm center hole'), add ONLY that exact hole. Do NOT add surrounding fastener holes unless specifically instructed.\n"
            "10. DIMENSIONAL INTEGRITY & ZERO HALLUCINATION (CRITICAL):\n"
            "   The `PartSpec` JSON is the authoritative, typed contract for this part.\n"
            "   - You MUST declare the exact dimensions from `PartSpec` (`length`, `width`, `height`, `hole_diameter`, `wall_thickness`, and any values in `custom_parameters` or `features`) at the top of the script as variables.\n"
            "   - NEVER invent or alter these core dimensions. The user or architect defines them in JSON so you do not hallucinate.\n"
            "   - When constructing the primary base body (e.g. with `.box()` or `.cylinder()`), you MUST USE these dimension variables (e.g. `.box(length, width, height)`)! Do NOT substitute `wall_thickness` or `plate_thickness` for the overall part `height` when `height` is specified in PartSpec!\n\n"
            f"--- PROCESS & MODELING SKILLS ---\n{skills_content}"
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
                # If surgical diff failed to apply, never send raw diff markers to python exec!
                rep_matches = re.findall(r"=======\s*\n(.*?)\n>>>>>>>", code_text, re.DOTALL)
                if rep_matches and "result =" in rep_matches[0]:
                    cleaned_code = rep_matches[0].strip()
                else:
                    cleaned_code = self._clean_fences(code_text)
                if "<<<<<<< SEARCH" in cleaned_code:
                    cleaned_code = re.sub(r"<<<<<<< SEARCH.*?>>>>>>>", "", cleaned_code, flags=re.DOTALL).strip()
                    if not cleaned_code or "result" not in cleaned_code:
                        cleaned_code = previous_code
        else:
            cleaned_code = self._clean_fences(code_text)

        interfaces = self._extract_interface_ports(cleaned_code, spec, mates)

        # Detect identical no-op iterations to prevent deadlocks
        if previous_code and cleaned_code.strip() == previous_code.strip():
            print(f"  ⚠️ [DesignerAgent] Warning: LLM generated identical code. No changes made.")

        return DesignerOutput(
            part_id=spec.id,
            code=self._normalize_cadquery_code(cleaned_code),
            interfaces=interfaces
        )

    @staticmethod
    def _normalize_cadquery_code(code: str) -> str:
        """
        Normalizes CadQuery code to prevent common CadQuery pitfalls:
        1. When chaining .faces(...).workplane() without centerOption, default to 'CenterOfMass'
           so features/holes are centered on the selected face rather than projected onto edge seams.
        2. In CadQuery, .workplane(offset=...) requires a float scalar (distance along normal).
           If an LLM passes a tuple like offset=(0, 0, z) or offset=(z,), extract the scalar z.
           If a 3D tuple offset=(x, y, z) is passed, transform it to .transformed(offset=(x, y, z)).
        """
        if not code:
            return code
        # Default .faces(...).workplane() to centerOption="CenterOfMass"
        pattern = r"(\.faces\s*\([^)]+\)\s*\.workplane)\s*\(\s*\)"
        code = re.sub(pattern, r'\1(centerOption="CenterOfMass")', code)

        # Fix .workplane(offset=(0, 0, z)) or offset=(0, z) -> offset=z
        code = re.sub(
            r'(\.workplane\s*\([^)]*?)offset=\(\s*(?:0(?:\.0)?\s*,\s*)+(?:0(?:\.0)?\s*,\s*)*([^,\)]+)\s*\)',
            r'\1offset=\2',
            code
        )

        # Fix remaining 3D tuples passed to .workplane(offset=(x, y, z)) -> .transformed(offset=(x, y, z))
        def _replace_3d_workplane_offset(m: re.Match) -> str:
            pre = m.group(1).rstrip(', ')
            x, y, z = m.group(2).strip(), m.group(3).strip(), m.group(4).strip()
            post = m.group(5)
            return f'{pre}{post}.transformed(offset=({x}, {y}, {z}))'

        code = re.sub(
            r'(\.workplane\s*\([^)]*?)offset=\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*([^,\)]+)\s*\)(\s*(\)|,))',
            _replace_3d_workplane_offset,
            code
        )
        return code

    @staticmethod
    def _clean_fences(code_text: str) -> str:
        """Safely cleans markdown code block fences and extracts python code."""
        cleaned = code_text.strip()
        # If there is a ```python ... ``` block in the response, extract it!
        match = re.search(r"```(?:python)?\s*\n(.*?)\n```", cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
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

        modified = previous_code.replace("\r\n", "\n")
        applied_count = 0
        for match in matches:
            search_block = match.group(1).strip("\r\n")
            replace_block = match.group(2).strip("\r\n")
            if search_block in modified:
                modified = modified.replace(search_block, replace_block, 1)
                applied_count += 1
            elif search_block.strip() in modified:
                # Strip leading/trailing whitespace match
                s_strip = search_block.strip()
                idx = modified.find(s_strip)
                if idx != -1:
                    modified = modified[:idx] + replace_block + modified[idx + len(s_strip):]
                    applied_count += 1
            else:
                # Line-by-line whitespace-trimmed fallback
                search_lines = [l.strip() for l in search_block.splitlines()]
                while search_lines and not search_lines[0]:
                    search_lines.pop(0)
                while search_lines and not search_lines[-1]:
                    search_lines.pop()
                if search_lines:
                    mod_lines = modified.splitlines()
                    n_search = len(search_lines)
                    for i in range(len(mod_lines) - n_search + 1):
                        window = [mod_lines[i + k].strip() for k in range(n_search)]
                        if window == search_lines:
                            new_lines = mod_lines[:i] + replace_block.splitlines() + mod_lines[i + n_search:]
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
        
        # 1. Parse comments (robust to leading/trailing hyphens, 'name=', or decorations)
        pattern = r"#.*?INTERFACE:\s*(?:name=)?(\w+)=\(([^)]+)\)\s*dir=\(([^)]+)\)\s*type=([\w_]+)(?:\s*d=([\d.]+))?(?:\s*max_deflection=([\d.]+))?"
        matches = re.findall(pattern, code)
        context = {
            "length": spec.length,
            "width": spec.width,
            "height": spec.height,
            "thickness": getattr(spec, "wall_thickness", 5.0) or 5.0,
        }
        # Extract variables by safely executing parameter assignments up to result / Workplane
        import math
        param_lines = []
        for line in code.splitlines():
            sline = line.strip()
            if sline.startswith("result") or "Workplane" in sline:
                break
            if "=" in sline and not sline.startswith("#"):
                param_lines.append(sline)
        if param_lines:
            try:
                exec("\n".join(param_lines), {"math": math, "__builtins__": {}}, context)
            except Exception:
                # Fallback: simple numeric assignments regex
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
                try:
                    return float(eval(clean, {"math": math, "__builtins__": {}}, context))
                except Exception:
                    return 0.0

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

        # 2. If no INTERFACE comments parsed, do NOT fabricate from PartSpec dimensions.
        # Instead, leave empty — the BRep extractor in post-processing will fill them.
        # This prevents the assembly agent from using incorrect coordinates.

        return interfaces

    @staticmethod
    def extract_interface_ports_from_brep(
        solid_obj: Any,
        spec: 'PartSpec',
        mates: Optional[List['MatingContext']] = None
    ) -> Dict[str, InterfacePort]:
        """
        Extracts real InterfacePorts from BRep solid geometry (ground truth).
        Finds cylindrical faces, computes their centers, and matches them to mates.
        This replaces the old fabrication logic that invented coordinates from PartSpec.
        """
        import cadquery as cq
        ports: Dict[str, InterfacePort] = {}

        shape_obj = solid_obj
        if hasattr(solid_obj, "val"):
            shape_obj = solid_obj.val()
        if shape_obj is None:
            return ports

        # Extract all cylindrical faces with centers and radii
        try:
            wp = cq.Workplane(obj=shape_obj) if not isinstance(solid_obj, cq.Workplane) else solid_obj
            cyl_faces = wp.faces("%CYLINDER").vals()
        except Exception:
            cyl_faces = []

        internal_cyls = []
        external_cyls = []

        for face in cyl_faces:
            try:
                from OCP.BRepAdaptor import BRepAdaptor_Surface
                from OCP.GeomAbs import GeomAbs_Cylinder
                surf = BRepAdaptor_Surface(face.wrapped)
                if surf.GetType() != GeomAbs_Cylinder:
                    continue
                cyl = surf.Cylinder()
                radius = float(cyl.Radius())
                loc = cyl.Location()
                axis = cyl.Axis()
                center = (round(loc.X(), 3), round(loc.Y(), 3), round(loc.Z(), 3))
                direction = (round(axis.Direction().X(), 3), round(axis.Direction().Y(), 3), round(axis.Direction().Z(), 3))

                # Determine internal vs external using normal dot product
                is_internal = False
                try:
                    axis_dir = cq.Vector(axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z())
                    for e in face.edges():
                        if hasattr(e, "geomType") and e.geomType() == "CIRCLE":
                            pt = e.startPoint()
                            p_vec = cq.Vector(pt.x - loc.X(), pt.y - loc.Y(), pt.z - loc.Z())
                            radial = p_vec - axis_dir * p_vec.dot(axis_dir)
                            if radial.Length > 1e-6:
                                n = face.normalAt(pt)
                                is_internal = n.dot(radial.normalized()) < 0
                                break
                except Exception:
                    pass

                entry = {
                    "center": center,
                    "direction": direction,
                    "radius": radius,
                    "diameter": round(radius * 2.0, 3),
                    "is_internal": is_internal,
                    "face": face
                }
                if is_internal:
                    internal_cyls.append(entry)
                else:
                    external_cyls.append(entry)
            except Exception:
                continue

        # Build ports from BRep cylinders
        hole_idx = 0
        shaft_idx = 0

        for cyl_info in internal_cyls:
            hole_idx += 1
            port_name = f"hole_center_{hole_idx}"
            # Compute Z range from bounding box of the face
            try:
                bb = cyl_info["face"].BoundingBox()
                z_top = round(bb.zmax, 3)
            except Exception:
                z_top = cyl_info["center"][2]

            ports[port_name] = InterfacePort(
                name=port_name,
                position=(cyl_info["center"][0], cyl_info["center"][1], z_top),
                direction=cyl_info["direction"],
                feature_type="hole",
                diameter=cyl_info["diameter"],
                from_brep=True
            )

        for cyl_info in external_cyls:
            shaft_idx += 1
            port_name = f"shaft_center_{shaft_idx}"
            try:
                bb = cyl_info["face"].BoundingBox()
                z_top = round(bb.zmax, 3)
            except Exception:
                z_top = cyl_info["center"][2]

            ports[port_name] = InterfacePort(
                name=port_name,
                position=(cyl_info["center"][0], cyl_info["center"][1], z_top),
                direction=cyl_info["direction"],
                feature_type="shaft",
                diameter=cyl_info["diameter"],
                from_brep=True
            )

        # If no cylinders found, extract top/bottom face centers as generic face ports
        if not ports:
            try:
                bb = shape_obj.BoundingBox()
                ports["top_face"] = InterfacePort(
                    name="top_face",
                    position=(round((bb.xmin + bb.xmax) / 2, 3), round((bb.ymin + bb.ymax) / 2, 3), round(bb.zmax, 3)),
                    direction=(0.0, 0.0, 1.0),
                    feature_type="face",
                    from_brep=True
                )
                ports["bottom_face"] = InterfacePort(
                    name="bottom_face",
                    position=(round((bb.xmin + bb.xmax) / 2, 3), round((bb.ymin + bb.ymax) / 2, 3), round(bb.zmin, 3)),
                    direction=(0.0, 0.0, -1.0),
                    feature_type="face",
                    from_brep=True
                )
            except Exception:
                pass

        return ports
