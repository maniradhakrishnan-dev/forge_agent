# AGENT.md

Instructions for coding agents working on **ForgeAgent**.
Read this FULLY before writing ANY code. This is your single source of truth.

---

## 1. Core Value & Philosophy

**ForgeAgent** is a training-free, ground-up multi-agent system for **verification-driven mechanical CAD design & assembly**.

**Core Value:** Given a plain-English spec, generate CadQuery parts, verify them against computed OpenCascade ground truth (DFM, topology, dimensional compliance), assemble them with verified fits & kinematics, and repair failures through targeted diagnostic loops. Everything else is a feature built on top of this verified foundation.

### Non-Negotiable Rules
- **No Third-Party Agent Frameworks.** Build everything from scratch in Python. Do NOT use LangGraph, AutoGen, CrewAI, or similar.
- **Async-First Python (`asyncio`).** All agent handlers, orchestrators, and tool calls use `async`/`await`.
- **Package Management with `uv`.** All dependencies via `uv` (`uv venv`, `uv sync`, `uv run`). Never `pip install`.
- **Ground Truth = Computed Geometry.** Pass/fail verdicts come ONLY from OpenCascade math checks (`python-OCP`). Never vibes-based LLM judgment.
- **Live Graph Emission.** Nodes emitted reactively as ground truth is proven. Never pre-plan a static DAG.
- **Strict Pydantic Contracts.** Every agent input and output is a Pydantic `BaseModel`. No loose dicts or untyped strings crossing agent boundaries.
- **No Gateway Server.** LLM calls use direct API via `httpx` + `.env` API keys. No `glc_v3` or separate server process.

---

## 2. Current Project State

### What EXISTS and WORKS
| Component | Status | File |
|---|---|---|
| CadQuery Sandbox (execute + export STEP/STL) | ✅ Working | `tools/cad_kernel.py` |
| Single-Part DFM Verifier (manifold, wall, holes) | ✅ Working (partial) | `tools/verify_single_part.py` |
| Planner Agent (text → PartSpec) | ✅ Working (offline fallback) | `orchestrator/agents/planner_agent.py` |
| Code Generator Agent (spec → CadQuery code) | ✅ Working (offline fallback) | `orchestrator/agents/code_generator_agent.py` |
| Verification Agent (runs DFM checks) | ✅ Working | `orchestrator/agents/verification_agent.py` |
| Repair Agent (formats failure → repair prompt) | ✅ Working | `orchestrator/agents/repair_agent.py` |
| Single-Part Pipeline | ✅ Working | `orchestrator/part_pipeline.py` |
| Gateway Client (offline mock fallback) | ✅ Working (mock only) | `orchestrator/gateway_client.py` |
| Skills (CadQuery + DFM) | ✅ Created | `skills/cadquery_modeling/`, `skills/dfm_3d_printing/` |

### What NEEDS to be built (see Implementation Plan)
| Component | Priority | Notes |
|---|---|---|
| `orchestrator/models.py` — Pydantic contracts for ALL agents | Phase A | PartSpec, MatingContext, AssemblyGraph, InterfacePort, DesignerOutput, VerificationVerdict, AssemblyVerdict, RepairInstruction, RunEntry |
| Real LLM wiring (direct Gemini/Anthropic via `.env` + `httpx`) | Phase A | Priority chain: GEMINI_API_KEY → ANTHROPIC_API_KEY → offline fallback |
| Hardened DFM verifiers (hole detection fix, overhang, bbox) | Phase A | `tools/verify_single_part.py` |
| Structured Run Logger | Phase A | `orchestrator/run_logger.py` |
| Assembly-aware Planner (emits `AssemblyGraph` with `MatingContext`) | Phase B | `orchestrator/agents/planner_agent.py` |
| Constraint Consistency Validator | Phase B | `orchestrator/constraint_validator.py` |
| Designer outputs `InterfacePorts` | Phase B | `orchestrator/agents/code_generator_agent.py` |
| Assembly Verifier (interference, clearance, kinematic sweep) | Phase C | `tools/verify_assembly.py` |
| Assembly Agent, Assembly Critic, Assembly Repair (Diagnostic Router) | Phase C | `orchestrator/agents/assembly_agent.py`, `assembly_critic_agent.py`, `assembly_repair_agent.py` |
| Live Graph Engine | Phase D | `orchestrator/live_graph/` |
| P0/P1 test cases + eval benchmark | Phase D | `tests/`, `eval/` |

