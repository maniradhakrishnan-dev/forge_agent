# ForgeAgent: Ground-Up Multi-Agent System for Mechanical CAD & Assembly

> **AI-Driven Parametric CAD Generation with Computed Geometric Verification, Live Graph Emission, and Protocol-First Architecture.**

---

## 📌 Executive Summary

While standard Text-to-CAD models generate simple single parts, **multi-part assemblies with verified tolerances, kinematic motion, and manufacturability remain an unsolved problem**. 

**ForgeAgent** addresses this gap by combining **CadQuery Python scripting**, **OpenCascade kernel math**, and a **custom ground-up multi-agent Live Graph engine**. Given a plain-English mechanism description, ForgeAgent dynamically generates individual parts, verifies DFM and topology ground truth, positions parts into assemblies with kinematic joints, and verifies interference and motion sweeps — emitting a dynamic execution graph as ground-truth checks pass.

---

## 🏗️ Multi-Agent Live Graph Architecture

ForgeAgent uses **zero third-party agent frameworks** (no LangGraph/AutoGen). The entire multi-agent orchestration, state machine, and **Live Graph DAG engine** are built from the ground up in Python.

```
                         [ Plain English User Spec ]
                                      │
                                      ▼
                      ┌──────────────────────────────┐
                      │    1. Architect / Planner    │
                      │ (Spec Decomposition & Graph) │
                      └──────────────┬───────────────┘
                                     │
                        Emits Initial Part Specs (JSON)
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │    2. Part Designer Agent    │
                      │   (Writes CadQuery scripts)  │
                      └──────────────┬───────────────┘
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │     3. Part Critic Agent     │
                      │ (Single-Part DFM & Geometry) │
                      └──────────────┬───────────────┘
                                     │
                    [PASS] Emits Part Node to Live Graph
                    [FAIL] Emits Repair Edge to Part Designer
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │      4. Assembly Agent       │
                      │  (Mating features & joints)  │
                      └──────────────┬───────────────┘
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │   5. Assembly Critic Agent   │
                      │ (Interference, Fit & Motion) │
                      └──────────────┬───────────────┘
                                     │
                    [PASS] Emits Assembly Node & STEP/STL
                    [FAIL] Emits Targeted Repair Edge
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │  6. Live Graph Orchestrator  │
                      │  (Event-Driven Engine & A2UI)│
                      └──────────────────────────────┘
```

---

## 🚀 Key Architectural Innovations

### 1. Live Graph Emission Engine (Dynamic DAG)
Unlike static pipelines that assume one-shot success, ForgeAgent's **Live Graph Engine** does not hardcode the execution graph upfront. Nodes and edges are emitted dynamically based on real OpenCascade ground-truth verdicts:
- **Part Nodes** are appended as the Architect decomposes the spec.
- **Repair Nodes** are emitted dynamically when a Critic detects a DFM or tolerance issue.
- **Assembly Nodes** are emitted only after all constituent parts pass single-part ground truth.

### 2. Protocol-First Foundation
- 🛠️ **MCP (Model Context Protocol):** CadQuery code execution sandboxes and OpenCascade geometry verification suites (`check_interference`, `check_fit`, `check_motion`, `check_dfm`) are exposed as standardized MCP tool servers.
- 🤝 **A2A (Agent-to-Agent Protocol):** Structured JSON task delegation and diagnostic failure payload passing between specialized agents.
- 📺 **A2UI (Agent-to-User Interface):** Real-time event streaming powering a web visualizer with live graph updates and Three.js 3D assembly rendering.
- 📚 **Markdown-as-Code Skills (`skills/`):** Injection of CadQuery modeling patterns, 3D printing DFM rules, and ISO tolerance lookup tables as modular skill files.

---

## 🔬 Ground-Truth Verification Matrix

Pass/fail verdicts are computed strictly from OpenCascade kernel geometry math — **never qualitative vibes**:

| Verification Check | Target Criteria | Method |
|---|---|---|
| **Solid Manifold** | Watertight solid, `isSolid() == True`, Volume $> 0$ | OpenCascade Shape Analysis |
| **3D Print DFM** | Min wall $\ge 1.5\text{mm}$, Min hole $\ge 2.0\text{mm}$, Overhang $\le 45^\circ$ | OCP Section Sampling & Surface Normals |
| **Interference** | Intersecting solid volume $= 0\text{ mm}^3$ between all part pairs | OpenCascade Boolean Section (`intersect`) |
| **Fit Clearance** | Mating gap falls within target range ($0.1\text{mm} \le \Delta \le 0.3\text{mm}$) | OpenCascade Distance Extrema (`DistShapeShape`) |
| **Kinematic Motion Sweep**| $0$ collision across full motion trajectory (e.g. $360^\circ$ crank rotation) | Trajectory Sampled Interference Sweep |

---

## 🎯 Test Priority Ladder

- **P0 (Single-Part & Basic Assembly):**
  1. Single bracket with mounting holes (CadQuery script $\rightarrow$ DFM pass $\rightarrow$ STEP export).
  2. Bolt + Nut fit pair (thread clearance verification).
  3. Bracket + Bolt assembly (hole alignment & fit verification).
- **P1 (Core Kinematic Differentiator):**
  - Crank-Slider mechanism (3-4 parts, pin joints, kinematic motion sweep over $360^\circ$ collision-free).
- **P2 (Stretch Goals):**
  - 2D orthographic technical drawings via OpenCascade HLR (SVG/PDF export).
  - Motor mount with imported STEP motor integration.
  - Spur gear pair with center-distance meshing verification.

---

## 📂 Repository Directory Layout

```
├── AGENT.md                 # Developer & LLM agent guidelines
├── README.md                # Project documentation hub (this file)
├── pyproject.toml           # uv-managed dependencies & package configuration
├── docs/                    # Deep dive documentation
│   ├── capstone_proposal.md # Formal 4-week capstone proposal
│   └── sota_aicad.md        # August 2026 SOTA research survey & benchmarks
├── orchestrator/            # Custom event-driven Live Graph engine & A2A dispatcher
├── tools/                   # MCP Tool Servers (cad_kernel, verify, render_hlr)
├── skills/                  # Markdown-as-Code skill definitions (CadQuery, DFM, tolerances)
├── eval/                    # Benchmark specs (MUSE-aligned) & run logger
├── tests/                   # Unit & integration test suite (uv run pytest)
├── infra/                   # AWS ECS Fargate & Docker container deployment
└── web/                     # A2UI web UI (Live Graph DAG & Three.js 3D viewer)
```

---

## 💻 How to Run the Loop

Manage dependencies and execute the loop using **`uv`**:

### 1. Run the Main CAD Generation & Verification Loop
```bash
uv run python main.py --prompt "Single mounting bracket 40x30x10mm with two 4.3mm clearance holes"
```

### 2. Run the Automated Integration Test Suite
```bash
uv run pytest
```

---

## 📖 Navigation & Documentation

- Read the full [Capstone Proposal](file:///home/mani_radhakrishnan/capv1_mech_design/docs/capstone_proposal.md) for timeline and eval details.
- Review the [State of the Art Survey](file:///home/mani_radhakrishnan/capv1_mech_design/docs/sota_aicad.md) for citable benchmarks (MUSE, Text2CAD-Bench) and competitive positioning.
- Consult [AGENT.md](file:///home/mani_radhakrishnan/capv1_mech_design/AGENT.md) for coding conventions and stack constraints.
