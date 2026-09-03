"""
Unit tests for strict Pydantic data contracts in orchestrator/models.py.
"""

from orchestrator.models import (
    PartSpec,
    MatingContext,
    JointDef,
    AssemblyGraph,
    InterfacePort,
    DesignerInput,
    DesignerOutput,
    DFMDiagnostic,
    VerificationVerdict,
    AssemblyDiagnostic,
    AssemblyVerdict,
    RepairInstruction,
    ValidationResult,
    RunEntry
)


def test_part_spec_instantiation():
    spec = PartSpec(
        id="p1",
        name="bracket",
        length=50.0,
        width=20.0,
        height=10.0,
        mates=[
            MatingContext(partner_id="bolt_1", mate_type="hole_shaft", my_feature_diameter=4.3)
        ]
    )
    assert spec.id == "p1"
    assert spec.length == 50.0
    assert len(spec.mates) == 1
    assert spec.mates[0].partner_id == "bolt_1"


def test_assembly_graph_instantiation():
    part1 = PartSpec(id="b1", name="bracket")
    part2 = PartSpec(id="b2", name="bolt")
    joint = JointDef(id="j1", type="rigid", part_a="b1", part_b="b2")
    graph = AssemblyGraph(name="test_assy", parts=[part1, part2], joints=[joint])
    
    assert len(graph.parts) == 2
    assert len(graph.joints) == 1
    assert graph.joints[0].part_a == "b1"


def test_designer_output_with_interfaces():
    port = InterfacePort(
        name="hole_1",
        position=(10.0, 15.0, 5.0),
        direction=(0.0, 0.0, 1.0),
        feature_type="hole",
        diameter=4.3
    )
    output = DesignerOutput(
        part_id="b1",
        code="import cadquery as cq\nresult = cq.Workplane('XY').box(10,10,10)",
        interfaces={"hole_1": port}
    )
    assert output.part_id == "b1"
    assert output.interfaces["hole_1"].diameter == 4.3


def test_verdict_models():
    dfm = DFMDiagnostic(
        rule_id="DFM-01",
        status="PASS",
        parameter="min_wall_thickness",
        measured=10.0,
        required=1.5,
        message="Wall ok"
    )
    verdict = VerificationVerdict(passed=True, diagnostics=[dfm], volume=12000.0)
    assert verdict.passed is True
    assert verdict.diagnostics[0].rule_id == "DFM-01"


def test_repair_instruction():
    repair = RepairInstruction(
        target_agent="code_generator_agent",
        target_part_id="b1",
        fault_type="dfm",
        prompt="Fix wall thickness to >= 1.5mm"
    )
    assert repair.target_agent == "code_generator_agent"
    assert repair.fault_type == "dfm"
