"""
Unit tests for ConstraintValidator (orchestrator/constraint_validator.py).
"""

from orchestrator.models import AssemblyGraph, PartSpec, MatingContext, JointDef
from orchestrator.agents.constraint_validator import ConstraintValidator


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


def test_constraint_validator_gear_mesh_center_distance_healing():
    """Gear mesh with mismatched center distance auto-heals to kinematic pitch radius sum."""
    p1 = PartSpec(
        id="gear_a",
        kinematic_params={"module": 1.0, "num_teeth": 20},
        mates=[MatingContext(partner_id="gear_b", mate_type="gear_mesh")]
    )
    p2 = PartSpec(
        id="gear_b",
        kinematic_params={"module": 1.0, "num_teeth": 40},
        mates=[MatingContext(partner_id="gear_a", mate_type="gear_mesh")]
    )
    joint = JointDef(id="j1", part_a="gear_a", part_b="gear_b")
    # Pitch radii are 10.0 and 20.0 -> expected center distance is 30.0.
    # Provided center distance is 25.0 (incorrect).
    graph = AssemblyGraph(
        parts=[p1, p2],
        joints=[joint],
        shared_parameters={"center_to_center_distance": 25.0}
    )

    res = ConstraintValidator.validate(graph)
    assert res.valid is True
    assert graph.shared_parameters["center_to_center_distance"] == 30.0


def test_constraint_validator_orphan_part_error():
    """Part without any mates or joints is flagged as an orphan."""
    p1 = PartSpec(id="housing", mates=[])
    p2 = PartSpec(id="shaft", mates=[])
    graph = AssemblyGraph(parts=[p1, p2], joints=[])

    res = ConstraintValidator.validate(graph)
    assert res.valid is False
    assert any("Orphan part" in err for err in res.errors)


def test_constraint_validator_inverted_hole_shaft_role_healing():
    """LLM inverts hole_shaft & shaft_hole between block and shaft. Validator auto-swaps and cleans dimensions."""
    p1 = PartSpec(
        id="part_1",
        name="support_block",
        part_type="bracket",
        geometry_form="bracket",
        length=50.0,
        width=50.0,
        height=10.0,
        hole_diameter=20.0,
        critical_dimensions={"outer_diameter": 20.0},
        mates=[
            MatingContext(
                partner_id="part_2",
                mate_type="shaft_hole",  # Inverted by LLM
                my_feature_name="central_bore",
                mate_port_id="shaft_surface",
                my_feature_diameter=20.0,
                clearance_mm=0.15
            )
        ]
    )
    p2 = PartSpec(
        id="part_2",
        name="long_shaft",
        part_type="shaft",
        geometry_form="stepped_shaft",
        length=1000.0,
        critical_dimensions={"outer_diameter": 20.0, "length": 1000.0},
        mates=[
            MatingContext(
                partner_id="part_1",
                mate_type="hole_shaft",  # Inverted by LLM
                my_feature_name="shaft_surface",
                mate_port_id="central_bore",
                my_feature_diameter=20.15,
                clearance_mm=0.15
            )
        ]
    )
    joint = JointDef(id="joint_1", type="cylindrical", part_a="part_1", part_b="part_2")
    graph = AssemblyGraph(parts=[p1, p2], joints=[joint])

    res = ConstraintValidator.validate(graph)
    assert res.valid is True
    assert len(res.errors) == 0

    # Roles must be swapped to physical truth:
    # p1 (block) has the hole -> hole_shaft, feature diameter 20.15
    assert p1.mates[0].mate_type == "hole_shaft"
    assert p1.mates[0].my_feature_diameter == 20.15
    # p2 (shaft) is the shaft -> shaft_hole, feature diameter 20.0
    assert p2.mates[0].mate_type == "shaft_hole"
    assert p2.mates[0].my_feature_diameter == 20.0

    # Bogus outer_diameter on bracket must be purged or converted to bore_diameter
    assert "outer_diameter" not in p1.critical_dimensions
    assert p1.critical_dimensions.get("bore_diameter") == 20.15




