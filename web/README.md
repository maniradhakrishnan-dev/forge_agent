# /web — A2UI Dynamic Web Visualizer

This directory contains the dynamic web dashboard built with Vite/React, rendering real-time Live Graph state and Three.js 3D assembly models via the Agent-to-User Interface (A2UI) protocol.

## Features

- **Live Graph View:** Dynamic DAG visualizer (React Flow / D3) showing nodes and edges emitted live as OpenCascade ground-truth checks pass/fail.
- **Interactive 3D Viewer:** Three.js / `@react-three/fiber` canvas rendering glTF/STEP assembly exports in real time.
- **Diagnostic Panel:** Displays structured error payloads and DFM check measurements.