---

## 3. Architecture: 8 Agents + 1 Validator

```
Text Input → Planner → [Constraint Validator] → Parallel Part Design Loops → Assembly → Reporter

Per-Part Loop:  Designer → Sandbox → Part Critic → (Part Repair → Designer)* → ✅ Verified Part
Assembly Loop:  Assembly Agent → Assembly Critic → (Assembly Repair Router)* → ✅ Verified Assembly
```

### The 8 Agents

| # | Agent | Class Name | Python File | Uses LLM? | Role |
|---|---|---|---|---|---|
| 1 | **Planner** (Architect) | `PlannerAgent` | `planner_agent.py` | ✅ YES | Decomposes prompt → `AssemblyGraph` |
| 2 | **Part Designer** (Code Gen) | `CodeGeneratorAgent` | `code_generator_agent.py` | ✅ YES | Generates CadQuery code + `InterfacePort[]` |
| 3 | **Part Verifier** (Inspector) | `PartVerifierAgent` | `part_verifier_agent.py` | ❌ NO | Runs 6-pillar OpenCascade DFM checks |
| 4 | **Part Repair** (Formatter) | `PartRepairAgent` | `part_repair_agent.py` | ❌ NO | Formats DFM failure prompt back to Designer |
| 5 | **Assembly** (Assembler) | `AssemblyAgent` | `assembly_agent.py` | ✅ YES / Math | Positions verified parts in `cq.Assembly()` |
| 6 | **Assembly Verifier** (Inspector) | `AssemblyVerifierAgent` | `assembly_verifier_agent.py` | ❌ NO | Runs interference, clearance, kinematics |
| 7 | **Assembly Repair** (Router) | `AssemblyRepairAgent` | `assembly_repair_agent.py` | ✅ YES / Rules | Diagnoses fault type & routes repair |
| 8 | **Reporter** (Exporter) | `ReporterAgent` | `reporter_agent.py` | ❌ NO | Exports STEP/STL & writes `run_log.jsonl` |

### Key Architectural Concepts

- **MatingContext:** Each part knows its assembly mates BEFORE code generation. If standalone (0 mates), design freely. If mated, Designer reads MatingContext to place features at coordinated positions.
- **InterfacePort:** Named mating feature positions (name, xyz position, face normal, diameter) exported by Designer. Assembly Agent uses these to mate parts deterministically.
- **Constraint Validator:** Runs AFTER Planner, BEFORE design loops. Catches inconsistent mate dimensions (e.g., hole_d - shaft_d ≠ clearance) before wasting design iterations.
- **Two-Level Repair:** Part Repair always routes back to same part's Designer. Assembly Repair diagnoses geometry vs positioning fault and routes to specific Part Designer OR Assembly Agent.
- **Escalation:** 5 repair retries exhausted → escalate to Planner for re-decomposition. Max 2 planner re-plans before hard fail.

---

## 4. LLM Interaction Pattern Per Agent

### Which Agents Call the LLM

Only 4 of 8 agents call the LLM. The other 4 are deterministic (pure OpenCascade math or template formatting).

---

### Agent 1: PLANNER (Architect) — LLM Call

**System Prompt:**
```
You are the Architect Planner Agent for ForgeAgent, a mechanical CAD multi-agent system.
Decompose the user's plain-English spec into a structured AssemblyGraph JSON.

Rules:
- For standalone parts: return 1 part with mates=[]
- For assemblies: return multiple parts, each with MatingContext specifying partner, mate_type, feature dimensions, clearance
- Define JointDef for each connection (rigid, revolute, prismatic)
- Respond ONLY with raw JSON matching the AssemblyGraph schema
```

**User Message:**
```
User Spec: {prompt}
Target Schema: AssemblyGraph JSON
```

