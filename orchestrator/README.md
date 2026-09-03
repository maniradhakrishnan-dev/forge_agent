# /orchestrator — Custom Live Graph Engine & A2A Dispatcher

This directory contains the custom, ground-up multi-agent orchestration engine for **ForgeAgent**.

## Key Components

- `graph_engine.py`: Custom event-driven Live Graph engine that dynamically emits DAG nodes and edges based on OpenCascade ground-truth verdicts.
- `a2a_dispatcher.py`: Agent-to-Agent (A2A) protocol implementation for structured task delegation and diagnostic payload passing between agents.
- `agents/`: Individual agent handlers:
  - `architect_agent.py`: Parses spec into assembly graphs.
  - `part_designer_agent.py`: Generates CadQuery scripts.
  - `part_critic_agent.py`: Executes single-part DFM & topology verifiers.
  - `assembly_agent.py`: Assembles parts with kinematic mates.
  - `assembly_critic_agent.py`: Executes interference, fit, and motion sweep verifiers.
- `circuit_breaker.py`: Retry counter manager and infinite loop prevention.
