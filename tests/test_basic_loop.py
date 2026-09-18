"""
Integration Test for Basic P0 Single-Part Verification Loop (Async).
Runs the generate -> kernel -> critic -> export flow asynchronously using python-OCP & CadQuery.
"""

import asyncio
from pathlib import Path
from tests.mocks.mock_loop import run_basic_p0_loop
from tools.cad_kernel import execute_cadquery_code
from tools.verify_single_part import verify_single_part


def test_cadquery_execution():
    """Test CadQuery kernel execution sandbox asynchronously."""
    code = """import cadquery as cq
result = cq.Workplane("XY").box(10, 10, 10)
"""
    solid, err = asyncio.run(execute_cadquery_code(code))
    assert err is None, f"CadQuery execution failed: {err}"
    assert solid is not None
    assert solid.val().isValid() is True


def test_single_part_verification():
    """Test single part DFM and topology verification checks."""
    import cadquery as cq
    box = cq.Workplane("XY").box(40, 30, 10).faces(">Z").workplane().hole(4.3)
    verdict = verify_single_part(box, min_wall=1.5, min_hole=2.0)
    assert verdict.passed is True, f"Verification failed: {verdict.diagnostics}"
    assert verdict.bounding_box["xlen"] == 40.0
    assert verdict.bounding_box["ylen"] == 30.0
    assert verdict.bounding_box["zlen"] == 10.0


def test_basic_p0_loop_end_to_end(tmp_path):
    """Test end-to-end basic P0 loop asynchronously with artifact export."""
    prompt = "Single mounting bracket 40x30x10mm with a central 4.3mm M4 clearance hole"
    out_dir = str(tmp_path / "artifacts")
    
    success, verdict, code, artifact_paths = asyncio.run(
        run_basic_p0_loop(prompt, output_dir=out_dir)
    )
    
    assert success is True, f"P0 Loop failed. Verdict: {verdict}"
    assert "step" in artifact_paths and Path(artifact_paths["step"]).exists()
    assert "stl" in artifact_paths and Path(artifact_paths["stl"]).exists()
    assert "result =" in code
    print("\n[SUCCESS] Async Basic P0 Loop passed end-to-end!")
    print(f"Exported STEP: {artifact_paths['step']}")
    print(f"Exported STL: {artifact_paths['stl']}")


def test_export_cad_artifacts_with_spec_and_interfaces(tmp_path):
    """Test export_cad_artifacts generates spec.json and interfaces.json."""
    import cadquery as cq
    from tools.cad_kernel import export_cad_artifacts
    from orchestrator.models import PartSpec, InterfacePort

    solid = cq.Workplane("XY").box(40, 40, 10)
    spec = PartSpec(id="part_1", name="test_block", length=40.0, width=40.0, height=10.0)
    ports = {
        "hole_1": InterfacePort(name="hole_1", position=(0.0, 0.0, 5.0), feature_type="hole", diameter=10.0)
    }

    out_dir = str(tmp_path / "part_export")
    artifacts = asyncio.run(export_cad_artifacts(
        solid, out_dir, "test_block",
        code="result = cq.Workplane('XY').box(40, 40, 10)",
        spec=spec,
        interfaces=ports
    ))

    assert "step" in artifacts and Path(artifacts["step"]).exists()
    assert "stl" in artifacts and Path(artifacts["stl"]).exists()
    assert "py" in artifacts and Path(artifacts["py"]).exists()
    assert "spec" in artifacts and Path(artifacts["spec"]).exists()
    assert "interfaces" in artifacts and Path(artifacts["interfaces"]).exists()

    # Verify content of spec.json and interfaces.json
    spec_json = Path(artifacts["spec"]).read_text()
    assert '"name": "test_block"' in spec_json
    assert '"length": 40.0' in spec_json

    iface_json = Path(artifacts["interfaces"]).read_text()
    assert '"hole_1"' in iface_json
    assert '"diameter": 10.0' in iface_json



if __name__ == "__main__":
    test_cadquery_execution()
    test_single_part_verification()
    test_basic_p0_loop_end_to_end(Path("artifacts/test_output"))
