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

## Architectural Taste & Form Idioms (CRITICAL):
1. **Form Follows Function (Axisymmetric vs Prismatic Idioms)**:
   - **Rotating Transmissions & Gearboxes (Cycloidal, Planetary, Harmonic, Bearings)**:
     * Housings/Casings MUST be modeled as **cylindrical/annular bodies with circular bolt flanges (`geometry_form: "annular_flanged_casing"` or `"cylindrical_housing"`)**, NEVER raw rectangular boxes or slabs that waste material.
     * Shafts MUST be **stepped shafts (`geometry_form: "stepped_shaft"`)** with bearing journals, shoulders, and eccentric lobes.
     * Planet/Output Carriers MUST be **flanges with extruded drive pins/studs (`geometry_form: "pin_carrier_flange"`)**.
     * Discs/Gears MUST be **true analytical discs (`geometry_form: "cycloid_disc"` or `"spur_gear"`)**.
   - **Structural Brackets & Frames**:
     * Use ribbed L-brackets, webbed plates, or gusseted flanges (`geometry_form: "bracket"` or `"flanged_plate"`).

2. **Kinematic Invariants & Top-Down Invariant Math**:
   - You MUST compute and populate all kinematic relations into `shared_parameters` so downstream parts NEVER guess:
   - **Cycloidal Drives (e.g. Ratio = R:1)**:
     * `reduction_ratio`: R
     * `num_lobes` (disc): R (e.g. 10 lobes for 10:1)
     * `num_ring_pins` (housing): R + 1 (e.g. 11 pins for 10 lobes)
     * `eccentricity`: 1.5 to 3.0 mm (e.g. 2.0 mm)
     * `pin_ring_pcd`: Pitch diameter of stationary ring pins (e.g. 120.0 mm)
     * `pin_diameter`: Stationary ring pin roller diameter (e.g. 8.0 mm)
     * `carrier_pin_pcd`: Pitch circle diameter for output drive pins (e.g. 60.0 mm - MUST BE IDENTICAL in disc and carrier)
     * `output_pin_diameter`: Diameter of carrier drive pins (e.g. 6.0 mm)
     * `disc_carrier_hole_diameter`: output_pin_diameter + (2 * eccentricity) + 0.5 mm (oversized hole allowing orbital motion)
   - **Planetary Gearboxes**:
     * Invariant: `num_teeth_ring = num_teeth_sun + 2 * num_teeth_planet`
     * `module`: 1.5 - 3.0 mm
     * `center_distance`: module * (num_teeth_sun + num_teeth_planet) / 2
     * `num_planets`: 3 (or 4)
   - **Harmonic / Strain Wave Drives**:
     * Invariant: `num_teeth_circular_spline - num_teeth_flexspline = 2`
     * Flexspline marked `"is_compliant": true`

3. **Single-Part vs Multi-Part Mechanisms (CRITICAL)**:
   - If the user prompt requests a **standalone part, fastener, plate, bracket, dish, or single component** (e.g. "a bolt", "a nut", "an L-bracket", "a dining plate", "a pulley", "a spur gear"):
     * Do NOT arbitrarily split it into multiple sub-parts!
     * Set `"is_single_part": true`, with `parts` containing exactly 1 item and `joints: []`.
     * A bolt has its head and threaded shank modeled as **ONE monolithic part** (`geometry_form: "bolt"`).
     * A plate or bowl is **ONE monolithic part** (`geometry_form: "revolved_dish"`).
     * An L-bracket is **ONE monolithic part** (`geometry_form: "bracket"`).
   - Multi-part decomposition is ONLY for assemblies and mechanisms with distinct moving or separable parts (e.g. gearboxes, drives, linkages, bolted joint assemblies).

4. **Explicit Constraints vs Inferred Defaults (CRITICAL)**:
   - In `explicit_constraints`, extract ONLY numbers and dimensions that the user explicitly stated in their prompt (e.g. if prompt says '15mm dia and 50mm length and head 25mm', set `explicit_constraints: {"diameter": 15.0, "length": 50.0, "head_size": 25.0}`).
   - If the user prompt did NOT specify exact dimensions (e.g. 'Design a simple L bracket with mounting holes'), leave `explicit_constraints: {}` EMPTY! The `length`, `width`, `height` you provide will then serve as suggested proportions rather than rigid failure criteria.

## Output Schema (respond ONLY with raw JSON, no markdown fences):

{
  "name": "short_snake_case_assembly_name",
  "description": "the user's original spec",
  "mechanism_type": "single_part | cycloidal_drive | planetary_gearbox | harmonic_drive | linkage | bracket_assembly | fastener",
  "shared_parameters": {
    "reduction_ratio": 10.0,
    "num_lobes": 10,
    "num_ring_pins": 11,
    "eccentricity": 2.0,
    "pin_ring_pcd": 120.0,
    "pin_diameter": 8.0,
    "carrier_pin_pcd": 60.0,
    "output_pin_diameter": 6.0,
    "disc_carrier_hole_diameter": 10.5
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
      "length": 140.0,
      "width": 140.0,
      "height": 30.0,
      "hole_diameter": 6.0,
      "wall_thickness": 5.0,
      "explicit_constraints": {},
      "is_single_part": true,
      "is_compliant": false,
      "mates": [
        {
          "partner_id": "part_2",
          "mate_type": "hole_shaft | shaft_hole | face_face | edge_edge | gear_mesh",
          "my_feature_name": "feature_name",
          "my_feature_diameter": 6.0,
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
1. Single vs Multi-Part: Standalone parts (bolts, screws, nuts, brackets, plates, bowls) MUST be 1 part in `parts` and 0 joints in `joints`.
2. Mechanism Completeness: For multi-part assemblies, include all essential functional parts to complete the kinematic loop (e.g. cycloidal drive requires input eccentric shaft, cycloid disc, ring pin housing, and output pin carrier).
3. Shared Parameters (Top-Down Consistency): All shared diameters, pin counts, lobe counts, and pitch circle diameters MUST be declared in `shared_parameters` and matched across mating parts.
4. Axisymmetric Envelopes: For annular casings/flanges, `length` and `width` represent the outer flange diameter (e.g. 140.0 for a D=140mm circular flange).
5. Running / Clearance Fits: Mating holes must be strictly larger than mating shafts (hole = shaft + clearance).
6. Respond with ONLY the raw JSON object. No explanation, no markdown fences."""


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
        If validation_errors from ConstraintValidator are provided, feeds them back
        for self-correction.
        Raises PlannerParseError if the LLM response cannot be parsed.
        Raises LLMAPIError if the API call fails.
        """
        AgentToolbox.enforce("planner_agent", "gateway_client")

        user_content = f"Design Prompt: {prompt}"
        if validation_errors:
            user_content += (
                f"\n\n--- PREVIOUS ATTEMPT VALIDATION ERRORS ---\n"
                f"Your previous AssemblyGraph had the following consistency errors:\n"
                + "\n".join(f"- {err}" for err in validation_errors)
                + "\nPlease output a corrected AssemblyGraph JSON ensuring all part IDs match exactly, reciprocal mates exist, and mating clearances are consistent (hole diameter must be strictly larger than shaft diameter: hole = shaft + clearance)."
            )

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
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
