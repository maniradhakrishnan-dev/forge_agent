"""
Unit tests for ConstraintValidator (orchestrator/constraint_validator.py).
"""

from orchestrator.models import AssemblyGraph, PartSpec, MatingContext, JointDef
from orchestrator.constraint_validator import ConstraintValidator


def test_constraint_validator_pass():
    p1 = PartSpec(
        id="bracket",
        mates=[MatingContext(partner_id="bolt", mate_type="hole_shaft", my_feature_diameter=4.3, clearance_mm=0.3)]
    )
    p2 = PartSpec(
        id="bolt",
        mates=[MatingContext(partner_id="bracket", mate_type="shaft_hole", my_feature_diameter=4.0, clearance_mm=0.3)]
    )
    joint = JointDef(id="j1", part_a="bracket", part_b="bolt")
    graph = AssemblyGraph(parts=[p1, p2], joints=[joint])

    res = ConstraintValidator.validate(graph)
    assert res.valid is True
    assert len(res.errors) == 0


def test_constraint_validator_missing_partner():
    p1 = PartSpec(
        id="bracket",
        mates=[MatingContext(partner_id="non_existent_part", mate_type="hole_shaft")]
    )
    graph = AssemblyGraph(parts=[p1])

    res = ConstraintValidator.validate(graph)
    assert res.valid is False
    assert any("non-existent" in err for err in res.errors)


def test_constraint_validator_fuzzy_and_reciprocal_healing():
    # p1 references 'planet_gears', but p2 is named 'planet_gear_set'
    p1 = PartSpec(
        id="sun_gear",
        mates=[MatingContext(partner_id="planet_gears", mate_type="hole_shaft", my_feature_diameter=5.3, clearance_mm=0.15)]
    )
    # p2 does not have reciprocal mate explicitly defined
    p2 = PartSpec(
        id="planet_gear_set",
        mates=[]
    )
    joint = JointDef(id="j1", part_a="sun_gear", part_b="planet_gears")
    graph = AssemblyGraph(parts=[p1, p2], joints=[joint])

    res = ConstraintValidator.validate(graph)
    assert res.valid is True
    assert p1.mates[0].partner_id == "planet_gear_set"
    assert joint.part_b == "planet_gear_set"
    assert len(p2.mates) == 1
    assert p2.mates[0].partner_id == "sun_gear"


def test_constraint_validator_nominal_fit_auto_healing():
    """Hole and shaft have identical nominal diameter (e.g. 5.0mm & 5.0mm). Auto-heals to clearance fit."""
    p1 = PartSpec(
        id="planet_gear",
        hole_diameter=5.0,
        mates=[MatingContext(partner_id="planet_carrier", mate_type="hole_shaft", my_feature_diameter=5.0, clearance_mm=0.2)]
    )
    p2 = PartSpec(
        id="planet_carrier",
        mates=[MatingContext(partner_id="planet_gear", mate_type="shaft_hole", my_feature_diameter=5.0, clearance_mm=0.2)]
    )
    joint = JointDef(id="j1", part_a="planet_gear", part_b="planet_carrier")
    graph = AssemblyGraph(parts=[p1, p2], joints=[joint])

    res = ConstraintValidator.validate(graph)
    assert res.valid is True
    assert len(res.errors) == 0
    # Hole diameter auto-healed to shaft + clearance (5.0 + 0.2 = 5.2)
    assert p1.mates[0].my_feature_diameter == 5.2
    assert p2.mates[0].my_feature_diameter == 5.0
    assert p1.hole_diameter == 5.2


def test_constraint_validator_inverted_tolerance_healing():
    """Hole=5.0mm, Shaft=5.2mm (inadvertently inverted by LLM). Auto-swaps to hole=5.2mm, shaft=5.0mm."""
    p1 = PartSpec(
        id="planet_gear",
        hole_diameter=5.0,
        mates=[MatingContext(partner_id="planet_carrier", mate_type="hole_shaft", my_feature_diameter=5.0, clearance_mm=0.2)]
    )
    p2 = PartSpec(
        id="planet_carrier",
        mates=[MatingContext(partner_id="planet_gear", mate_type="shaft_hole", my_feature_diameter=5.2, clearance_mm=0.2)]
    )
    joint = JointDef(id="j1", part_a="planet_gear", part_b="planet_carrier")
    graph = AssemblyGraph(parts=[p1, p2], joints=[joint])

    res = ConstraintValidator.validate(graph)
    assert res.valid is True
    assert len(res.errors) == 0
    assert p1.mates[0].my_feature_diameter == 5.2
    assert p2.mates[0].my_feature_diameter == 5.0


def test_constraint_validator_true_interference_error():
    """Shaft is substantially larger than hole (e.g. 10mm shaft into 5mm hole). Reports unambiguous error."""
    p1 = PartSpec(
        id="planet_gear",
        mates=[MatingContext(partner_id="planet_carrier", mate_type="hole_shaft", my_feature_diameter=5.0, clearance_mm=0.2)]
    )
    p2 = PartSpec(
        id="planet_carrier",
        mates=[MatingContext(partner_id="planet_gear", mate_type="shaft_hole", my_feature_diameter=10.0, clearance_mm=0.2)]
    )
    joint = JointDef(id="j1", part_a="planet_gear", part_b="planet_carrier")
    graph = AssemblyGraph(parts=[p1, p2], joints=[joint])

    res = ConstraintValidator.validate(graph)
    assert res.valid is False
    assert len(res.errors) == 1
    # Ensure error correctly names hole on planet_gear and shaft on planet_carrier (not duplicated, not inverted)
    assert "hole diameter (5.0mm) on 'planet_gear' is smaller than shaft diameter (10.0mm) on 'planet_carrier'" in res.errors[0]


