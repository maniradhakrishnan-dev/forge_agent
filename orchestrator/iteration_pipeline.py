"""
Human-in-the-Loop Part & Assembly Iteration Engine (ForgeAgent).
Enables users to iteratively modify existing parts or assemblies:
User Feedback -> Targeted Code Update -> Sandbox -> DFM Verifier -> (Assembly Verifier) -> Export
"""

import os
import re
import time
import uuid
import asyncio
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from orchestrator.gateway_client import GatewayClient
from orchestrator.models import (
    AssemblyGraph,
    PartSpec,
    DesignerOutput,
    VerificationVerdict,
    AssemblyVerdict,
)
from orchestrator.run_logger import RunLogger
from orchestrator.agents.planner_agent import PlannerAgent
from orchestrator.agents.code_generator_agent import CodeGeneratorAgent
from orchestrator.agents.part_verifier_agent import PartVerifierAgent
from orchestrator.agents.part_repair_agent import PartRepairAgent
from orchestrator.agents.assembly_agent import AssemblyAgent
from orchestrator.agents.assembly_verifier_agent import AssemblyVerifierAgent
from orchestrator.agents.assembly_repair_agent import AssemblyRepairAgent
from orchestrator.agents.constraint_validator import ConstraintValidator
from orchestrator.part_pipeline import run_part_pipeline
from tools.cad_kernel import execute_cadquery_code, export_cad_artifacts


def resolve_iteration_target(target_path: str) -> Tuple[str, str, Dict[str, Any]]:
    """
    Analyzes target_path to determine if it is a single part or an assembly.
    Supports .json (spec.json, assembly_graph.json), .py scripts, and directories.
    Returns: (target_type: 'part'|'assembly', resolved_path, metadata)
    """
    p = Path(target_path)
    if not p.exists():
        raise FileNotFoundError(f"Target path does not exist: {target_path}")

    # 1. Direct JSON target (part spec or assembly graph)
    if p.is_file() and p.suffix == ".json":
        if p.name == "assembly_graph.json":
            return "assembly", str(p.parent), {"graph_file": str(p)}
        try:
            import json
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and ("parts" in data and "joints" in data):
                return "assembly", str(p.parent), {"graph_file": str(p)}
        except Exception:
            pass
        return "part", str(p), {"spec_file": str(p)}

    # 2. Direct Python script target
    if p.is_file() and p.suffix == ".py":
        return "part", str(p), {"code_file": str(p)}

    # 3. Directory target
    if p.is_dir():
        # Check for explicit assembly_graph.json
        if (p / "assembly_graph.json").exists():
            return "assembly", str(p), {"graph_file": str(p / "assembly_graph.json")}

        # Check for assembly markers: multiple part directories or assembly STEP files
        part_dirs = [
            d for d in p.iterdir()
            if d.is_dir() and ((d / "spec.json").exists() or any(f.suffix == ".py" for f in d.iterdir()))
        ]
        assy_steps = list(p.glob("*assembly*.step"))

        if len(part_dirs) >= 2 or len(assy_steps) > 0:
            return "assembly", str(p), {"part_dirs": [str(d) for d in part_dirs]}

        # Check for single part in root of directory (spec.json or py file)
        if (p / "spec.json").exists():
            return "part", str(p / "spec.json"), {"spec_file": str(p / "spec.json")}

        py_files = [f for f in p.glob("*.py") if not f.name.startswith("test_") and not f.name.startswith("run_")]
        if py_files:
            return "part", str(py_files[0]), {"code_file": str(py_files[0])}

        # Fallback to single part inside a child directory
        if part_dirs:
            child_spec = Path(part_dirs[0]) / "spec.json"
            if child_spec.exists():
                return "part", str(child_spec), {"spec_file": str(child_spec)}
            child_py = list(Path(part_dirs[0]).glob("*.py"))
            if child_py:
                return "part", str(child_py[0]), {"code_file": str(child_py[0])}

    raise ValueError(f"Could not identify a valid CadQuery part or assembly in: {target_path}")


