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
    code: Optional[str] = None
) -> Dict[str, str]:
    """
    Asynchronously exports a CadQuery Workplane/Shape to STEP, STL, and Python script format.
    """
    def _export():
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

        return artifacts

    return await asyncio.to_thread(_export)
