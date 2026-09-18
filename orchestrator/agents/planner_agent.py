"""
Planner Agent (Architect).
Decomposes user text prompt into a structured AssemblyGraph JSON requirement
using LLM inference. NO hardcoded fallbacks — the LLM does all the thinking.
"""

import json
from typing import Optional, List, Dict, Any
from orchestrator.gateway_client import GatewayClient
from orchestrator.models import AssemblyGraph, PartSpec
from orchestrator.toolbox import AgentToolbox


class PlannerParseError(Exception):
    """Raised when the LLM response cannot be parsed into a valid AssemblyGraph."""
    def __init__(self, raw_response: str, parse_error: str):
        self.raw_response = raw_response
        self.parse_error = parse_error
        super().__init__(
            f"❌ PlannerAgent failed to parse LLM response into AssemblyGraph.\n"
            f"   Parse Error: {parse_error}\n"
            f"   Raw LLM Response (first 500 chars):\n"
            f"   {raw_response[:500]}"
        )


PLANNER_SYSTEM_PROMPT = """You are the Lead Mechanical Architect & Planner Agent for ForgeAgent, a professional AI mechanical CAD system.

Your job: Decompose the user's plain-English mechanical design prompt into a high-taste, structurally sound, and kinematically rigorous AssemblyGraph JSON.

## Architectural Principles & Rules:
1. **Form Follows Function**:
   - Axisymmetric components (housings, shafts, discs, gears, pulleys) must be modeled with cylindrical/annular envelopes (`geometry_form: "annular_flanged_casing"`, `"stepped_shaft"`, `"cycloid_disc"`), avoiding material-wasting rectangular slabs.
   - Structural brackets, ribs, and plates should use webbed forms (`geometry_form: "bracket"`, `"flanged_plate"`).

2. **Kinematic Invariants & Top-Down Consistency**:
   - Compute and populate all kinematic relations (pitch circle diameters, tooth ratios, center distances, reduction ratios) in `shared_parameters`.
   - Ensure matching mating features between partner parts share the exact same pitch circle diameters and center-to-center distances.

3. **Single-Part vs Multi-Part Decomposition**:
   - Standalone parts (a single bolt, screw, nut, bracket, plate, bowl, pulley, or gear) MUST be 1 part in `parts` (`is_single_part: true`) and 0 joints in `joints`.
   - Multi-part decomposition is required whenever the prompt describes multiple interacting, mating, or inserted components (e.g. shafts inserted into holes of a block, gears meshing, bolts fastening plates together, linkages, or speed reducers).
   - Decompose every individual physical part into the `parts` list with its corresponding `id`, `name`, `geometry_form`, `part_type`, `critical_dimensions`, and `mates`.

4. **Explicit Constraints vs Inferred Defaults**:
   - In `explicit_constraints`, extract ONLY dimensions and numbers the user explicitly stated in their prompt.
   - If user did not specify exact dimensions, leave `explicit_constraints: {}` empty.

5. **Dynamic Skill Assignment**:
   - Review the AVAILABLE ENGINEERING SKILLS catalog appended below.
   - For `AssemblyGraph.skills`, assign the high-level mechanism and assembly skills (e.g. `["assembly_strategies", "fits_and_tolerances"]`).
   - For each `PartSpec.skills`, assign the specific component and manufacturing skills needed for that exact part (e.g. `["stepped_shaft", "dfm_3d_printing", "fits_and_tolerances"]` or `["fasteners_and_flanges", "dfm_3d_printing"]`).
   - Assign ONLY valid skill names from the Available Engineering Skills catalog.

## Output Schema (respond ONLY with raw JSON, no markdown fences):

{
  "name": "short_snake_case_assembly_name",
  "description": "the user's original spec",
  "mechanism_type": "single_part | cycloidal_drive | planetary_gearbox | harmonic_drive | linkage | bracket_assembly | fastener",
  "skills": ["mechanism_skill_name", "dfm_skill_name"],
  "shared_parameters": {
    "center_distance": 40.0,
    "clearance": 0.15
  },
  "parts": [
    {
      "id": "part_1",
      "name": "descriptive_part_name",
      "description": "what this part is and its functional architecture",
      "part_type": "housing | shaft | gear | carrier | bracket | disc | bolt | plate",
      "geometry_form": "annular_flanged_casing | stepped_shaft | cycloid_disc | pin_carrier_flange | spur_gear | bracket | bolt | nut | revolved_dish",
      "manufacturing_process": "3d_printing | cnc_machining | sheet_metal",
      "verification_depth": "concept | functional | manufacturing | assembly_ready",
      "skills": ["stepped_shaft", "dfm_3d_printing"],
      "length": 40.0,
      "width": 30.0,
      "height": 10.0,
      "hole_diameter": 6.0,
      "wall_thickness": 4.0,
      "custom_parameters": {},
      "critical_dimensions": {
        "outer_diameter": 6.0,
        "length": 40.0
      },
      "features": [],
      "explicit_constraints": {},
      "is_single_part": true,
      "is_compliant": false,
      "mates": [
        {
          "partner_id": "part_2",
          "mate_type": "hole_shaft (if THIS part has the hole/bore) | shaft_hole (if THIS part is the shaft/pin) | face_face | edge_edge | gear_mesh",
          "my_feature_name": "central_bore (if hole) | shaft_tip (if shaft)",
          "mate_port_id": "shaft_tip (partner's mating feature)",
          "my_feature_diameter": 6.15,
          "clearance_mm": 0.15
        }
      ]
    }
  ],
  "joints": [
    {
      "id": "joint_1",
      "type": "rigid | revolute | prismatic | cylindrical",
      "part_a": "part_1",
      "part_b": "part_2",
      "axis": [0, 0, 1]
    }
  ]
}

## Engineering & DFM Rules:
1. Single vs Multi-Part: Standalone parts MUST be 1 part in `parts` and 0 joints in `joints`.
2. Mechanism Completeness: For multi-part assemblies, include all essential functional parts to complete the kinematic loop.
3. Running / Clearance Fits: Mating holes must be strictly larger than mating shafts (hole = shaft + clearance).
4. Geometry-Form Aware Critical Dimensions: For every part, declare explicit `critical_dimensions` (e.g., for a shaft: `{"outer_diameter": 6.0, "length": 40.0}`, for a housing: `{"bore_diameter": 6.15, "outer_diameter": 30.0, "height": 20.0}`). Downstream verifiers check OpenCascade BRep geometry directly against `critical_dimensions`.
   - Never assign `outer_diameter` in `critical_dimensions` to rectangular blocks or brackets. Only use `outer_diameter` for axisymmetric/cylindrical parts (shafts, pins, bushings, discs, gears).
5. Explicit Port Mating Contract: In each `mates` entry, define `my_feature_name` and `mate_port_id` (the name of the partner's mating port) so the Assembler can mate them deterministically without scoring heuristics.
6. Typed Contract Invariants: All critical dimensions MUST be typed in `length`, `width`, `height`, `hole_diameter`, `wall_thickness`, `custom_parameters`, and `critical_dimensions` so the downstream Designer never hallucinates.
7. Mating Direction Conventions (Hole vs Shaft):
   - `"hole_shaft"`: Used by the part containing the HOLE/BORE. `my_feature_diameter` MUST be the bore diameter (e.g., 20.15).
   - `"shaft_hole"`: Used by the part containing the SHAFT/PIN/BOLT. `my_feature_diameter` MUST be the shaft diameter (e.g., 20.0).
8. Respond with ONLY the raw JSON object. No explanation, no markdown fences."""


