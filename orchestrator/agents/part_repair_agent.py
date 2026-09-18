"""
Part Repair Agent.
Attempts zero-LLM parametric and syntax fixes on CadQuery scripts.
Falls back to formatting diagnostic text for Designer Agent escalation only when
direct code edits cannot resolve the failure.

Tools: code_reader, code_editor, cad_kernel_sandbox, verify_single_part
LLM: NO — this agent never calls the LLM.
"""

import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, Union
from orchestrator.models import VerificationVerdict, PartSpec


# ---------------------------------------------------------------------------
# Variable names commonly used in CadQuery scripts, grouped by diagnostic rule
# ---------------------------------------------------------------------------

_WALL_THICKNESS_VARS = {
    "wall_thickness", "wall_t", "t_wall", "wall", "min_wall",
    "shell_thickness", "casing_wall", "housing_wall",
}

_HOLE_DIAMETER_VARS = {
    "hole_dia", "hole_diameter", "bore_dia", "bore_diameter",
    "mounting_hole_dia", "bolt_hole_dia", "pin_hole_dia",
    "center_hole_dia", "shaft_hole_dia",
}

_OUTER_DIMENSION_VARS = {
    # Length / width / height
    "length", "width", "height", "depth",
    # Diameters & radii
    "outer_dia", "outer_diameter", "od", "outer_radius", "outer_r",
    "pitch_dia", "pitch_diameter", "pitch_d",
    "ring_outer_dia", "housing_dia", "casing_dia",
    "total_length", "total_width", "total_height",
    "body_length", "body_width", "body_height",
}


