"""
Unit & Integration tests for Human-in-the-Loop Iteration Engine (orchestrator/iteration_pipeline.py).
"""

import pytest
from pathlib import Path
from orchestrator.gateway_client import GatewayClient
from orchestrator.iteration_pipeline import (
    resolve_iteration_target,
    run_part_iteration,
    run_assembly_iteration
)


def test_resolve_iteration_target(tmp_path):
    # 1. Resolving a single .py file
    py_file = tmp_path / "part_bracket.py"
    py_file.write_text("import cadquery as cq\nresult = cq.Workplane('XY').box(10, 10, 10)")
    t_type, path, meta = resolve_iteration_target(str(py_file))
    assert t_type == "part"
    assert path == str(py_file)

    # 2. Resolving an assembly directory
    assy_dir = tmp_path / "test_assy"
    assy_dir.mkdir()
    (assy_dir / "assembly.step").write_text("dummy step")
    part_a = assy_dir / "part_a"
    part_a.mkdir()
    (part_a / "part_a.py").write_text("dummy code")
    part_b = assy_dir / "part_b"
    part_b.mkdir()
    (part_b / "part_b.py").write_text("dummy code")

    t_type, path, meta = resolve_iteration_target(str(assy_dir))
    assert t_type == "assembly"
    assert path == str(assy_dir)


@pytest.mark.asyncio
async def test_single_part_iteration_end_to_end(tmp_path):
    """Tests iterating on an existing single part with surgical modifications."""
    base_file = "artifacts/runs/8ff28964/top_ergonomic_shell.py"
    if not Path(base_file).exists():
        pytest.skip(f"Base file {base_file} not found.")

    out_dir = str(tmp_path / "part_iter_out")
    client = GatewayClient()
    prompt = "Add an oval cutout on the top center for a scroll wheel (length 25mm, width 10mm)"

    passed, spec, verdict, code, artifacts = await run_part_iteration(
        base_code_or_file=base_file,
        prompt=prompt,
        output_dir=out_dir,
        gateway_client=client
    )

    assert passed is True
    assert verdict is not None and verdict.passed is True
    assert "step" in artifacts and Path(artifacts["step"]).exists()
    assert "stl" in artifacts and Path(artifacts["stl"]).exists()
    assert "cutout" in code.lower() or "slot" in code.lower() or "wheel" in code.lower() or "oval" in code.lower() or "circle" in code.lower()


@pytest.mark.asyncio
async def test_assembly_iteration_end_to_end(tmp_path):
    """Tests iterating on an existing assembly, updating one part and re-verifying assembly ground-truth."""
    base_dir = "artifacts/test_cli_assy"
    if not Path(base_dir).exists():
        pytest.skip(f"Base assembly dir {base_dir} not found.")

    out_dir = str(tmp_path / "assy_iter_out")
    client = GatewayClient()
    prompt = "Increase the bolt length to 30mm and ensure proper fit"

    passed, graph, verdict, solids, artifacts = await run_assembly_iteration(
        base_run_dir=base_dir,
        prompt=prompt,
        target_part_id="part_2",
        output_dir=out_dir,
        gateway_client=client
    )

    assert passed is True
    assert verdict.passed is True
    assert len(solids) >= 2
    assert "assembly" in artifacts