**Expected LLM Output:** Raw JSON matching `AssemblyGraph` Pydantic model
```json
{
  "parts": [
    {"id": "bracket", "spec": {"length": 40, "width": 30, ...}, "mates": [{"partner": "bolt", "type": "hole_shaft", "my_feature_diameter": 4.3, "clearance": 0.15}]},
    {"id": "bolt", "spec": {...}, "mates": [{"partner": "bracket", "type": "shaft_hole", "my_feature_diameter": 4.0}]}
  ],
  "joints": [{"type": "rigid", "part_a": "bracket", "part_b": "bolt"}]
}
```

**Fallback (no LLM):** Regex-based prompt parser extracts dimensions and part type keywords.

---

### Agent 2: DESIGNER (Code Generator) — LLM Call

**System Prompt:**
```
You are the Part Designer Agent for ForgeAgent.
Write self-contained CadQuery Python code defining a single solid part.

Rules:
- MUST define a top-level variable `result` of type cq.Workplane
- Read the PartSpec dimensions and MatingContext carefully
- Place mating features (holes, shafts, slots) at exact positions from MatingContext
- Export InterfacePorts as a comment block: # INTERFACE: name=(x,y,z) dir=(nx,ny,nz) type=hole d=4.3
- Respond ONLY with raw Python code

{skills/cadquery_modeling/SKILL.md content injected here}
```

**User Message:**
```
Part Spec:
{spec.model_dump_json(indent=2)}

Mating Context:
{mates json}

{if repair attempt: "PREVIOUS ATTEMPT FAILED: {repair_instruction}"}
```

**Expected LLM Output:** Raw Python CadQuery code
```python
import cadquery as cq

# INTERFACE: hole_center_1=(10,15,5) dir=(0,0,1) type=hole d=4.3
result = (
    cq.Workplane("XY")
    .box(40, 30, 10)
    .faces(">Z").workplane().center(10, 15)
    .hole(4.3)
)
```

**Fallback (no LLM):** Template-based CadQuery generator using `_generate_part_by_type()` method.

---

### Agent 3: PART CRITIC — NO LLM (Pure Math)

Does NOT call LLM. Runs deterministic OpenCascade checks:
- `check_solid_manifold()` → `isSolid()`, `Volume() > 0`
- `check_dfm_wall_thickness()` → min bbox dimension ≥ 1.5mm
- `check_dfm_hole_diameter()` → cylindrical face radii ≥ 2.0mm
- `check_dfm_overhang_angle()` → unsupported angle ≤ 45°
- `check_bounding_box()` → actual vs spec within tolerance

Returns `VerificationVerdict(passed=bool, diagnostics=[DFMDiagnostic(...)])`.

---

### Agent 4: PART REPAIR — NO LLM (Template Formatter)

Does NOT call LLM. Reads failed `DFMDiagnostic` entries and formats a string:
```
The previous CadQuery script failed:
- [DFM-01] min_wall_thickness: Measured 1.2mm, Required 1.5mm
- [DFM-02] min_hole_diameter: Measured 1.8mm, Required 2.0mm
Please adjust CadQuery code to fix these exact failures.
```

This string becomes the `repair_prompt` passed back to Designer Agent on next iteration.

---

### Agent 5: ASSEMBLY AGENT — LLM Call (or deterministic)

**System Prompt:**
```
You are the Assembly Agent for ForgeAgent.
Position verified parts into a cq.Assembly() using their InterfacePorts.

Rules:
- Mate InterfacePorts by aligning positions and directions
- Apply coordinate transforms via cq.Location
- Apply JointDef constraints
- Respond ONLY with raw Python code using cq.Assembly()
```

**User Message:**
```
Parts and InterfacePorts:
bracket: hole_center_1=(10,15,5) dir=(0,0,1) type=hole d=4.3
bolt:    shaft_tip=(0,0,0) dir=(0,0,1) type=shaft d=4.0

Joint: rigid between bracket and bolt

{if repair: "PREVIOUS POSITIONING FAILED: {repair_instruction}"}
```

**Can also be deterministic:** Compute transform from InterfacePort positions directly (translate bolt origin to bracket hole center).

---

