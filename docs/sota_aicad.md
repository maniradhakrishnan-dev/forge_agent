# sota_aicad.md — State of the Art: AI-Driven CAD Generation
*Compiled August 2026. This is the single home for all external research, benchmarks,
industry tools, and named papers/companies referenced by this project. `AGENT.md` and
`capstone_proposal.md` point here instead, to keep working context focused.*

---

## 1. Headline Finding

Across every industry tool, benchmark, and published system surveyed, the same
conclusion repeats independently: **AI can now generate a reasonable single CAD part
from text, and — as of 2026 — several published agentic systems can now do reasonable
multi-part assembly generation too.** What remains genuinely unsolved is **reliable,
geometry-verified manufacturability and assembly correctness at scale**, evaluated
against real numeric tolerances rather than qualitative judgment. That narrower gap is
this project's target — see Section 5 for the corrected, honest competitive read.

---

## 2. The Three Input→Output Approaches

| Approach | Input → Output | Precision-verifiable? | Used here? |
|---|---|---|---|
| **1. Code-driven (text)** | Text → parametric code → kernel → geometry | Yes | **Yes — this project's approach** |
| **2. Code-driven (scan/image)** | Point cloud / image → parametric code → kernel → geometry | Yes | Same output paradigm as (1), different front-end; not pursued now, natural future extension |
| **3. Direct 3D/mesh generation** | Text/image → raw mesh, no kernel | No — no guaranteed dimensions, no clean STEP export | Not used — structurally incompatible with tolerance/manufacturability verification |

Approaches 1 and 2 both ultimately produce the same class of artifact (a real
parametric B-rep solid via a geometry kernel) — the difference is only the input
modality. Approach 3 is a genuinely different, incompatible paradigm, used elsewhere
in industry only for visual/gaming assets or early-stage concept sketches where
dimensional accuracy doesn't matter.

---

## 3. Method Families (Generation Techniques)

```
1. Autoregressive command-sequence   — original paradigm, largely superseded
2. Diffusion-based                   — strong for CAD foundation models, not spec-driven
3. Code-generation, fine-tuned       — heavy SFT/RL, strong on in-distribution prompts,
                                        brittle on abstract/plain-English input
4. Code-generation, agentic/         — no fine-tuning; loop-based generate→verify→retry;
   training-free                       THIS PROJECT'S FAMILY
5. Part-token composition            — retrieval/reuse of existing validated parts,
                                        not generation of new geometry
6. Direct 3D/mesh generation         — not used in engineering CAD (see Section 2)
```

### Family 1 — Autoregressive command-sequence generation
Predicts CAD construction commands (sketch → extrude → boolean) token by token, like
a language model predicting words. DeepCAD originated this; SkexGen and HNC-CAD
(Hierarchical Neural Coding) added disentangled codebooks for controllability;
CAD-SIGNet added point-cloud conditioning. Known weakness: discrete token formats
over-compress representations and tend toward oversimplified results on complex
geometry.

### Family 2 — Diffusion-based generation
Denoising-based generation of sketches/B-rep structure, mostly unconditional or
lightly-conditioned — active 2025–2026 research area, but solving a different problem
than spec-driven generation.

- **BrepGen** — diffusion directly on structured B-rep latent geometry.
- **SketchDNN** — joint continuous-discrete diffusion for 2D sketches; new SOTA on
  FID/NLL for sketch generation.
- **BRep-GD** — graph diffusion model for B-rep generation.
- **GeoFusion-CAD** (2026) — Mamba-based state-space diffusion; new SOTA on long
  command sequences, an area where Transformer-based models degrade.

Relevance: mostly evaluated on distributional similarity to training data (COV, MMD,
JSD, FID), not on satisfying a specific engineering spec. No manufacturability or
assembly-verification claims found in this family.

### Family 3 — Code-generation, fine-tuned
Generates CadQuery/parametric code via heavy supervised + reinforcement fine-tuning on
large synthetic datasets.