async def run_part_iteration(
    base_code_or_file: str,
    prompt: str,
    output_dir: str = "artifacts/part_iteration",
    max_retries: int = 3,
    gateway_client: Optional[GatewayClient] = None,
    run_id: Optional[str] = None
) -> Tuple[bool, PartSpec, Optional[VerificationVerdict], str, Dict[str, str]]:
    """
    Iterates on a single mechanical part:
    Loads previous code/spec.json -> Prompts Designer with surgical feedback -> Sandbox -> DFM Verifier -> Export.
    """
    run_id = run_id or str(uuid.uuid4())[:8]
    logger = RunLogger(run_id=run_id, output_dir=output_dir)
    gw = gateway_client or GatewayClient()
    planner = PlannerAgent(gw)

    existing_code = ""
    existing_spec: Optional[PartSpec] = None

    target_p = Path(base_code_or_file) if os.path.exists(base_code_or_file) else None
    if target_p and target_p.is_file():
        if target_p.suffix == ".json":
            try:
                existing_spec = PartSpec.from_json_file(target_p)
                print(f"  📄 [Iteration] Loaded existing PartSpec from JSON: {target_p}")
            except Exception as e:
                print(f"  ⚠️  Could not parse PartSpec from JSON: {e}")
            # Look for companion .py code in same directory
            py_candidates = [f for f in target_p.parent.glob("*.py") if not f.name.startswith("test_") and not f.name.startswith("run_")]
            if py_candidates:
                existing_code = py_candidates[0].read_text(encoding="utf-8")
        elif target_p.suffix == ".py":
            existing_code = target_p.read_text(encoding="utf-8")
            # Look for companion spec.json in same directory
            spec_candidate = target_p.parent / "spec.json"
            if spec_candidate.exists():
                try:
                    existing_spec = PartSpec.from_json_file(spec_candidate)
                except Exception:
                    pass
    elif target_p and target_p.is_dir():
        spec_candidate = target_p / "spec.json"
        if spec_candidate.exists():
            try:
                existing_spec = PartSpec.from_json_file(spec_candidate)
            except Exception:
                pass
        py_candidates = [f for f in target_p.glob("*.py") if not f.name.startswith("test_") and not f.name.startswith("run_")]
        if py_candidates:
            existing_code = py_candidates[0].read_text(encoding="utf-8")
    else:
        existing_code = base_code_or_file

    # 0. Attempt zero-LLM parametric edit first (Zero tokens) if we have existing code and a prompt
    if existing_code and prompt and prompt.strip().lower() not in ["rebuild", "regenerate", "update", "from spec", "from json"]:
        repair_agent = PartRepairAgent()
        p_code, p_fixed, p_note = repair_agent.attempt_user_parametric_edit(existing_code, prompt)
        if p_fixed and p_code:
            print(f"\n[Iteration] ⚡ Attempting zero-LLM parametric modification: {p_note}...")
            solid_obj, exec_err = await execute_cadquery_code(p_code)
            if not exec_err and solid_obj:
                spec_to_verify = existing_spec or PartSpec(id="iterated_part", name="iterated_part")
                verifier = PartVerifierAgent(min_wall_thickness=spec_to_verify.wall_thickness, min_hole_diameter=spec_to_verify.hole_diameter)
                verdict = verifier.verify_part_solid(solid_obj, spec=spec_to_verify)
                if verdict.passed:
                    print(f"  ✅ [Zero-LLM Iteration] Verification passed with 0 LLM tokens!")
                    artifacts = await export_cad_artifacts(
                        solid_obj, output_dir, spec_to_verify.name,
                        code=p_code, spec=spec_to_verify
                    )
                    logger.log_step(agent="part_repair_agent", status="PASS", latency_ms=0.0)
                    logger.generate_summary_markdown(f"Iterate: {prompt}", True)
                    return True, spec_to_verify, verdict, p_code, artifacts
            print(f"  ⚠️  Parametric edit did not satisfy verifier; escalating to Planner & Designer LLMs.")

    # Measure base solid envelope to preserve proportions if prompt doesn't specify dimension changes
    base_len, base_wid, base_hgt = 40.0, 30.0, 10.0
    if existing_code:
        try:
            base_solid, _ = await execute_cadquery_code(existing_code)
            if base_solid:
                bb = base_solid.BoundingBox()
                base_len, base_wid, base_hgt = max(bb.xlen, 1.0), max(bb.ylen, 1.0), max(bb.zlen, 1.0)
        except Exception:
            pass

    # If existing_spec is available and prompt is empty or just generic rebuild, honor existing_spec directly
    is_direct_spec_replay = existing_spec is not None and (
        not prompt or prompt.strip().lower() in ["rebuild", "regenerate", "update", "from spec", "from json", ""]
    )

    if is_direct_spec_replay:
        print(f"\n[Iteration] 📋 Directly honoring edited PartSpec JSON contract ({existing_spec.name}) — 0 planner hallucination!")
        part_spec = existing_spec
        # Check if we can sync the edited spec into existing code directly (Zero LLM tokens)
        if existing_code:
            repair_agent = PartRepairAgent()
            p_code, p_synced, p_notes = repair_agent.attempt_spec_sync_edit(existing_code, existing_spec)
            if p_synced and p_code:
                print(f"  ⚡ [Zero-LLM Spec Sync] Synchronized code variables: {', '.join(p_notes)}")
                solid_obj, exec_err = await execute_cadquery_code(p_code)
                if not exec_err and solid_obj:
                    verifier = PartVerifierAgent(min_wall_thickness=part_spec.wall_thickness, min_hole_diameter=part_spec.hole_diameter)
                    verdict = verifier.verify_part_solid(solid_obj, spec=part_spec)
                    if verdict.passed:
                        print(f"  ✅ [Zero-LLM Spec Sync] Verification passed with 0 LLM tokens!")
                        artifacts = await export_cad_artifacts(
                            solid_obj, output_dir, part_spec.name,
                            code=p_code, spec=part_spec
                        )
                        logger.log_step(agent="part_repair_agent", status="PASS", latency_ms=0.0)
                        logger.generate_summary_markdown(f"Iterate from JSON Spec: {part_spec.name}", True)
                        return True, part_spec, verdict, p_code, artifacts
                existing_code = p_code
    else:
        print(f"\n[Iteration] 🧠 Planning modifications for part from user request: '{prompt}'...")
        t0 = time.time()
        part_spec = await planner.plan_iteration_part(existing_code or (existing_spec.model_dump_json() if existing_spec else ""), prompt)
        part_spec.is_single_part = True

        # Preserve existing_spec properties if planner returned defaults
        if existing_spec:
            if not part_spec.custom_parameters and existing_spec.custom_parameters:
                part_spec.custom_parameters = existing_spec.custom_parameters
            if not part_spec.features and existing_spec.features:
                part_spec.features = existing_spec.features
            if part_spec.name == "iterated_part" and existing_spec.name:
                part_spec.name = existing_spec.name
                part_spec.id = existing_spec.id

        # Preserve base part dimensions if planner left default placeholders (40x30) without explicit prompt constraints
        explicit = getattr(part_spec, "explicit_constraints", {}) or {}
        if "length" not in explicit and (part_spec.length == 40.0 or part_spec.length <= 0):
            part_spec.length = round(base_len, 1)
        if "width" not in explicit and (part_spec.width == 30.0 or part_spec.width <= 0):
            part_spec.width = round(base_wid, 1)
        if "height" not in explicit and (part_spec.height == 10.0 or part_spec.height <= 0):
            part_spec.height = round(base_hgt, 1)

        logger.log_step(
            agent="planner_agent",
            part_id=part_spec.id,
            status="PASS",
            latency_ms=(time.time() - t0) * 1000
        )

    print(f"[Iteration] ⚙️  Applying surgical modifications to '{part_spec.name}' while preserving existing geometry...")
    mod_prompt = (
        f"USER ITERATION REQUEST: {prompt or 'Update geometry to strictly match PartSpec JSON'}\n"
        f"CRITICAL INSTRUCTIONS:\n"
        f"1. STRICT CONTRACT CONFORMANCE: All dimensions and features in PartSpec JSON are immutable requirements.\n"
        f"2. STRICT MINIMALITY: Implement ONLY the exact modification requested above. Do NOT invent or add unsolicited mounting holes, fasteners, fillets, chamfers, or pockets.\n"
        f"3. SURGICAL PRESERVATION: Preserve all existing working geometry, parameters, and interface features from PREVIOUS CODE DRAFT unless specifically asked to change them."
    )

    passed, designer_out, verdict, solid_obj, artifacts = await run_part_pipeline(
        spec=part_spec,
        output_dir=output_dir,
        max_retries=max_retries,
        gateway_client=gw,
        run_logger=logger,
        initial_code=existing_code if existing_code else None,
        user_modification_prompt=mod_prompt
    )

    code = designer_out.code if designer_out else existing_code
    logger.generate_summary_markdown(f"Iterate: {prompt}", passed)
    return passed, part_spec, verdict, code, artifacts