class PlannerAgent:
    def __init__(self, gateway_client: GatewayClient):
        self.gateway = gateway_client

    async def plan_assembly(
        self,
        prompt: str,
        validation_errors: Optional[List[str]] = None
    ) -> AssemblyGraph:
        """
        Uses LLM to decompose user prompt into a structured AssemblyGraph.
        Dynamically injects relevant domain skills from the SkillRegistry.
        If validation_errors from ConstraintValidator are provided, feeds them back
        for self-correction.
        """
        AgentToolbox.enforce("planner_agent", "gateway_client")

        # Dynamically inject the full registry skill catalog into the Planner prompt
        from orchestrator.skills.registry import default_registry
        catalog_text = default_registry.format_catalog_for_planner()

        system_prompt = PLANNER_SYSTEM_PROMPT
        if catalog_text:
            system_prompt += f"\n\n## AVAILABLE ENGINEERING SKILLS IN REGISTRY (Assign to graph.skills and part.skills):\n{catalog_text}"

        # If mechanism-specific skills (e.g. cycloidal, planetary) or complex kinematics are applicable,
        # also attach detailed formulas from the skill contents
        mechanism_skills = [
            s for s in ["cycloidal_drive", "planetary_gearbox", "compliant_mechanisms"]
            if any(term in prompt.lower() for term in s.split("_"))
        ]
        if mechanism_skills:
            detailed_skills_text = default_registry.format_skills_for_prompt(mechanism_skills)
            if detailed_skills_text:
                system_prompt += f"\n\n## DETAILED MECHANISM KINEMATIC FORMULAS:\n{detailed_skills_text}"

        user_content = f"Design Prompt: {prompt}"
        if validation_errors:
            user_content += (
                f"\n\n--- PREVIOUS ATTEMPT VALIDATION ERRORS ---\n"
                f"Your previous AssemblyGraph had the following consistency errors:\n"
                + "\n".join(f"- {err}" for err in validation_errors)
                + "\nPlease output a corrected AssemblyGraph JSON ensuring all part IDs match exactly, reciprocal mates exist, and mating clearances are consistent (hole diameter must be strictly larger than shaft diameter: hole = shaft + clearance)."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        # This will raise LLMAPIError if both providers fail — no silent fallback
        response_text = await self.gateway.complete(messages, temperature=0.1)

        # Parse the LLM response into AssemblyGraph
        try:
            # Strip markdown code fences if present
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                # Remove opening fence (```json or ```)
                first_newline = cleaned.index("\n")
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            graph = AssemblyGraph(**data)

            # Validate: must have at least one part
            if not graph.parts:
                raise PlannerParseError(
                    raw_response=response_text,
                    parse_error="AssemblyGraph has zero parts. LLM returned an empty decomposition."
                )

            print(f"  ✅ PlannerAgent decomposed prompt into {len(graph.parts)} parts: "
                  f"{[p.name for p in graph.parts]}")
            return graph

        except json.JSONDecodeError as e:
            raise PlannerParseError(
                raw_response=response_text,
                parse_error=f"JSON decode error: {e}"
            )
        except PlannerParseError:
            raise
        except Exception as e:
            raise PlannerParseError(
                raw_response=response_text,
                parse_error=f"{type(e).__name__}: {e}"
            )

    async def plan_part(self, prompt: str) -> PartSpec:
        """
        Backward compatible single-part planning helper.
        """
        graph = await self.plan_assembly(prompt)
        return graph.parts[0]

    async def plan_iteration_part(self, existing_code: str, user_feedback: str) -> PartSpec:
        """
        Analyzes existing CadQuery code and user modification feedback to generate an updated PartSpec.
        """
        AgentToolbox.enforce("planner_agent", "gateway_client")
        system_prompt = (
            "You are the Architect Planner Agent for ForgeAgent. "
            "Your job is to formulate a focused, minimal PartSpec update for an existing mechanical part based strictly on the user's iteration request.\n\n"
            "## CRITICAL ITERATION RULES:\n"
            "1. STRICT MINIMALITY: Only specify changes and features that the user explicitly asked for.\n"
            "2. DO NOT invent or assume unsolicited features (e.g., extra mounting holes, fastener patterns, counterbores, fillets) unless the user explicitly requested them.\n"
            "3. PRESERVE BASE GEOMETRY: Keep existing dimensions, part names, and base features intact unless the user explicitly instructs to alter them.\n"
            "4. Respond ONLY with valid raw JSON representing the updated PartSpec (matching schema: name, description, length, width, height, hole_diameter, wall_thickness, etc.). Do not include markdown code fences."
        )
        prompt = (
            f"Existing CadQuery Code:\n```python\n{existing_code[:2500]}\n```\n\n"
            f"User Modification Request:\n{user_feedback}\n\n"
            f"Output the updated PartSpec JSON reflecting ONLY the exact user requested modifications. "
            f"Respond ONLY with raw JSON."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        response_text = await self.gateway.complete(messages, temperature=0.1)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.index("\n")
            cleaned = cleaned[first_nl + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)
        part_dict = data["parts"][0] if ("parts" in data and isinstance(data["parts"], list) and data["parts"]) else data
        part_dict.setdefault("is_single_part", True)
        return PartSpec(**part_dict)

    async def plan_iteration_assembly(
        self,
        existing_graph: AssemblyGraph,
        user_feedback: str,
        part_codes: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Analyzes user modification feedback on an existing assembly and determines which parts must be updated.
        """
        AgentToolbox.enforce("planner_agent", "gateway_client")
        parts_info = [
            {"id": p.id, "name": p.name, "description": p.description, "process": p.manufacturing_process}
            for p in existing_graph.parts
        ]
        shared_info = existing_graph.shared_parameters or {}
        prompt = (
            f"You are the Architect Planner Agent. The user wants to iterate on an existing mechanical assembly.\n\n"
            f"Existing Assembly Name: {existing_graph.name}\n"
            f"Existing Mechanism Type: {existing_graph.mechanism_type}\n"
            f"Existing Shared Parameters: {json.dumps(shared_info)}\n"
            f"Existing Parts:\n{json.dumps(parts_info, indent=2)}\n\n"
            f"User Modification Request:\n{user_feedback}\n\n"
            f"Determine which part(s) need changes and what specific instructions to give each part designer. "
            f"If shared dimensions (center distances, matching hole/shaft sizes, wall thickness) must change, include them in 'updated_shared_parameters'. "
            f"Respond ONLY with raw JSON matching this schema:\n"
            f"{{\n"
            f'  "affected_parts": ["part_id_1"],\n'
            f'  "part_instructions": {{"part_id_1": "specific instructions for modifying part_1"}},\n'
            f'  "updated_shared_parameters": {{"param_name": 12.0}},\n'
            f'  "summary": "brief summary of changes"\n'
            f"}}"
        )
        messages = [
            {"role": "system", "content": "You are the Architect Planner Agent for ForgeAgent. Respond ONLY with valid JSON, no markdown fences."},
            {"role": "user", "content": prompt}
        ]
        response_text = await self.gateway.complete(messages, temperature=0.1)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.index("\n")
            cleaned = cleaned[first_nl + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        return json.loads(cleaned)