| Method | Input | Training scale | Notes |
|---|---|---|---|
| CAD-Recode | Point cloud | Large synthetic corpus | Originating method for this lineage; output confirmed interpretable/editable by off-the-shelf LLMs |
| cadrille | Point cloud + image + text | 160K examples, SFT+RL | First unified multi-modal reconstruction; **known weakness: syntactically valid but semantically wrong output on abstract/non-expert text — poor generalization beyond expert-level training data** |
| CADFusion | Text | SFT + DPO on visual feedback | Alternates sequence-learning and visual-feedback (VLM-scored) training stages |
| Text2CadQuery | Text | 150K, SFT | |
| PR-CAD (2026) | Text | 150K, SFT+RL | |
| CAD-Coder | Text | 150K, SFT+RL, geometric reward | Chain-of-thought + geometric reward signal |
| CReFT-CAD | Image (orthographic projections) | RL fine-tuning | Boosts orthographic-projection reasoning — relevant to drawing-generation stretch goal |
| ProCAD-coder | Text | Only 1.6K examples | "Clarify before you draw" — proactively asks clarifying questions before generating |
| NURBGen | Text | LLM-driven | High-fidelity text-to-CAD via NURBS modeling |
| TOOLCAD | Text | RL | Tool-using LLM approach to text-to-CAD |

**Pattern across this family:** heavy training investment buys geometric fidelity on
expert-style prompts, at the cost of brittleness on the vague, everyday phrasing real
users actually type.

### Family 4 — Code-generation, agentic / training-free
### *This project's category*

No fine-tuning. Uses a general-purpose LLM's existing code ability inside a
generate→verify→retry loop.

**Single-part focused:**
| Method | Notes |
|---|---|
| CADCodeVerify | Agent using validation questions + visual feedback for verification |
| CADDesigner | General-purpose agent; **beat fine-tuned cadrille and CADCodeVerify** on abstract text input (IoU 0.277 vs 0.027 / 0.235; 100% success rate) — key evidence that training-free agentic approaches generalize better than heavy fine-tuning on plain-English input |
| CAD-Assistant | Tool-augmented VLLM treating CAD software itself as a callable tool |
| EvoCAD | Evolutionary CAD code generation with vision-language models |

**Assembly/multi-part focused — published, and the most directly comparable prior work:**
| Method | Notes |
|---|---|
| **ArtiCAD** (April 2026) | Multi-agent: Design Agent decomposes input into components + explicit connectors defined *before* geometry generation; Generation Agents produce FreeCAD scripts; Assembly Agent aligns parts via joint solver; Review Agent scores output. |
| **CADSmith** (2026) | Multi-agent, nested correction loops: inner loop resolves execution errors, outer loop grounded in programmatic OpenCascade geometry validation + VLM visual judgment. Single-part currently. |
| **Physics-in-the-Loop** (May 2026) | Embeds validated knowledge-based engineering tools directly into agent decision loop; closed-loop physical verification. |
| **AgentsCAD** (July 2026) | Multi-agent LLM reasoning + geometric feature recognition specifically for DFM of FDM 3D-printed parts. |
| **Embodied CAD** (2026) | Solver-grounded LLM agents for parametric B-Rep assembly modeling |

**Why this family matters most for this project:** it demonstrably outperforms
heavily fine-tuned Family 3 methods specifically on abstract, non-expert text input —
literature-backed justification for the training-free architectural choice.

### Family 5 — Part-token composition (retrieval/reuse, not generation)
A separate class of system treats existing validated *parts* as tokens and composes them into assemblies via embedding-based retrieval over a parts/PLM database — rather than generating new geometry.

### Family 6 — Direct 3D / mesh generation
Not used in engineering CAD. Direct 3D meshes lack B-rep topology and exact analytic dimensions.

---

## 4. Benchmarks

### Text2CAD-Bench (May 2026) — single-part geometric accuracy
600 human-curated examples across four complexity tiers (L1–L4). Performance drops significantly on complex topology (L3-L4).

### BenchCAD (May 2026) — programmatic CAD as generation target
Traces the field's evolution from command sequence generation toward code (CadQuery) as the standard target.

### MUSE (May 2026) — manufacturable, functional, assemblable text-to-CAD
**The primary benchmark for ForgeAgent evaluation.** 106 hand-curated design instances with formal design specifications. Evaluation uses 3 funnel stages: Code check $\rightarrow$ Geometry check $\rightarrow$ Design-intent alignment.

---

## 5. Corrected Competitive Landscape

ArtiCAD and CADSmith demonstrate multi-agent assembly and programmatic CAD verification. 

**ForgeAgent's Key Contributions:**
1. **Live Graph Emission Engine:** Dynamic DAG nodes emitted based on OpenCascade ground-truth verdicts.
2. **Custom Ground-Up Harness:** Built without third-party frameworks, using MCP tools, A2A messaging, and A2UI streaming.
3. **Headless CadQuery + OpenCascade Stack:** Containerized cloud deployment (AWS ECS Fargate) rather than desktop GUI agents.
