"""
Planner Agent (Architect).
Decomposes user text prompt into a structured AssemblyGraph JSON requirement
using LLM inference. NO hardcoded fallbacks — the LLM does all the thinking.
"""

import json
from typing import Optional, List, Dict, Any
from orchestrator.gateway_client import GatewayClient, LLMAPIError
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


PLANNER_SYSTEM_PROMPT = """You are the Architect Planner Agent for ForgeAgent, a multi-agent mechanical CAD system.

Your job: Decompose the user's plain-English mechanical design prompt into a structured AssemblyGraph JSON.

## Output Schema (respond ONLY with raw JSON, no markdown fences):

{
  "name": "short_snake_case_assembly_name",
  "description": "the user's original spec",
  "mechanism_type": "string describing mechanism (e.g., gearbox, linkage, enclosure, bracket_assembly, linear_stage, etc.)",
  "shared_parameters": {
    "key_dimension_or_ratio_name": 10.0,
    "matching_interface_diameter": 6.0,
    "center_to_center_distance": 30.0
  },
  "parts": [
    {
      "id": "part_1",
      "name": "descriptive_part_name",
      "description": "what this part is and its function",
      "part_type": "string describing component type",
      "manufacturing_process": "3d_printing | cnc_machining | sheet_metal",
      "verification_depth": "concept | functional | manufacturing | assembly_ready",
      "length": 50.0,
      "width": 30.0,
      "height": 40.0,
      "hole_diameter": 5.3,
      "wall_thickness": 2.0,
      "mates": [
        {
          "partner_id": "part_2",
          "mate_type": "hole_shaft | shaft_hole | face_face | edge_edge",
          "my_feature_name": "feature_name",
          "my_feature_diameter": 5.3,
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

## Rules:
1. First-Principles Engineering Reasoning:
   - Reason through the mechanical physics, motion, and dimensions dynamically for whatever mechanism is requested.
   - Do NOT assume a specific mechanism type. Calculate ratios, center distances, and envelopes directly from the user's prompt requirements.
   - Mechanism Completeness: Include all essential functional components needed to transmit power and complete the kinematic loop. For example, for a planetary/epicyclic gearbox, include the sun gear, planet gear (specify `num_planets: 3` in `shared_parameters`), ring gear casing, and the planet carrier plate (with pins to support the planets and an output shaft).
2. Shared Parameters (Top-Down Consistency):
   - Populate `shared_parameters` with any global design constants that multiple parts must agree on (e.g. center distances, matching shaft/bore sizes, pitch, wall thicknesses).
   - Ensure mating features between parts share identical or clearance-offset dimensions.
3. Manufacturing Process Detection:
   - If prompt mentions "machining", "machined", "cnc", or "milled", set manufacturing_process = "cnc_machining".
   - If prompt mentions "sheet metal", "laser", "bend", or "gauge", set manufacturing_process = "sheet_metal".
   - Fasteners default to "cnc_machining". Otherwise default to "3d_printing".
4. Standard Fits & Tolerances:
   - Running / clearance fit (shaft into hole, pin into bore): ALWAYS ensure mating hole diameter is strictly larger than mating shaft diameter (e.g. hole=5.2mm, shaft=5.0mm for a 0.2mm clearance fit; NEVER specify shaft diameter larger than hole).
   - Fastener clearance: M3 -> 3.4mm, M4 -> 4.3mm, M5 -> 5.3mm, M6 -> 6.4mm.
5. Realistic Envelopes:
   - Dimensions (`length`, `width`, `height`) must represent the physical outer 3D bounding box in mm.
   - For an internal ring gear / casing: The physical outer diameter (length/width) must accommodate the internal teeth plus solid casing wall: set outer diameter (length/width) >= D_pitch + 25mm so that mounting holes do not sever the teeth roots or breach outer walls.
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