class PartRepairAgent:
    """
    Single-part repair agent with zero-LLM code editing tools.

    Primary path:  attempt_parametric_fix() / attempt_syntax_fix()
                   → directly patches the CadQuery script and returns fixed code.

    Escalation:    generate_repair_instructions() / generate_syntax_repair_instructions()
                   → formats diagnostic text for Designer Agent (LLM) when direct fix fails.
    """

    # ------------------------------------------------------------------
    # 1. PRIMARY PATH — Zero-LLM Code Editing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_variables(code: str) -> Dict[str, Tuple[float, int, str]]:
        """
        Parses top-level numeric variable assignments from a CadQuery script.

        Returns dict of {var_name: (value, line_number, full_line_text)}.
        Only captures simple assignments like `wall_thickness = 1.5` or
        `outer_dia = 2 * 25.0`.  Skips lines inside functions, classes, or
        multi-line expressions.
        """
        variables: Dict[str, Tuple[float, int, str]] = {}
        for line_no, line in enumerate(code.splitlines(), start=1):
            stripped = line.strip()
            # Skip comments, blank lines, indented lines (inside functions/classes)
            if not stripped or stripped.startswith("#") or line[0] in (" ", "\t"):
                continue
            m = re.match(r"^([a-zA-Z_]\w*)\s*=\s*(.+)$", stripped)
            if not m:
                continue
            var_name = m.group(1)
            expr = m.group(2).strip()
            # Skip string assignments, function calls (except simple math)
            if expr.startswith(("'", '"', "[", "{", "cq.", "cadquery.", "Path(")):
                continue
            try:
                val = float(eval(expr, {"__builtins__": {}, "math": __import__("math")}))
                variables[var_name] = (val, line_no, line)
            except Exception:
                continue
        return variables

    @staticmethod
    def _replace_variable(code: str, var_name: str, old_line: str, new_value: float) -> str:
        """
        Replaces a single variable assignment line in the code.
        Preserves comments on the same line.
        """
        # Build replacement line preserving original indentation and inline comments
        indent = old_line[:len(old_line) - len(old_line.lstrip())]
        comment = ""
        comment_match = re.search(r"\s+#\s*.+$", old_line)
        if comment_match:
            comment = f"  # was {old_line.split('=')[1].strip().split('#')[0].strip()}"

        # Format value: use integer if whole number, else 1 decimal minimum
        if new_value == int(new_value) and new_value < 10000:
            val_str = f"{int(new_value)}.0"
        else:
            val_str = f"{new_value:.4f}".rstrip("0").rstrip(".")
            if "." not in val_str:
                val_str += ".0"

        new_line = f"{indent}{var_name} = {val_str}{comment}"
        return code.replace(old_line, new_line, 1)

    def repair_spec_contract(
        self,
        spec: PartSpec,
        verdict: VerificationVerdict,
        spec_file_path: Optional[Union[str, Path]] = None
    ) -> Tuple[PartSpec, bool, List[str]]:
        """
        Repairs the typed PartSpec contract based on verification diagnostics.
        Guarantees that JSON contract on disk matches physical requirements
        before any code edits or Designer LLM calls occur.
        """
        repaired = spec.model_copy(deep=True)
        changes: List[str] = []

        failed = [d for d in verdict.diagnostics if d.status == "FAIL"]

        # If the geometry failed basic physical manifold checks (PHYS-01), the spec contract
        # itself is not at fault — the shape is degenerate (e.g. 0-volume, 2D wire, self-intersecting).
        if any(d.rule_id in ("PHYS-01", "PHYS-02") for d in failed):
            return spec, False, ["Skipping spec contract repair because part geometry failed physical manifold checks (PHYS-01/PHYS-02)."]

        for diag in failed:
            if diag.rule_id == "STRUCT-01":

                # Increase minimum wall thickness
                new_wall = round(max(repaired.wall_thickness, diag.required + 0.5), 1)
                if abs(new_wall - repaired.wall_thickness) > 1e-3:
                    old_w = repaired.wall_thickness
                    repaired.wall_thickness = new_wall
                    changes.append(f"[STRUCT-01] Repaired spec.wall_thickness: {old_w}mm -> {new_wall}mm (required >={diag.required}mm)")

            elif diag.rule_id in ("DFM-3D-02", "DFM-CNC-02", "DFM-SM-02"):
                # Increase minimum hole diameter
                new_hole = round(max(repaired.hole_diameter, diag.required + 0.2), 1)
                if abs(new_hole - repaired.hole_diameter) > 1e-3:
                    old_h = repaired.hole_diameter
                    repaired.hole_diameter = new_hole
                    changes.append(f"[{diag.rule_id}] Repaired spec.hole_diameter: {old_h}mm -> {new_hole}mm (required >={diag.required}mm)")

            elif diag.rule_id == "FAST-01":
                # Ensure ISO 273 clearance hole
                if repaired.hole_diameter < 4.3:
                    old_h = repaired.hole_diameter
                    repaired.hole_diameter = 4.3
                    changes.append(f"[FAST-01] Repaired spec.hole_diameter: {old_h}mm -> 4.3mm (ISO 273 clearance)")

            # NOTE: We NEVER repair the contract for SPEC-01 (bounding box compliance) or CRIT-01. 
            # The PartSpec length/width/height are the ground truth targets. If the LLM generates 
            # a part that violates them, we must fix the CAD code, NOT corrupt the spec contract.

        # Re-sync axisymmetric parts (outside the diagnostic loop)
        if repaired.geometry_form in ("stepped_shaft", "shaft", "bolt", "pin") or repaired.part_type in ("shaft", "pin", "bolt"):
            crit = repaired.critical_dimensions or {}
            od = crit.get("outer_diameter") or crit.get("shaft_diameter")
            if od is not None and od > 0:
                repaired.width = float(od)
                repaired.height = float(od)

        was_repaired = len(changes) > 0
        if was_repaired and spec_file_path:
            try:
                repaired.to_json_file(spec_file_path)
            except Exception as e:
                changes.append(f"Warning saving repaired spec.json: {e}")

        return repaired, was_repaired, changes

    def attempt_spec_sync_edit(
        self,
        code: str,
        spec: PartSpec
    ) -> Tuple[str, bool, List[str]]:
        """
        Level 1 Repair: Deterministically syncs CadQuery script variables to match
        the repaired PartSpec typed contract. Zero LLM tokens.
        """
        variables = self._parse_variables(code)
        if not variables:
            return code, False, ["No parseable variables to sync."]

        fixed_code = code
        sync_notes: List[str] = []

        # 1. Sync wall thickness
        if spec.wall_thickness > 0:
            for vname in _WALL_THICKNESS_VARS:
                if vname in variables:
                    old_val, line_no, old_line = variables[vname]
                    if abs(old_val - spec.wall_thickness) > 1e-2:
                        fixed_code = self._replace_variable(fixed_code, vname, old_line, spec.wall_thickness)
                        sync_notes.append(f"Synced {vname}: {old_val} -> {spec.wall_thickness}mm from spec.wall_thickness")
                        variables = self._parse_variables(fixed_code)
                        break

        # 2. Sync hole diameter
        if spec.hole_diameter > 0:
            for vname in _HOLE_DIAMETER_VARS:
                if vname in variables:
                    old_val, line_no, old_line = variables[vname]
                    if abs(old_val - spec.hole_diameter) > 1e-2:
                        fixed_code = self._replace_variable(fixed_code, vname, old_line, spec.hole_diameter)
                        sync_notes.append(f"Synced {vname}: {old_val} -> {spec.hole_diameter}mm from spec.hole_diameter")
                        variables = self._parse_variables(fixed_code)
                        break

        # 3. Sync dimensions (length, width, height)
        dim_mappings = {
            "length": spec.length,
            "width": spec.width,
            "height": spec.height,
            "total_length": spec.length,
            "total_width": spec.width,
            "total_height": spec.height,
            "body_length": spec.length,
            "body_width": spec.width,
            "body_height": spec.height,
        }
        for dname, target_val in dim_mappings.items():
            if dname in variables and target_val > 0:
                old_val, line_no, old_line = variables[dname]
                if abs(old_val - target_val) > 1e-2:
                    fixed_code = self._replace_variable(fixed_code, dname, old_line, target_val)
                    sync_notes.append(f"Synced {dname}: {old_val} -> {target_val}mm from spec.{dname.split('_')[-1]}")
                    variables = self._parse_variables(fixed_code)

        # 4. Sync custom parameters
        for param_name, param_val in spec.custom_parameters.items():
            try:
                numeric_val = float(param_val)
            except (ValueError, TypeError):
                continue
            if param_name in variables and numeric_val > 0:
                old_val, line_no, old_line = variables[param_name]
                if abs(old_val - numeric_val) > 1e-2:
                    fixed_code = self._replace_variable(fixed_code, param_name, old_line, numeric_val)
                    sync_notes.append(f"Synced custom parameter {param_name}: {old_val} -> {numeric_val} from spec.custom_parameters")
                    variables = self._parse_variables(fixed_code)

        return fixed_code, len(sync_notes) > 0, sync_notes

    def attempt_parametric_fix(
        self,
        code: str,
        verdict: VerificationVerdict,
        spec: Optional[PartSpec] = None,
        spec_file_path: Optional[Union[str, Path]] = None
    ) -> Tuple[Optional[str], bool, List[str]]:
        """
        Attempts to fix DFM diagnostic failures by directly editing variable
        assignments in the CadQuery script, maintaining strict JSON contract sync. Zero LLM tokens.

        Args:
            code: The CadQuery Python script that failed verification.
            verdict: The VerificationVerdict with failed diagnostics.
            spec: Optional PartSpec contract to repair first.
            spec_file_path: Optional path to save repaired spec.json.

        Returns:
            (fixed_code or None, was_fixed, list of fix descriptions)
            If was_fixed is False, the caller should escalate to Designer Agent.
        """
        failed = [d for d in verdict.diagnostics if d.status == "FAIL"]
        if not failed:
            return code, True, []

        fixed_code = code
        fixes_applied: List[str] = []

        # 0. JSON-First Contract Repair: Repair PartSpec first if provided
        repaired_spec = spec
        if spec is not None:
            repaired_spec, was_repaired, spec_notes = self.repair_spec_contract(spec, verdict, spec_file_path)
            if was_repaired:
                fixes_applied.extend(spec_notes)
                # Level 1: Deterministic spec-to-code sync edit
                synced_code, was_synced, sync_notes = self.attempt_spec_sync_edit(fixed_code, repaired_spec)
                if was_synced:
                    fixed_code = synced_code
                    fixes_applied.extend(sync_notes)

        # Geometry Pre-Fix: Check for Workplane("XZ") revolve axis error causing PHYS-01 zero volume
        if any(d.rule_id == "PHYS-01" for d in failed) and "XZ" in fixed_code and "revolve" in fixed_code:
            rev_pattern = r"\.revolve\s*\(\s*(?:360(?:\.0)?)?\s*,\s*\(\s*0\s*,\s*0\s*,\s*0\s*\)\s*,\s*\(\s*0\s*,\s*0\s*,\s*1\s*\)\s*\)"
            new_code = re.sub(rev_pattern, ".revolve()", fixed_code)
            if new_code != fixed_code:
                fixed_code = new_code
                fixes_applied.append("[PHYS-01] Fixed .revolve() rotation axis on XZ workplane (switched to global Z axis)")
                failed = [d for d in failed if d.rule_id not in ("PHYS-01", "PHYS-02")]
                if not failed:
                    return fixed_code, True, fixes_applied

        # Check if ALL remaining failures are parametrically fixable
        fixable_rules = {"SPEC-01", "STRUCT-01", "DFM-3D-02", "DFM-CNC-02", "DFM-SM-02"}
        unfixable = [d for d in failed if d.rule_id not in fixable_rules]
        if unfixable:
            # Topology / manifold / self-intersection issues cannot be fixed parametrically
            return None, False, [
                f"Cannot fix {d.rule_id} ({d.message}) parametrically — requires Designer (LLM)."
                for d in unfixable
            ]

        variables = self._parse_variables(fixed_code)
        if not variables:
            if fixes_applied:
                return fixed_code, True, fixes_applied
            return None, False, ["No parseable top-level variables found in script."]

        for diag in failed:
            # Dynamically refresh variables to avoid stale lines/offsets if earlier repairs modified the code
            variables = self._parse_variables(fixed_code)
            if not variables:
                break
            fixed_this = False

            if diag.rule_id == "STRUCT-01":
                # Wall thickness too thin — find and increase wall variable
                target_val = round(diag.required + 0.5, 1)  # Add 0.5mm safety margin
                for vname in _WALL_THICKNESS_VARS:
                    if vname in variables:
                        old_val, line_no, old_line = variables[vname]
                        if old_val < diag.required:
                            fixed_code = self._replace_variable(fixed_code, vname, old_line, target_val)
                            fixes_applied.append(
                                f"[STRUCT-01] {vname}: {old_val} → {target_val}mm (was {diag.measured}mm, required ≥{diag.required}mm)"
                            )
                            fixed_this = True
                            break

            elif diag.rule_id in ("DFM-3D-02", "DFM-CNC-02", "DFM-SM-02"):
                # Hole diameter too small — find and increase hole variable
                target_val = round(diag.required + 0.2, 1)  # Small margin
                for vname in _HOLE_DIAMETER_VARS:
                    if vname in variables:
                        old_val, line_no, old_line = variables[vname]
                        if old_val < diag.required:
                            fixed_code = self._replace_variable(fixed_code, vname, old_line, target_val)
                            fixes_applied.append(
                                f"[{diag.rule_id}] {vname}: {old_val} → {target_val}mm (required ≥{diag.required}mm)"
                            )
                            fixed_this = True
                            break

            elif diag.rule_id == "SPEC-01":
                # Bounding box dimension mismatch
                if diag.measured > diag.required:
                    # Part too large — scale down the dominant outer dimension
                    scale_factor = diag.required / diag.measured
                    best_var = None
                    best_dist = float("inf")
                    for vname in _OUTER_DIMENSION_VARS:
                        if vname in variables:
                            old_val, line_no, old_line = variables[vname]
                            dist = abs(old_val - diag.measured)
                            if dist < best_dist and old_val > 1.0:
                                best_dist = dist
                                best_var = (vname, old_val, line_no, old_line)
                    if best_var and best_dist < diag.measured * 0.5:
                        vname, old_val, line_no, old_line = best_var
                        if abs(old_val - diag.required) / max(diag.required, 0.1) < 0.10:
                            return None, False, [
                                f"Variable '{vname}' is already defined as {old_val}mm (matching target {diag.required}mm), "
                                f"but physical bounding box is {diag.measured}mm (exceeding target due to added outer features). "
                                f"Check whether attached features (knuckles, flanges, bosses) extend beyond the required envelope."
                            ]
                        new_val = round(old_val * scale_factor, 2)
                        fixed_code = self._replace_variable(fixed_code, vname, old_line, new_val)
                        fixes_applied.append(
                            f"[SPEC-01] {vname}: {old_val} → {new_val}mm (bounding box {diag.measured}mm > target {diag.required}mm)"
                        )
                        fixed_this = True
                else:
                    # Part too small — scale up
                    scale_factor = diag.required / max(diag.measured, 0.1)
                    best_var = None
                    best_dist = float("inf")
                    for vname in _OUTER_DIMENSION_VARS:
                        if vname in variables:
                            old_val, line_no, old_line = variables[vname]
                            dist = abs(old_val - diag.measured)
                            if dist < best_dist and old_val > 0.5:
                                best_dist = dist
                                best_var = (vname, old_val, line_no, old_line)
                    if best_var and best_dist < diag.required * 0.5:
                        vname, old_val, line_no, old_line = best_var
                        if abs(old_val - diag.required) / max(diag.required, 0.1) < 0.10:
                            return None, False, [
                                f"Variable '{vname}' is already defined as {old_val}mm (matching target {diag.required}mm), "
                                f"but physical bounding box is only {diag.measured}mm. Ensure '{vname}' is actually used "
                                f"in primary geometry construction (e.g. .box(L, W, H)) rather than being omitted or hardcoded."
                            ]
                        new_val = round(old_val * scale_factor, 2)
                        fixed_code = self._replace_variable(fixed_code, vname, old_line, new_val)
                        fixes_applied.append(
                            f"[SPEC-01] {vname}: {old_val} → {new_val}mm (bounding box {diag.measured}mm < target {diag.required}mm)"
                        )
                        fixed_this = True

            if not fixed_this and not fixes_applied:
                # Could not find a matching variable for this diagnostic
                return None, False, [
                    f"Cannot map {diag.rule_id} ({diag.parameter}: measured={diag.measured}, required={diag.required}) "
                    f"to any known variable in the script. Escalating to Designer."
                ] + fixes_applied

        if fixes_applied:
            return fixed_code, True, fixes_applied
        return None, False, ["No fixes could be applied."]

    def attempt_syntax_fix(
        self,
        code: str,
        exec_error: str
    ) -> Tuple[Optional[str], bool, List[str]]:
        """
        Attempts to fix CadQuery execution errors by pattern-matched code edits.
        Zero LLM tokens.

        Args:
            code: The CadQuery Python script that failed execution.
            exec_error: The traceback/error message from cad_kernel sandbox.

        Returns:
            (fixed_code or None, was_fixed, list of fix descriptions)
        """
        fixed_code = code
        fixes: List[str] = []

        # Fix 1: Remove .fillet() / .chamfer() calls that crash OpenCASCADE or CadQuery
        fillet_keywords = (
            "Standard_Failure", "StdFail_NotDone", "BRep_API", "suitable edges",
            "Standard_ConstructionError", "ChFi3d_Builder", "edges be selected",
            "requires that edges be selected", "Cannot compute fillet", "Standard_DomainError"
        )
        if any(kw in exec_error for kw in fillet_keywords):
            # Remove .fillet(...) and .chamfer(...) method calls along with any preceding .edges(...) or .faces(...) selector
            pattern = r"(?:\.(?:edges|faces)\s*\([^)]*\))?\s*\.(?:fillet|chamfer)\s*\([^)]*\)"
            new_code = re.sub(pattern, "", fixed_code)
            if new_code != fixed_code:
                fixed_code = new_code
                fixes.append("Removed .fillet()/.chamfer() calls causing OpenCASCADE/CadQuery BRep failure")

        # Fix 2: Remove .filterBy(...) calls — CadQuery doesn't have this method
        if "filterBy" in exec_error and ".filterBy(" in fixed_code:
            code_cur = fixed_code
            idx = code_cur.find(".filterBy(")
            while idx != -1:
                start_paren = idx + len(".filterBy")
                depth = 0
                end_paren = start_paren
                for i in range(start_paren, len(code_cur)):
                    if code_cur[i] == "(":
                        depth += 1
                    elif code_cur[i] == ")":
                        depth -= 1
                        if depth == 0:
                            end_paren = i + 1
                            break
                code_cur = code_cur[:idx] + code_cur[end_paren:]
                idx = code_cur.find(".filterBy(")
            if code_cur != fixed_code:
                fixed_code = code_cur
                fixes.append("Removed .filterBy() calls (not a CadQuery method)")


        # Fix 3: Remove indexed selectors like >Z[-2], faces(">Z[1]")
        if "Nth element" in exec_error or "empty list" in exec_error:
            # Remove indexed face/edge selectors
            pattern = r"(\.(?:faces|edges)\s*\(['\"])[^'\"]*\[-?\d+\][^'\"]*(['\"])"
            new_code = re.sub(pattern, r"\1>Z\2", fixed_code)
            if new_code != fixed_code:
                fixed_code = new_code
                fixes.append("Replaced indexed selectors (>Z[-2]) with simple >Z selector")

        # Fix 4: Remove .placeSketch() usage
        if "placeSketch" in exec_error:
            lines = fixed_code.splitlines()
            new_lines = [l for l in lines if ".placeSketch(" not in l]
            if len(new_lines) < len(lines):
                fixed_code = "\n".join(new_lines)
                fixes.append("Removed .placeSketch() calls (requires cq.Sketch, not Workplane)")

        # Fix 5: Remove invalid .helix() calls (Workplane has no helix method)
        if "object has no attribute 'helix'" in exec_error:
            lines = fixed_code.splitlines()
            new_lines = []
            skip_var = None
            for l in lines:
                if ".helix(" in l:
                    m = re.match(r"\s*([a-zA-Z0-9_]+)\s*=", l)
                    if m:
                        skip_var = m.group(1)
                    continue
                if skip_var and skip_var in l:
                    m2 = re.match(r"\s*([a-zA-Z0-9_]+)\s*=", l)
                    if m2:
                        skip_var = m2.group(1)
                    continue
                if any(x in l for x in [".cut(threads)", ".union(threads)", "threads.val()", "threads ="]):
                    continue
                new_lines.append(l)
            if len(new_lines) < len(lines):
                fixed_code = "\n".join(new_lines)
                fixes.append("Removed invalid .helix() and dependent sweep/cut operations (Workplane has no helix method)")

        # Fix 6: Replace failed .loft() / .sweep() with simple box/extrusion fallback
        loft_keywords = ("Nothing to loft", "More than one wire or face is required", "loft", "BRepOffsetAPI_MakePipeShell")
        if any(kw in exec_error for kw in loft_keywords):
            # Extract top-level dimension variables from the script to preserve intended size
            variables = self._parse_variables(code)
            length_val = next((v[0] for k, v in variables.items() if "length" in k.lower() or k == "l"), 100.0)
            width_val = next((v[0] for k, v in variables.items() if "width" in k.lower() or k == "w"), 50.0)
            thickness_val = next((v[0] for k, v in variables.items() if "thickness" in k.lower() or "height" in k.lower() or k == "t" or k == "h"), 5.0)

            # Build a simple box-based replacement that preserves variable declarations
            var_lines = []
            other_lines = []
            for line in code.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("import "):
                    var_lines.append(line)
                elif re.match(r"^[a-zA-Z_]\w*\s*=\s*[^=]", stripped) and "cq." not in stripped and "result" not in stripped.split("=")[0]:
                    var_lines.append(line)
                # Skip everything else (the broken geometry chain)

            fallback_code = "\n".join(var_lines) + "\n\n"
            fallback_code += "# Fallback: simple box extrusion (loft/sweep failed)\n"
            fallback_code += f"result = cq.Workplane('XY').box(length, width, thickness)\n"

            fixed_code = fallback_code
            fixes.append("Replaced failed .loft()/.sweep() chain with simple box extrusion fallback")

        # Fix 7: Remove or fix invalid .split(keep=...) calls
        if "unexpected keyword argument 'keep'" in exec_error or ".split(keep=" in fixed_code:
            new_code = re.sub(r"\.split\s*\(\s*keep\s*=[^)]*\)", "", fixed_code)
            if new_code != fixed_code:
                fixed_code = new_code
                fixes.append("Removed invalid .split(keep=...) call (CadQuery split only accepts keepTop/keepBottom)")

        if fixes:
            # Strictly validate that the syntax-patched code compiles AND produces a valid 3D solid
            from tools.cad_kernel import _sync_execute_cadquery
            res_obj, exec_err_fix = _sync_execute_cadquery(fixed_code)
            if not exec_err_fix and res_obj is not None:
                return fixed_code, True, fixes
            else:
                return None, False, [f"Syntax fix attempted ({'; '.join(fixes)}) but patched code failed solid execution: {exec_err_fix}"]

        return None, False, [f"No pattern-matched syntax fix available for this error."]


    def attempt_user_parametric_edit(
        self,
        code: str,
        user_prompt: str
    ) -> Tuple[Optional[str], bool, str]:
        """
        Parses user prompt for parametric modifications and directly edits
        CadQuery script variables without calling LLMs. Zero LLM tokens.

        Examples:
        - "increase hole diameter to 6mm"
        - "change length to 50mm"
        - "set wall thickness to 3mm"
        - "increase bolt length to 30mm"
        - "height = 25"
        """
        variables = self._parse_variables(code)
        if not variables:
            return None, False, "No numeric variables found in code"

        prompt_lower = user_prompt.lower()

        # Target variable category mapping
        candidates = []
        if any(kw in prompt_lower for kw in ("hole", "bore", "drill")):
            candidates.extend(k for k in variables if any(h in k.lower() for h in ("hole", "bore", "inner_dia")))
        if any(kw in prompt_lower for kw in ("wall", "thickness")):
            candidates.extend(k for k in variables if any(w in k.lower() for w in ("wall", "thickness", "thick", "gauge")))
        if any(kw in prompt_lower for kw in ("length", "len", "long")):
            candidates.extend(k for k in variables if "length" in k.lower() or "len" in k.lower())
        if any(kw in prompt_lower for kw in ("width", "wide")):
            candidates.extend(k for k in variables if "width" in k.lower())
        if any(kw in prompt_lower for kw in ("height", "tall", "depth")):
            candidates.extend(k for k in variables if any(h in k.lower() for h in ("height", "tall", "depth")))
        if any(kw in prompt_lower for kw in ("outer", "diameter", "radius", "od")):
            candidates.extend(k for k in variables if any(d in k.lower() for d in ("outer", "dia", "radius", "od")))

        # Check for explicit variable names mentioned directly in prompt
        for var_name in variables:
            if var_name.lower() in prompt_lower and var_name not in candidates:
                candidates.insert(0, var_name)

        if not candidates:
            return None, False, "No matching parameter found in user prompt"

        # Extract numeric target value from prompt (e.g., "to 6mm", "= 6", "to 30", "set to 3")
        val_match = re.search(r"(?:to|=|is|set to)\s*([0-9.]+)", prompt_lower)
        if not val_match:
            num_matches = re.findall(r"([0-9.]+)\s*(?:mm)?", prompt_lower)
            if num_matches:
                new_val = float(num_matches[-1])
            else:
                return None, False, "No target numeric value found in prompt"
        else:
            new_val = float(val_match.group(1))

        best_var = candidates[0]
        old_val, line_no, old_line = variables[best_var]
        new_code = self._replace_variable(code, best_var, old_line, new_val)
        return new_code, True, f"Parametrically updated '{best_var}' from {old_val} to {new_val}mm"


    # ------------------------------------------------------------------
    # 2. ESCALATION PATH — Text Formatters for Designer Agent (LLM)
    # ------------------------------------------------------------------

    def generate_repair_instructions(self, verdict: VerificationVerdict) -> str:
        """
        Formats failed DFM diagnostics into an actionable text repair prompt
        for the Designer Agent (LLM).  This is the ESCALATION path — only called
        when attempt_parametric_fix() returns was_fixed=False.
        """
        failed_diagnostics = [d for d in verdict.diagnostics if d.status == "FAIL"]
        if not failed_diagnostics:
            return ""

        # Deduplicate MATE-01/CRIT-01 failures with identical measured/required values
        # (e.g. 3 identical wing mate failures are really 1 problem)
        seen_signatures = set()
        deduped = []
        for diag in failed_diagnostics:
            if diag.rule_id in ("MATE-01", "CRIT-01"):
                sig = (diag.rule_id, round(diag.measured, 1), round(diag.required, 1))
                if sig in seen_signatures:
                    continue
                seen_signatures.add(sig)
            deduped.append(diag)
        failed_diagnostics = deduped

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
                if "disconnected solid bodies" in diag.message:
                    instructions.append(
                        f"  -> ACTION: The part consists of {int(diag.measured)} disconnected solid bodies! "
                        f"Either:\n"
                        f"  1. A feature (boss, lug, rib, ring) unioned with .union() floats with an air gap because of coordinate offsets! NOTE: cq.Workplane('XY').box(L, W, H) is centered at Z=0 (Z extends from -H/2 to +H/2, so the top face is at Z=+H/2, NOT H). If you put features at offset=H, they float in mid-air! Either attach directly using result.faces('>Z').workplane() or use box(L, W, H, centered=(True, True, False)).\n"
                        f"  2. Or holes/cuts sliced completely through the solid, severing it into multiple pieces. Maintain continuous material."
                    )
                else:
                    instructions.append(
                        f"  -> ACTION: OpenCascade reports invalid non-manifold solid or self-intersecting faces. "
                        f"Ensure Boolean cuts and unions have clean overlap and do not create zero-thickness edges or tangential self-intersections."
                    )
            elif diag.rule_id == "PHYS-02":
                instructions.append(
                    f"  -> ACTION: B-Rep topology analyzer found self-intersecting wires or corrupt faces. "
                    f"Verify that polygon coordinates do not self-cross and that closed wire profiles are non-self-intersecting."
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
        """
        Formats CadQuery execution traceback with targeted debugging guidance
        for the Designer Agent (LLM).  This is the ESCALATION path — only called
        when attempt_syntax_fix() returns was_fixed=False.
        """
        guidance = ""
        if ("Standard_Failure" in exec_error or "StdFail_NotDone" in exec_error or "BRep_API" in exec_error) and ("fillet" in exec_error or "chamfer" in exec_error):
            guidance = (
                "\n  -> CRITICAL HINT: OpenCascade fillet/chamfer failed (BRep_API / StdFail_NotDone). "
                "Holes or teeth on the selected face prevent filleting! "
                "REMOVE the chamfer/fillet completely (fillets are purely aesthetic and not required for functional verification), "
                "OR apply the fillet to the base solid BEFORE drilling any holes or cutting teeth."
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
        elif "ValueError" in exec_error and "Nth element" in exec_error:
            guidance = (
                "\n  -> CRITICAL HINT: Invalid indexed selector (e.g. '>Z[-2]' or 'faces(\">Z[1]\")')! "
                "CadQuery cannot select the N-th element of an empty list. NEVER use indexed selectors like [-1], [-2], etc. "
                "Simplify your geometry: remove complex indexed pocket selectors and place cuts/holes directly on .faces('>Z').workplane(). "
                "For carrier plates, use a clean circular plate with polarArray holes without complex internal pockets."
            )
        elif "AttributeError" in exec_error and ("copy" in exec_error or "placeSketch" in exec_error):
            guidance = (
                "\n  -> CRITICAL HINT: .placeSketch() requires a cq.Sketch object, not a cq.Workplane! "
                "Avoid .placeSketch() entirely — use standard .faces('>Z').workplane().rect(...).cutBlind(...) or .circle(...).extrude(...) instead."
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
        elif "Cannot find a solid on the stack" in exec_error or "findSolid" in exec_error:
            guidance = (
                "\n  -> CRITICAL HINT: The Workplane stack lost the 3D solid context before calling .fillet() or .chamfer()! "
                "Ensure you call .fillet() on the solid object (e.g. `result = result.edges(...).fillet(...)`) "
                "rather than chaining immediately after a 2D sketch or cut. If adding a slot, pocket, or cutout, avoid filleting its edges completely."
            )

        return f"CadQuery Execution Error:\n{exec_error}{guidance}"


# Backward compatibility alias
RepairAgent = PartRepairAgent