async def run_assembly_iteration(
    base_run_dir: str,
    prompt: str,
    target_part_id: Optional[str] = None,
    output_dir: str = "artifacts/assembly_iteration",
    max_part_retries: int = 5,
    max_assembly_retries: int = 3,
    gateway_client: Optional[GatewayClient] = None,
    run_id: Optional[str] = None
) -> Tuple[bool, AssemblyGraph, AssemblyVerdict, Dict[str, Any], Dict[str, Any]]:
    """
    Iterates on a multi-part assembly:
    Loads previous parts -> Modifies targeted parts -> Re-mates assembly -> Verifies interference == 0 -> Export.
    """
    run_id = run_id or str(uuid.uuid4())[:8]
    logger = RunLogger(run_id=run_id, output_dir=output_dir)
    gw = gateway_client or GatewayClient()
    planner = PlannerAgent(gw)
    assembler = AssemblyAgent()
    verifier = AssemblyVerifierAgent()
    repair_router = AssemblyRepairAgent()

    base_p = Path(base_run_dir)

    # 1. Discover existing part scripts and original design prompt
    part_codes: Dict[str, str] = {}
    part_specs: Dict[str, PartSpec] = {}

    original_prompt = ""
    summary_file = base_p / "run_summary.md"
    if summary_file.exists():
        m = re.search(r"\*\*Prompt:\*\*\s*(.+)", summary_file.read_text())
        if m:
            original_prompt = m.group(1).strip()

    # Scan part subdirectories
    for d in sorted(base_p.iterdir()):
        if d.is_dir():
            py_files = [f for f in d.glob("*.py") if not f.name.startswith("test_")]
            if py_files:
                pid = d.name
                code_txt = py_files[0].read_text()
                part_codes[pid] = code_txt
                part_codes[py_files[0].stem] = code_txt

    if not part_codes:
        # Check root py files
        for f in base_p.glob("*.py"):
            if not f.name.startswith("test_") and not f.name.startswith("run_"):
                pid = f.stem
                part_codes[pid] = f.read_text()

    # Check for existing AssemblyGraph JSON and per-part spec.json
    disk_graph_file = base_p / "assembly_graph.json" if (base_p / "assembly_graph.json").exists() else None
    if not disk_graph_file and (base_p.parent / "assembly_graph.json").exists():
        disk_graph_file = base_p.parent / "assembly_graph.json"

    disk_graph = None
    if disk_graph_file:
        try:
            disk_graph = AssemblyGraph.from_json_file(disk_graph_file)
            print(f"  📄 [Assembly Iteration] Loaded existing AssemblyGraph from JSON: {disk_graph_file}")
            for p in disk_graph.parts:
                p_spec_file = base_p / p.id / "spec.json"
                if p_spec_file.exists():
                    try:
                        part_specs[p.id] = PartSpec.from_json_file(p_spec_file)
                        print(f"  📄 [Assembly Iteration] Loaded part spec for '{p.id}' from {p_spec_file}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"  ⚠️  Could not parse AssemblyGraph from JSON: {e}")

    # Reconstruct or plan updated AssemblyGraph with ConstraintValidator verification
    planning_query = f"Original Design: {original_prompt}\nModification: {prompt}" if original_prompt else prompt
    print(f"\n[Assembly Iteration] 🧠 Planning iteration on assembly with {len(part_codes)} parts {[p for p in part_codes.keys()]}...")
    max_planning_retries = 3
    initial_graph = None
    validation_errors = None

    if disk_graph and (not prompt or prompt.strip().lower() in ["rebuild", "regenerate", "update", "from spec", "from json", ""]):
        print(f"  📋 Directly using edited AssemblyGraph from disk — 0 planner hallucination!")
        initial_graph = disk_graph
    else:
        for plan_iter in range(1, max_planning_retries + 1):
            initial_graph = await planner.plan_assembly(planning_query, validation_errors=validation_errors)
            val_res = ConstraintValidator.validate(initial_graph)
            if val_res.valid:
                logger.log_step(agent="constraint_validator", iteration=plan_iter, status="PASS")
                break
            print(f"  ⚠️  [ConstraintValidator] Iteration graph consistency check failed (Attempt {plan_iter}/{max_planning_retries}):")
            for err in val_res.errors:
                print(f"     • {err}")
            logger.log_step(agent="constraint_validator", iteration=plan_iter, status="FAIL", diagnostics=val_res.errors)
            validation_errors = val_res.errors

    # Determine affected parts
    if target_part_id:
        # Resolve target_part_id (e.g. 'part_2' might correspond to second part in graph)
        resolved_target = target_part_id
        if target_part_id.startswith("part_") and target_part_id[5:].isdigit():
            idx = int(target_part_id[5:]) - 1
            if 0 <= idx < len(initial_graph.parts):
                resolved_target = initial_graph.parts[idx].id

        affected_parts = [resolved_target, target_part_id]
        part_instructions = {resolved_target: prompt, target_part_id: prompt}
    else:
        try:
            impact = await planner.plan_iteration_assembly(initial_graph, prompt, part_codes)
            affected_parts = impact.get("affected_parts", [p.id for p in initial_graph.parts[:1]])
            part_instructions = impact.get("part_instructions", {p: prompt for p in affected_parts})
            updated_params = impact.get("updated_shared_parameters")
            if updated_params and isinstance(updated_params, dict):
                print(f"  🔄 [Assembly Iteration] Updating shared assembly parameters: {updated_params}")
                initial_graph.shared_parameters.update(updated_params)
        except Exception:
            affected_parts = [initial_graph.parts[0].id]
            part_instructions = {initial_graph.parts[0].id: prompt}

    print(f"  🎯 Targeted parts for modification: {affected_parts}")

    # 2. Update affected parts concurrently and reuse unaffected parts
    verified_solids: Dict[str, Any] = {}
    interfaces: Dict[str, Dict[str, Any]] = {}
    part_artifacts: Dict[str, Dict[str, str]] = {}

    sem = asyncio.Semaphore(2)

    async def _process_part(idx: int, part_spec: PartSpec):
        async with sem:
            pid = part_spec.id
            alt_id = f"part_{idx+1}"
            code_key = next((k for k in part_codes.keys() if k == pid or k == alt_id or part_spec.name in k or k in part_spec.name), None)
            existing_code = part_codes.get(code_key or pid)
            is_affected = any(target in (pid, alt_id, part_spec.name, code_key) for target in affected_parts)

            if is_affected or pid in affected_parts or (code_key and code_key in affected_parts):
                instr = part_instructions.get(pid) or part_instructions.get(code_key) or prompt
                # Try zero-LLM parametric edit first if existing code is available
                if existing_code:
                    repair_agent = PartRepairAgent()
                    p_code, p_fixed, p_note = repair_agent.attempt_user_parametric_edit(existing_code, instr)
                    if p_fixed and p_code:
                        solid, err = await execute_cadquery_code(p_code)
                        if not err and solid:
                            p_verifier = PartVerifierAgent(min_wall_thickness=part_spec.wall_thickness, min_hole_diameter=part_spec.hole_diameter)
                            verdict = p_verifier.verify_part_solid(solid, spec=part_spec)
                            if verdict.passed:
                                print(f"  ⚡ [Zero-LLM Iteration] {pid}: {p_note} (0 LLM tokens)")
                                code_gen = CodeGeneratorAgent(gw)
                                d_out = DesignerOutput(
                                    part_id=pid,
                                    code=p_code,
                                    interfaces=code_gen._extract_interface_ports(p_code, part_spec, part_spec.mates)
                                )
                                arts = await export_cad_artifacts(solid, output_dir, part_spec.name, code=p_code)
                                return True, pid, solid, d_out.interfaces, arts, p_code

                # Surgical modification on affected part via Designer LLM
                mod_prompt = (
                    f"USER ITERATION REQUEST: {instr}\n"
                    f"Please update the PREVIOUS CODE DRAFT to implement this modification while preserving all working features and interfaces."
                )
                passed, d_out, p_verdict, solid, arts = await run_part_pipeline(
                    spec=part_spec,
                    output_dir=output_dir,
                    max_retries=max_part_retries,
                    gateway_client=gw,
                    run_logger=logger,
                    master_skeleton=initial_graph.shared_parameters,
                    initial_code=existing_code,
                    user_modification_prompt=mod_prompt
                )
                if not passed or not d_out:
                    return False, pid, None, {}, {}, ""

                return True, pid, solid, d_out.interfaces, arts, d_out.code

            elif existing_code:
                # Re-execute existing verified code
                solid, err = await execute_cadquery_code(existing_code)
                if err:
                    passed, d_out, _, solid, arts = await run_part_pipeline(
                        spec=part_spec,
                        output_dir=output_dir,
                        max_retries=max_part_retries,
                        gateway_client=gw,
                        run_logger=logger
                    )
                    if not passed or not d_out:
                        return False, pid, None, {}, {}, ""
                    return True, pid, solid, d_out.interfaces, arts, d_out.code
                else:
                    code_gen = CodeGeneratorAgent(gw)
                    d_out = DesignerOutput(
                        part_id=pid,
                        code=existing_code,
                        interfaces=code_gen._extract_interface_ports(existing_code, part_spec, part_spec.mates)
                    )
                    arts = await export_cad_artifacts(solid, output_dir, part_spec.name, code=existing_code)
                    return True, pid, solid, d_out.interfaces, arts, existing_code
            else:
                # Missing part: generate
                passed, d_out, _, solid, arts = await run_part_pipeline(
                    spec=part_spec,
                    output_dir=output_dir,
                    max_retries=max_part_retries,
                    gateway_client=gw,
                    run_logger=logger,
                    master_skeleton=initial_graph.shared_parameters
                )
                if not passed or not d_out:
                    return False, pid, None, {}, {}, ""
                return True, pid, solid, d_out.interfaces, arts, d_out.code

    part_tasks = [_process_part(idx, p) for idx, p in enumerate(initial_graph.parts)]
    part_results = await asyncio.gather(*part_tasks)

    for ok, pid, solid, p_interfaces, arts, final_code in part_results:
        if not ok or solid is None:
            logger.log_step(agent="iteration_pipeline", status="FAIL", diagnostics=[f"Iteration failed on '{pid}'"])
            return False, initial_graph, AssemblyVerdict(passed=False), {}, {}
        verified_solids[pid] = solid
        interfaces[pid] = p_interfaces
        part_artifacts[pid] = arts
        if final_code:
            part_codes[pid] = final_code

    # 3. Mating and Assembly Verification Loop
    print(f"\n[Assembly Iteration] 🧩 Re-mating assembly with updated parts...")
    final_verdict = None
    transformed_solids = {}
    top_assembly = None
    pos_repair_prompt = ""

    for assy_iter in range(1, max_assembly_retries + 1):
        transformed_solids, top_assembly = await assembler.assemble_parts(
            graph=initial_graph,
            solids=verified_solids,
            interfaces=interfaces,
            positioning_repair_prompt=pos_repair_prompt
        )

        final_verdict = verifier.verify_assembly_solids(
            transformed_solids,
            joints=initial_graph.joints,
            graph=initial_graph,
            interfaces=interfaces
        )
        ver_status = "PASS" if final_verdict.passed else "FAIL"
        logger.log_step(
            agent="assembly_verifier_agent",
            iteration=assy_iter,
            status=ver_status,
            diagnostics=[d.model_dump() for d in final_verdict.diagnostics]
        )

        if final_verdict.passed:
            print(f"  ✅ [AssemblyVerifier] Interference=0.0mm³, Fit Clearance & Kinematics PASSED!")
            break
        else:
            print(f"  ❌ [AssemblyVerifier] Assembly verification failed (Iter {assy_iter}/{max_assembly_retries}):")
            for d in final_verdict.diagnostics:
                if d.status == "FAIL":
                    print(f"     • {d.message}")
            if assy_iter == max_assembly_retries:
                break

            # Route repair with 3-way triage (graph_patch, tolerance_patch, geometry)
            instruction = repair_router.diagnose_repair(
                final_verdict, initial_graph, retry_count=assy_iter, part_codes=part_codes
            )
            logger.log_step(agent="assembly_repair_agent", iteration=assy_iter, status="FAIL", diagnostics=[instruction.model_dump()])

            if instruction.fault_type == "graph_patch":
                print(f"  🔧 [AssemblyRepair] Direct graph patch applied (zero LLM): {instruction.prompt}")
                if instruction.patched_graph:
                    initial_graph = instruction.patched_graph
            elif instruction.fault_type == "tolerance_patch":
                print(f"  🔧 [AssemblyRepair] Direct tolerance patch applied (zero LLM): {instruction.prompt}")
                if instruction.patched_graph:
                    initial_graph = instruction.patched_graph
                if instruction.patched_code:
                    for pid, fixed_code in instruction.patched_code.items():
                        solid, err = await execute_cadquery_code(fixed_code)
                        if not err and solid:
                            verified_solids[pid] = solid
                            part_codes[pid] = fixed_code
            elif instruction.fault_type == "positioning":
                pos_repair_prompt = instruction.prompt
                print(f"  🔧 [AssemblyRepair] Positioning repair queued: {instruction.prompt}")
            elif instruction.target_agent in ("part_repair_agent", "code_generator_agent"):
                target_p = next((p for p in initial_graph.parts if p.id == instruction.target_part_id), initial_graph.parts[0])
                prev_c = part_codes.get(target_p.id, "")
                _, d_out, _, s_obj, _ = await run_part_pipeline(
                    spec=target_p,
                    output_dir=output_dir,
                    max_retries=1,
                    gateway_client=gw,
                    run_logger=logger,
                    master_skeleton=initial_graph.shared_parameters,
                    initial_code=prev_c,
                    user_modification_prompt=instruction.prompt
                )
                if d_out and s_obj:
                    verified_solids[target_p.id] = s_obj
                    interfaces[target_p.id] = d_out.interfaces
                    part_codes[target_p.id] = d_out.code

    # 4. Export assembly artifacts
    passed = bool(final_verdict and final_verdict.passed)
    try:
        initial_graph.to_json_file(f"{output_dir}/assembly_graph.json")
    except Exception:
        pass

    if top_assembly and passed:
        try:
            assembler = AssemblyAgent()
            assy_code = assembler.generate_assembly_script(initial_graph, output_dir)
            assy_step = f"{output_dir}/{initial_graph.name}_assembly.step"
            assy_stl = f"{output_dir}/{initial_graph.name}_assembly.stl"
            assy_py = f"{output_dir}/assembly.py"
            top_assembly.save(assy_step, "STEP")
            top_assembly.save(assy_stl, "STL")
            part_artifacts["assembly"] = {"step": assy_step, "stl": assy_stl, "py": assy_py, "spec": f"{output_dir}/assembly_graph.json"}
        except Exception as e:
            print(f"  ⚠️  Assembly export warning: {e}")

    logger.generate_summary_markdown(f"Iterate Assembly: {prompt}", passed)
    return passed, initial_graph, final_verdict or AssemblyVerdict(passed=False), transformed_solids, part_artifacts


async def run_iteration_pipeline(
    iterate_path: str,
    user_feedback: str,
    target_part_id: Optional[str] = None,
    output_dir: str = "artifacts/iteration",
    gateway_client: Optional[GatewayClient] = None,
    run_logger: Optional[RunLogger] = None,
    run_id: Optional[str] = None
) -> Tuple[bool, Any, Any, Any, Dict[str, Any]]:
    """
    Unified entry point for human-in-the-loop iteration on parts or assemblies.
    Resolves target type and routes to run_part_iteration or run_assembly_iteration.
    """
    target_type, resolved_path, meta = resolve_iteration_target(iterate_path)
    run_id = run_id or (run_logger.run_id if run_logger else str(uuid.uuid4())[:8])
    gw = gateway_client or GatewayClient()

    if target_type == "part":
        return await run_part_iteration(
            base_code_or_file=resolved_path,
            prompt=user_feedback,
            output_dir=output_dir,
            gateway_client=gw,
            run_id=run_id
        )
    else:
        passed, graph, verdict, solids, artifacts = await run_assembly_iteration(
            base_run_dir=resolved_path,
            prompt=user_feedback,
            target_part_id=target_part_id,
            output_dir=output_dir,
            gateway_client=gw,
            run_id=run_id
        )
        return passed, graph, verdict, "", artifacts

