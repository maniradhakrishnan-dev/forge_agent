"""
Unit tests for CodeGeneratorAgent (orchestrator/agents/code_generator_agent.py).
"""

import pytest
from orchestrator.models import PartSpec, MatingContext
from orchestrator.gateway_client import GatewayClient, GatewayConfig
from orchestrator.agents.code_generator_agent import CodeGeneratorAgent


def test_apply_surgical_diff_single_block():
    base_code = (
        "import cadquery as cq\n"
        "length = 40.0\n"
        "width = 30.0\n"
        "hole_dia = 2.0\n"
        "result = cq.Workplane('XY').box(length, width, 10).faces('>Z').hole(hole_dia)\n"
    )
    diff = (
        "Here is the targeted repair:\n"
        "<<<<<<< SEARCH\n"
        "hole_dia = 2.0\n"
        "=======\n"
        "hole_dia = 4.5\n"
        ">>>>>>>\n"
    )
    patched, ok = CodeGeneratorAgent.apply_surgical_diff(base_code, diff)
    assert ok is True
    assert "hole_dia = 4.5" in patched
    assert "length = 40.0" in patched
    assert "width = 30.0" in patched


def test_apply_surgical_diff_multiple_blocks():
    base_code = (
        "import cadquery as cq\n"
        "length = 40.0\n"
        "width = 30.0\n"
        "result = cq.Workplane('XY').box(length, width, 10)\n"
    )
    diff = (
        "<<<<<<< SEARCH\n"
        "length = 40.0\n"
        "=======\n"
        "length = 50.0\n"
        ">>>>>>>\n"
        "and also:\n"
        "<<<<<<< SEARCH\n"
        "result = cq.Workplane('XY').box(length, width, 10)\n"
        "=======\n"
        "result = cq.Workplane('XY').box(length, width, 10).faces('>Z').hole(5.0)\n"
        ">>>>>>>\n"
    )
    patched, ok = CodeGeneratorAgent.apply_surgical_diff(base_code, diff)
    assert ok is True
    assert "length = 50.0" in patched
    assert ".hole(5.0)" in patched


def test_apply_surgical_diff_syntax_error_rejection():
    base_code = (
        "import cadquery as cq\n"
        "result = cq.Workplane('XY').box(10, 10, 10)\n"
    )
    diff = (
        "<<<<<<< SEARCH\n"
        "result = cq.Workplane('XY').box(10, 10, 10)\n"
        "=======\n"
        "result = cq.Workplane('XY').box(10, 10,  # incomplete syntax\n"
        ">>>>>>>\n"
    )
    patched, ok = CodeGeneratorAgent.apply_surgical_diff(base_code, diff)
    assert ok is False
    assert patched == base_code


def test_clean_fences():
    fenced = "```python\nimport cadquery as cq\nresult = cq.Workplane('XY').box(10, 10, 10)\n```"
    cleaned = CodeGeneratorAgent._clean_fences(fenced)
    assert not cleaned.startswith("```")
    assert not cleaned.endswith("```")
    assert "import cadquery as cq" in cleaned


@pytest.mark.live
@pytest.mark.asyncio
async def test_code_generator_outputs_designer_output():
    client = GatewayClient()
    agent = CodeGeneratorAgent(client)
    
    spec = PartSpec(
        id="bracket_1",
        name="cnc_bracket",
        part_type="mounting_bracket",
        manufacturing_process="cnc_machining",
        length=50.0,
        width=40.0,
        height=15.0
    )
    
    output = await agent.generate_designer_output(spec)
    assert output.part_id == "bracket_1"
    assert "result =" in output.code
    assert len(output.interfaces) > 0