### Agent 6: ASSEMBLY CRITIC — NO LLM (Pure Math)

Does NOT call LLM. Runs deterministic OpenCascade checks:
- `check_interference()` → boolean intersection volume = 0 mm³
- `check_fit_clearance()` → BRepExtrema distance ∈ [0.1, 0.3]mm
- `check_kinematic_sweep()` → step joint angle 0°→360°, 0 collisions

Returns `AssemblyVerdict(passed=bool, diagnostics=[AssemblyDiagnostic(...)])`.

---

### Agent 7: ASSEMBLY REPAIR (Diagnostic Router) — LLM Call (or rule-based)

**System Prompt:**
```
You are the Assembly Repair Agent for ForgeAgent.
Given an assembly failure diagnostic, determine the root cause.

Rules:
- If a part's feature dimension causes interference/clearance failure → GEOMETRY_FAULT → target the specific part's Designer
- If parts are positioned wrongly (wrong transform/rotation) → POSITIONING_FAULT → target Assembly Agent
- Respond ONLY with JSON: {"fault_type": "geometry|positioning", "target_part_id": "...", "repair_prompt": "..."}
```

**User Message:**
```
Assembly Verdict (FAILED):
- Interference between bracket and bolt: overlap volume = 2.3mm³
- Bracket hole diameter: 4.3mm, Bolt shaft diameter: 4.5mm
- Expected clearance: 0.15mm, Actual: -0.1mm (interference)
```

**Expected Output:**
```json
{"fault_type": "geometry", "target_part_id": "bolt", "repair_prompt": "Reduce bolt shaft diameter from 4.5mm to 4.0mm to achieve 0.15mm clearance with 4.3mm bracket hole"}
```

**Can also be rule-based:** If `shaft_d > hole_d` → geometry fault on the shaft part.

---

### Agent 8: REPORTER — NO LLM (Template Formatter)

Does NOT call LLM. Deterministic operations:
- Calls `export_cad_artifacts()` to write STEP + STL files
- Formats verification summary report
- Writes `RunEntry` to structured run log (JSONL)
- Emits final PASS node to Live Graph

---

## 5. LLM Wiring (`.env` + Direct API)

**No gateway server.** `gateway_client.py` reads API keys from `.env` and calls providers directly:

```
Priority chain:
1. GEMINI_API_KEY set?     → POST to generativelanguage.googleapis.com
2. ANTHROPIC_API_KEY set?  → POST to api.anthropic.com
3. OPENAI_API_KEY set?     → POST to api.openai.com
4. Nothing set?            → Offline fallback (template-based generation)
```

`.env` file:
```
GEMINI_API_KEY=your_key_here
# ANTHROPIC_API_KEY=your_key_here
# OPENAI_API_KEY=your_key_here
```

---

## 6. Tech Stack (Locked)

- **Language:** Python 3.11+ (async/await)
- **CAD Scripting:** CadQuery 2.x (`cadquery`)
- **Geometry Kernel:** OpenCascade (OCCT) via `python-OCP`
- **LLM Access:** Direct API via `httpx` + `.env` keys (Gemini, Anthropic, OpenAI)
- **Data Contracts:** Pydantic v2 `BaseModel` at every boundary
- **Package Manager:** `uv` exclusively
- **Agent Communication:** In-process Pydantic model passing (no HTTP between agents)

---

## 7. Scope Boundaries

### ✅ Core Scope (Build This)
- Verified single part generation (CadQuery + OpenCascade DFM)
- Verified multi-part assembly (interference, fit clearance, kinematic sweep)
- Assembly-aware part design (MatingContext + InterfacePorts)
- Constraint Consistency Validator
- Two-level repair (Part Repair + Assembly Repair Diagnostic Router)
- Escalation policy (retry exhaustion → Planner re-decomposition)
- Live Graph (reactive node emission)
- Structured Run Log

### 🔮 Stretch / Future (NOT now)
- Standard parts catalog (ISO fasteners)
- MCP tool server wrapping
- A2A protocol (distributed agents)
- A2UI web visualizer (SSE + Three.js)
- Third-party STEP import
- FEA / structural analysis
- 2D orthographic drawings
- Cloud deployment

