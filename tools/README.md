# /tools — Model Context Protocol (MCP) Tool Servers

This directory contains the MCP-compliant tool servers exposing CadQuery execution and OpenCascade geometry verification to ForgeAgent LLM agents.

## MCP Tool Servers

1. `cad_kernel_server.py`: Safely executes agent-authored CadQuery Python code in a sandboxed environment, outputting STEP, STL, and glTF artifacts.
2. `verify_single_part_server.py`: Runs single-part ground-truth checks (`check_solid_manifold`, `check_dfm_wall_thickness`, `check_dfm_hole_diameter`, `check_dfm_overhang_angle`).
3. `verify_assembly_server.py`: Runs multi-part ground-truth checks (`check_interference_intersection`, `check_fit_clearance`, `check_kinematic_motion_sweep`).
4. `render_hlr_server.py`: Generates 2D Hidden-Line Removal (HLR) orthographic vector projections (SVG/PDF).
