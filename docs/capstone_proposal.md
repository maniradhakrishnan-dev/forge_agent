# Capstone Proposal: ForgeAgent — Ground-Up Multi-Agent System for Mechanical CAD Design & Assembly

> [!IMPORTANT]
> **Core Architecture:** ForgeAgent is built completely from the ground up using a **custom multi-agent Live Graph engine** without third-party frameworks. It combines CadQuery Python scripting, OpenCascade kernel verification, Model Context Protocol (MCP) tool servers, Agent-to-Agent (A2A) protocol messaging, and dynamic Agent-to-User Interface (A2UI) event streaming.

---

## 1. Problem Statement

Text-to-CAD generation is a rapidly evolving frontier. While modern LLMs generate single parts with moderate fidelity, **multi-part assemblies with verified tolerances, kinematic motion, and manufacturing constraints remain unsolved industry-wide**. Adjacent platforms (e.g., Leo AI) focus heavily on retrieving existing validated parts from libraries rather than generating new geometry from scratch, specifically because generation-with-verification is hard.

**ForgeAgent directly addresses this gap through an end-to-end, verification-driven multi-agent harness.**

---

## 2. Project Goal

> Given a plain-English mechanism spec, ForgeAgent dynamically generates individual CadQuery parts, verifies single-part DFM and topology ground truth, positions them into assemblies with kinematic joints, and verifies multi-part fits and motion sweeps — emitting a live execution graph as ground-truth verifications pass.

*Analysis (FEA) is explicitly out of scope for the core deliverable — reserved as a stretch goal.*

---

## 3. Verification Definition (Computed Ground Truth)

Pass/fail verdicts are computed strictly from OpenCascade kernel geometry math — **never vibes-based LLM judgment**:

1. **Single-Part DFM & Topology:**
   - **Solid Manifold Check:** `val().isSolid() == True`, volume $> 0$, watertight topology.
   - **3D Printing DFM Rules:** Minimum wall thickness ($\ge 1.5\text{mm}$), hole diameters ($\ge 2.0\text{mm}$), unsupported overhang angles ($\le 45^\circ$).
   - **Dimensional Compliance:** Bounding box check against spec targets.

2. **Assembly Fits & Kinematics:**
   - **Interference:** Common intersection volume between all part pairs must equal $0\text{ mm}^3$.
   - **Fit Tolerance:** Clearance between mating features (shaft vs. bore, bolt vs. hole) falls within defined numeric bounds ($0.1\text{mm} \le \Delta \le 0.3\text{mm}$).
   - **Kinematic Motion Sweep:** Steps joint parameters across full motion range (e.g. $360^\circ$ crank rotation), verifying zero collision across the trajectory.

---

## 4. Ground-Up Multi-Agent Architecture

ForgeAgent uses a 6-agent modular structure coordinated by a custom event-driven engine:

```
                       [ Plain English Spec ]
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
                 │ (Interference, Fit & Kinematics)
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

## 5. Protocol Integrations (Course Alignment)

- **MCP (Model Context Protocol):** Exposes CadQuery execution sandboxes and OpenCascade geometry verifiers as standardized MCP tool servers.
- **A2A (Agent-to-Agent Protocol):** Structured JSON task delegation and diagnostic failure payload passing between agents.
- **A2UI (Agent-to-User Interface):** Real-time event streaming of live graph states and Three.js 3D assembly visualizer.
- **Markdown-as-Code Skills:** Modular skill injections (`skills/`) providing CadQuery modeling idioms, 3D printing DFM rules, and ISO tolerance standards.

---

## 6. Test Priority Ladder

| Priority | Test Case | What It Proves |
|---|---|---|
| **P0** | Single bracket with clearance holes | Basic part generation, DFM verification, dimensional accuracy |
| **P0** | Bolt + Nut pair | Standard part generation, thread/fit clearance verification |
| **P0** | Bracket + Bolt assembly | Multi-part placement, hole alignment, fit verification |
| **P1** | Crank-Slider mechanism (3-4 parts, pin joints) | Multi-part assembly, kinematic motion sweep, collision-free trajectory |
| **P2 (Stretch)**| 2D Orthographic Drawings (HLR) | Manufacturing 2D SVG/PDF projections |
| **P2 (Stretch)**| Motor mount + imported STEP motor | Real-world STEP part integration & mounting verification |
| **P2 (Stretch)**| Spur gear pair | Center-distance calculation & gear meshing verification |

---

## 7. 4-Week Execution Plan

- **Week 1 (Local Foundation):** Custom harness setup, MCP server implementations for CadQuery & OpenCascade, Part Designer + Part Critic agents running P0 single bracket case.
- **Week 2 (Multi-Part & Live Graph):** Live Graph event engine, Assembly Agent + Assembly Critic running bolt+nut and bracket+bolt assembly cases.
- **Week 3 (Kinematics & Cloud Deployment):** Crank-slider mechanism (P1) with kinematic motion sweep. AWS ECS Fargate deployment, S3 artifact bucket, RDS logging.
- **Week 4 (Eval & A2UI Visualizer):** MUSE-aligned benchmark evaluation suite, A2UI web UI integration (Live Graph view + Three.js 3D assembly viewer), capstone presentation prep.