---

## 8. Repository Structure

```
capv1_mech_design/
├── main.py                    # CLI entry point
├── pyproject.toml             # uv dependencies (cadquery, pydantic, httpx, pytest)
├── .env                       # API keys (GEMINI_API_KEY, etc.) — gitignored
├── AGENT.md                   # THIS FILE — read first
├── README.md                  # Project overview
│
├── orchestrator/              # Multi-agent pipeline & orchestration
│   ├── models.py              # [TO BUILD] ALL Pydantic contracts
│   ├── gateway_client.py      # LLM client (direct API + offline fallback)
│   ├── constraint_validator.py # [TO BUILD] Pre-design consistency check
│   ├── run_logger.py          # [BUILT] Structured JSONL run log
│   ├── part_pipeline.py       # [BUILT] Single-part design→verify→repair loop
│   ├── assembly_pipeline.py   # [BUILT] Multi-part assembly pipeline
│   ├── iteration_pipeline.py  # [BUILT] Human-in-the-loop revision pipeline
│   ├── agents/
│   │   ├── planner_agent.py           # [EXISTS] Text → PartSpec (upgrade to AssemblyGraph)
│   │   ├── code_generator_agent.py    # [EXISTS] Spec → CadQuery code (add InterfacePorts)
│   │   ├── verification_agent.py      # [EXISTS] Runs DFM checks
│   │   ├── repair_agent.py            # [EXISTS] Formats failures → repair prompt
│   │   ├── assembly_agent.py          # [TO BUILD] Positions parts via InterfacePorts
│   │   ├── assembly_critic_agent.py   # [TO BUILD] Assembly verification
│   │   ├── assembly_repair_agent.py   # [TO BUILD] Diagnostic Router
│   │   └── reporter_agent.py          # [TO BUILD] Export + logging
│   └── live_graph/            # [TO BUILD] Reactive Live Graph Engine
│       ├── models.py          # GraphNode, GraphEdge, GraphPatch
│       ├── store.py           # In-memory graph state
│       ├── executor.py        # Async event loop
│       └── cad_planner.py     # CAD-specific graph planning
│
├── tools/                     # OpenCascade geometry tools (ground truth)
│   ├── cad_kernel.py          # [EXISTS] CadQuery sandbox + STEP/STL export
│   ├── verify_single_part.py  # [EXISTS] Single-part DFM checks (needs hardening)
│   └── verify_assembly.py     # [TO BUILD] Multi-part assembly checks
│
├── skills/                    # Domain knowledge injection
│   ├── cadquery_modeling/SKILL.md    # [EXISTS] CadQuery patterns
│   ├── dfm_3d_printing/SKILL.md     # [EXISTS] DFM rules
│   └── assembly_mating/SKILL.md     # [TO BUILD] Assembly conventions
│
├── tests/                     # Test suite
├── eval/                      # Benchmark specs & runner
├── artifacts/                 # Generated STEP/STL outputs
├── docs/                      # Documentation
│   ├── capstone_proposal.md
│   └── architecture.md        # Full architecture diagram
└── my_working_md/             # Personal working notes
```

---

## 9. Priority Ladder (Test Cases)

| Priority | Test Case | What It Proves |
|---|---|---|
| **P0** | Single bracket with clearance holes | Part generation, DFM verification, STEP export |
| **P0** | Bolt + Nut pair | Standard part gen, fit clearance verification |
| **P0** | Bracket + Bolt assembly | Multi-part placement, hole alignment, fit verification |
| **P1** | Crank-Slider mechanism (3-4 parts) | Kinematic motion sweep, collision-free trajectory |

---

## 10. Reference Codebases (For Learning Only — NOT Dependencies)

- `/home/mani_radhakrishnan/TSAI_EAGV3_Session13/S13Code/` — Agent Runtime, Live Graph Engine pattern
- `/home/mani_radhakrishnan/TSAI_EAGV3_Session14/glc_v3/` — LLM Gateway pattern (we use direct API instead)
- `/home/mani_radhakrishnan/TSAI_EAGV3_Session14/S14Code/` — A2UI pattern (future scope)
