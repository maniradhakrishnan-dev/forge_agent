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

    # 2. Resolving a direct spec.json file
    spec_file = tmp_path / "spec.json"
    spec_file.write_text('{"id": "part_1", "name": "bracket", "length": 50.0}')
    t_type, path, meta = resolve_iteration_target(str(spec_file))
    assert t_type == "part"
    assert path == str(spec_file)
    assert meta.get("spec_file") == str(spec_file)

    # 3. Resolving a direct assembly_graph.json file
    graph_file = tmp_path / "assembly_graph.json"
    graph_file.write_text('{"name": "assy", "parts": [], "joints": []}')
    t_type, path, meta = resolve_iteration_target(str(graph_file))
    assert t_type == "assembly"
    assert meta.get("graph_file") == str(graph_file)

    # 4. Resolving an assembly directory
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

    # 5. Resolving a directory with spec.json
    single_dir = tmp_path / "single_part_dir"
    single_dir.mkdir()
    (single_dir / "spec.json").write_text('{"id": "single", "name": "block"}')
    t_type, path, meta = resolve_iteration_target(str(single_dir))
    assert t_type == "part"
    assert "spec.json" in path



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


@pytest.mark.asyncio
async def test_part_iteration_from_spec_json(tmp_path):
    """Tests iterating directly from a spec.json file on disk with zero-LLM parametric edit."""
    part_dir = tmp_path / "part_1"
    part_dir.mkdir()
    spec_file = part_dir / "spec.json"
    spec_file.write_text("""{
  "id": "part_1",
  "name": "block",
  "description": "block with hole",
  "part_type": "mounting_bracket",
  "manufacturing_process": "3d_printing",
  "verification_depth": "functional",
  "length": 40.0,
  "width": 40.0,
  "height": 10.0,
  "hole_diameter": 10.0,
  "wall_thickness": 4.0
}""")

    code_file = part_dir / "block.py"
    code_file.write_text("""import cadquery as cq

# Parameters
length = 40.0
width = 40.0
height = 10.0
hole_dia = 10.0

result = cq.Workplane("XY").box(length, width, height).faces(">Z").workplane(centerOption="CenterOfMass").hole(hole_dia)
""")

    out_dir = str(tmp_path / "iter_out")
    client = GatewayClient()
    prompt = "increase the hole diameter to 12mm"

    passed, spec, verdict, code, artifacts = await run_part_iteration(
        base_code_or_file=str(spec_file),
        prompt=prompt,
        output_dir=out_dir,
        gateway_client=client
    )

    assert passed is True
    assert verdict is not None and verdict.passed is True
    assert "step" in artifacts and Path(artifacts["step"]).exists()
    assert "spec" in artifacts and Path(artifacts["spec"]).exists()
    assert "12.0" in code or "12" in code


@pytest.mark.asyncio
async def test_direct_spec_replay_zero_tokens(tmp_path):
    """Tests editing spec.json directly (e.g. changing length to 60mm and hole to 14mm) and rebuilding with zero tokens."""
    part_dir = tmp_path / "part_bracket"
    part_dir.mkdir()
    spec_file = part_dir / "spec.json"
    # User manually changed length to 60.0 and hole_diameter to 14.0 in spec.json
    spec_file.write_text("""{
  "id": "part_bracket",
  "name": "bracket",
  "description": "mounting bracket",
  "part_type": "mounting_bracket",
  "manufacturing_process": "3d_printing",
  "verification_depth": "functional",
  "length": 60.0,
  "width": 30.0,
  "height": 10.0,
  "hole_diameter": 14.0,
  "wall_thickness": 4.0
}""")

    code_file = part_dir / "bracket.py"
    code_file.write_text("""import cadquery as cq

# Parameters
length = 40.0
width = 30.0
height = 10.0
hole_dia = 10.0

result = cq.Workplane("XY").box(length, width, height).faces(">Z").workplane(centerOption="CenterOfMass").hole(hole_dia)
""")

    out_dir = str(tmp_path / "replay_out")
    client = GatewayClient()

    # User triggers rebuild with no prompt or 'rebuild'
    passed, spec, verdict, code, artifacts = await run_part_iteration(
        base_code_or_file=str(spec_file),
        prompt="rebuild",
        output_dir=out_dir,
        gateway_client=client
    )

    assert passed is True
    assert verdict is not None and verdict.passed is True
    assert "step" in artifacts and Path(artifacts["step"]).exists()
    assert "spec" in artifacts and Path(artifacts["spec"]).exists()
    # Check that variables in code were updated to match the edited JSON
    assert "60.0" in code or "60" in code
    assert "14.0" in code or "14" in code
    assert spec.length == 60.0
    assert spec.hole_diameter == 14.0


