"""
CadQuery Kernel Execution Sandbox.
Safely executes agent-authored CadQuery code asynchronously and exports STEP/STL files.
"""

import asyncio
import traceback
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import cadquery as cq


class CADKernelExecutionError(Exception):
    """Raised when CadQuery code fails execution or fails to produce a solid result."""
    pass


import math
import re
import json

def _sync_execute_cadquery(code: str) -> Tuple[Any, Optional[str]]:
    """Synchronous internal execution logic."""
    execution_scope: Dict[str, Any] = {
        "cq": cq,
        "cadquery": cq,
        "math": math,
        "re": re,
        "json": json
    }
    
    try:
        # Pass a single dictionary to avoid the exec() local/global scoping quirk
        exec(code, execution_scope, execution_scope)
    except Exception as e:
        error_msg = f"CadQuery Execution Error: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        return None, error_msg

    if "result" not in execution_scope:
        return None, "Script execution succeeded but did not define a top-level `result` variable."

    result_obj = execution_scope["result"]
    if not isinstance(result_obj, (cq.Workplane, cq.Shape, cq.Compound)):
        return None, f"`result` object is of type {type(result_obj)}, expected cq.Workplane or cq.Shape."

    # Extract solid bodies to ensure code produced a true 3D solid, not a 2D sketch/wire
    solids = []
    if isinstance(result_obj, cq.Workplane):
        solids = result_obj.solids().vals()
    elif hasattr(result_obj, "Solids"):
        solids = result_obj.Solids()
    elif isinstance(result_obj, cq.Solid):
        solids = [result_obj]

    if not solids:
        return None, (
            "CadQuery execution error: `result` does not contain any 3D solid bodies. "
            "It appears to be a 2D sketch, wire, or empty workplane. "
            "Ensure all 2D profiles are extruded (.extrude()) or cut (.cutBlind()) into 3D solid geometry."
        )

    # Check total volume across solids
    total_vol = sum(getattr(s, "Volume", lambda: 0.0)() for s in solids)
    if total_vol <= 1e-6:
        return None, (
            f"CadQuery execution error: `result` solid body has zero or negative volume ({total_vol} mm³). "
            "Ensure features create a valid 3D manifold solid."
        )

    return result_obj, None



async def execute_cadquery_code(code: str) -> Tuple[Any, Optional[str]]:
    """
    Asynchronously executes CadQuery Python code in a thread pool to avoid blocking the event loop.
    
    Returns:
        (cq.Workplane or cq.Shape object, error_message)
    """
    return await asyncio.to_thread(_sync_execute_cadquery, code)


async def export_cad_artifacts(
    solid_obj: Any,
    output_dir: str,
    file_prefix: str,
    code: Optional[str] = None,
    spec: Optional[Any] = None,
    interfaces: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """
    Asynchronously exports a CadQuery Workplane/Shape to STEP, STL, Python script,
    and typed JSON specifications (spec.json and interfaces.json).
    """
    def _export():
        import json
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        step_file = out_path / f"{file_prefix}.step"
        stl_file = out_path / f"{file_prefix}.stl"
        py_file = out_path / f"{file_prefix}.py"

        # Handle cq.Assembly vs cq.Workplane / cq.Shape
        if isinstance(solid_obj, cq.Assembly):
            try:
                solid_obj.save(str(step_file))
            except Exception:
                compound = solid_obj.toCompound()
                cq.exporters.export(compound, str(step_file), exportType="STEP")

            try:
                solid_obj.save(str(stl_file))
            except Exception:
                compound = solid_obj.toCompound()
                cq.exporters.export(compound, str(stl_file), exportType="STL")
        else:
            # Export STEP
            cq.exporters.export(solid_obj, str(step_file), exportType="STEP")
            # Export STL
            cq.exporters.export(solid_obj, str(stl_file), exportType="STL")

        artifacts = {
            "step": str(step_file),
            "stl": str(stl_file)
        }

        # Export Python CadQuery script
        if code:
            py_file.write_text(code, encoding="utf-8")
            artifacts["py"] = str(py_file)

        # Export PartSpec / AssemblyGraph JSON specification
        if spec is not None:
            is_assembly = (
                type(spec).__name__ == "AssemblyGraph" or
                (isinstance(spec, dict) and "parts" in spec and "joints" in spec)
            )
            spec_name = "assembly_graph.json" if is_assembly else "spec.json"
            spec_file = out_path / spec_name

            if hasattr(spec, "model_dump_json"):
                spec_json = spec.model_dump_json(indent=2)
            elif isinstance(spec, dict):
                spec_json = json.dumps(spec, indent=2)
            else:
                spec_json = str(spec)

            spec_file.write_text(spec_json, encoding="utf-8")
            artifacts["spec"] = str(spec_file)

            # Also create named json file (e.g. mounting_bracket.json) for convenience
            if file_prefix and file_prefix != spec_name.replace(".json", ""):
                named_file = out_path / f"{file_prefix}.json"
                named_file.write_text(spec_json, encoding="utf-8")

        # Export InterfacePorts JSON
        if interfaces is not None:
            iface_file = out_path / "interfaces.json"
            iface_data = {}
            for k, v in interfaces.items():
                if hasattr(v, "model_dump"):
                    iface_data[k] = v.model_dump()
                elif isinstance(v, dict):
                    iface_data[k] = v
                else:
                    iface_data[k] = str(v)
            iface_file.write_text(json.dumps(iface_data, indent=2), encoding="utf-8")
            artifacts["interfaces"] = str(iface_file)

        return artifacts

    return await asyncio.to_thread(_export)

