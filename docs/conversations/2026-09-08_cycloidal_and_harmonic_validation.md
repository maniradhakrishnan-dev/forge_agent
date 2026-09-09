# Multi-Mechanism Ground Truth Validation: Harmonic Drive & Cycloidal Drive

- **Date:** September 8, 2026
- **Workspace:** `/home/mani_radhakrishnan/capv1_mech_design`
- **Objective:** Verify ForgeAgent multi-agent CAD generation & verification pipeline by building two advanced transmission mechanisms from scratch:
  1. **Harmonic (Strain Wave) Drive**
  2. **Cycloidal Gear Drive**

---

## 1. Mechanism 1: Harmonic Gear Drive

- **Run ID:** [`8a489776`](file:///home/mani_radhakrishnan/capv1_mech_design/artifacts/runs/8a489776/run_summary.md)
- **Prompt:** `"Build a harmonicgear drive for metal manufacturing or machining ,the gear ratio is 2000 rpm to 200 rpm ,the gear box will be attached to bldc motor"`
- **Manufacturing Process:** `cnc_machining`
- **Verification Depth:** `assembly_ready`

### Results:
- **Planner Decomposition:** 3 parts: `circular_spline_housing`, `flexspline_cup`, `wave_generator_cam`
- **Single-Part DFM:** All 3 parts passed 6-pillar OpenCascade geometric checks on **Attempt 1**.
- **Assembly Verification:** Passed on **Assembly Iteration 1**.
- **Interference Volume:** `0.0 mm³` overlap.
- **Generated CAD Artifacts:**
  - Composite STEP: [harmonic_gear_drive_2000_200.step](file:///home/mani_radhakrishnan/capv1_mech_design/artifacts/runs/8a489776/harmonic_gear_drive_2000_200.step)
  - Composite STL: [harmonic_gear_drive_2000_200.stl](file:///home/mani_radhakrishnan/capv1_mech_design/artifacts/runs/8a489776/harmonic_gear_drive_2000_200.stl)

---

## 2. Mechanism 2: Cycloidal Drive

- **Run ID:** [`0e849f1f`](file:///home/mani_radhakrishnan/capv1_mech_design/artifacts/runs/0e849f1f/run_summary.md)
- **Prompt:** `"Build a cycloidal gear drive for metal manufacturing or machining ,the gear ratio is 3000 rpm to 100 rpm ,the gear box will be attached to bldc motor"`
- **Manufacturing Process:** `cnc_machining`
- **Verification Depth:** `assembly_ready`

### Results:
- **Planner Decomposition:** 4 parts: `eccentric_input_shaft`, `cycloid_disk`, `outer_housing`, `output_carrier_plate`
- **Single-Part DFM:** All 4 parts passed 6-pillar OpenCascade geometric checks on **Attempt 1**.
  - `output_carrier`: Watertight manifold, 203.7ms
  - `housing_casing`: Watertight manifold, 314.0ms
  - `cycloid_disk`: Watertight manifold with smooth multi-lobe profile, 360.5ms
  - `input_eccentric_shaft`: Watertight manifold with offset cam lobe, 15.2ms
- **Assembly Verification:** Passed on **Assembly Iteration 1**.
- **Interference Volume:** `0.0 mm³` overlap.
- **Generated CAD Artifacts:**
  - Composite STEP: [cycloidal_drive_30_to_1.step](file:///home/mani_radhakrishnan/capv1_mech_design/artifacts/runs/0e849f1f/cycloidal_drive_30_to_1.step) (1.88 MB)
  - Composite STL: [cycloidal_drive_30_to_1.stl](file:///home/mani_radhakrishnan/capv1_mech_design/artifacts/runs/0e849f1f/cycloidal_drive_30_to_1.stl) (1.90 MB)

---

## 3. Engineering Fixes Implemented

### A. Pin Ring Housing Cavity Geometry (`skills/cadquery_modeling/SKILL.md`)
- **Problem:** When cutting the internal cavity for the ring housing, cutting at `(pin_ring_dia / 2) + (pin_dia / 2)` removed the solid material needed for the stationary pin rollers to attach. When unioned, the pins floated disconnected, causing `Part consists of 32 disconnected solid bodies!`
- **Fix:** In [skills/cadquery_modeling/SKILL.md](file:///home/mani_radhakrishnan/capv1_mech_design/skills/cadquery_modeling/SKILL.md), documented that the cavity bore radius must be cut at `pin_ring_dia / 2.0` (center circle of pins). The outer half of each pin roller embeds solidly into the casing wall, creating a watertight single manifold.

### B. Dynamic Variable Context for InterfacePort Extraction (`orchestrator/agents/code_generator_agent.py`)
- **Problem:** Interface comments containing script variables (e.g. `# INTERFACE: lobe_profile=(0,0,disk_thickness/2)...`) failed during `eval()` because `disk_thickness` was not in the hardcoded context dictionary. The exception handler silently dropped the port, falling back to dummy ports without `gear_mesh` annotations.
- **Fix:** Added regex parsing in [orchestrator/agents/code_generator_agent.py](file:///home/mani_radhakrishnan/capv1_mech_design/orchestrator/agents/code_generator_agent.py) to extract all top-level numerical variables defined in the CadQuery script and inject them into `context`. All ports with expressions like `disk_thickness/2` or `pin_circle_dia/2` now evaluate cleanly.

### C. Concentric Internal Mechanism Handling (`tools/verify_assembly.py`)
- **Problem:** When rotating components (cycloid disk, planet gears, flexsplines) sit inside a housing cavity on the same axial span, `tools/verify_assembly.py` previously mistook their coaxial placement for an "axial stacking collision" (thinking they were links or brackets that should be stacked end-to-end).
- **Fix:** Added `is_concentric_mechanism` check in [tools/verify_assembly.py](file:///home/mani_radhakrishnan/capv1_mech_design/tools/verify_assembly.py) covering gears, cycloids, splines, cams, and rotors. Coaxial placement inside a pocket is recognized as intentional internal gearing.
