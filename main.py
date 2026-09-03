# Load .env BEFORE any module imports that read os.getenv()
from dotenv import load_dotenv
load_dotenv()

"""
ForgeAgent Main CLI Entry Point.
Executes the Multi-Agent CAD Generation & Verification Pipeline via the Live Graph Engine.

Usage:
    uv run python main.py --prompt "Mounting bracket 40x30x10mm with M4 clearance hole" --process 3d_printing --depth functional
    uv run python main.py --prompt "Bracket with M4 bolt assembly" --process 3d_printing --depth assembly_ready
    uv run python main.py --prompt "CNC machined aluminum plate 60x40x15mm" --process cnc_machining
    uv run python main.py --prompt "Sheet metal enclosure bracket 2mm gauge" --process sheet_metal
"""

import sys
import uuid
import argparse
import asyncio
from pathlib import Path
from orchestrator.gateway_client import GatewayClient, LLMAPIError
from orchestrator.agents.planner_agent import PlannerParseError
from orchestrator.live_graph.store import GraphStore
from orchestrator.live_graph.executor import LiveGraphExecutor


async def main():
    parser = argparse.ArgumentParser(description="ForgeAgent: Multi-Agent Mechanical CAD Generation & Verification")
    parser.add_argument(
        "--prompt",
        type=str,
        default="Single mounting bracket 40x30x10mm with a central 4.3mm M4 clearance hole",
        help="Plain English mechanism or assembly description"
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Directory to save STEP, STL, and run_log.jsonl artifacts (default: artifacts/runs/<run_id>/)"
    )
    parser.add_argument(
        "--process",
        type=str,
        choices=["3d_printing", "cnc_machining", "sheet_metal"],
        default=None,
        help="Primary manufacturing process DFM suite (3d_printing, cnc_machining, sheet_metal). Auto-detected from prompt if omitted."
    )
    parser.add_argument(
        "--depth",
        type=str,
        choices=["concept", "functional", "manufacturing", "assembly_ready"],
        default="functional",
        help="Verification depth (concept, functional, manufacturing, assembly_ready)"
    )

    args = parser.parse_args()

    # Generate unique run ID
    run_id = str(uuid.uuid4())[:8]

    # Auto-detect manufacturing process from prompt if not explicitly passed
    process = args.process
    if not process:
        p_lower = args.prompt.lower()
        if any(w in p_lower for w in ["machin", "cnc", "milled", "lathe"]):
            process = "cnc_machining"
        elif any(w in p_lower for w in ["sheet metal", "laser", "bend", "gauge"]):
            process = "sheet_metal"
        else:
            process = "3d_printing"

    # Default output directory includes run_id for traceability
    output_dir = args.out_dir or f"artifacts/runs/{run_id}"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(" 🛠️  ForgeAgent: Multi-Agent Mechanical CAD Generation & Verification")
    print("=" * 70)
    print(f"Run ID:               {run_id}")
    print(f"Prompt:               {args.prompt}")
    print(f"Manufacturing Process: {process}")
    print(f"Verification Depth:   {args.depth}")
    print(f"Output Directory:     {output_dir}")
    print("-" * 70)

    gw = GatewayClient()
    store = GraphStore()
    executor = LiveGraphExecutor(store)

    try:
        success, graph_state_file = await executor.execute_prompt(
            prompt=args.prompt,
            output_dir=output_dir,
            process=process,
            depth=args.depth,
            gateway_client=gw,
            run_id=run_id
        )
    except LLMAPIError as e:
        print(f"\n❌ [LLM API FAILURE] {e}")
        print(f"  • Check your API keys in .env")
        print(f"  • Check your model names (GEMINI_MODEL, GROQ_MODEL)")
        print(f"  • Run ID: {run_id}")
        sys.exit(2)
    except PlannerParseError as e:
        print(f"\n❌ [PLANNER PARSE FAILURE] {e}")
        print(f"  • The LLM returned a response that could not be parsed as AssemblyGraph JSON")
        print(f"  • Run ID: {run_id}")
        sys.exit(3)
    except Exception as e:
        print(f"\n❌ [UNEXPECTED ERROR] {type(e).__name__}: {e}")
        print(f"  • Run ID: {run_id}")
        sys.exit(1)

    if success:
        print(f"\n✅ [GROUND TRUTH PASS] Design & Verification Succeeded!")
        print(f"  • Run ID:               {run_id}")
        print(f"  • Graph State Snapshot: {graph_state_file}")
        print(f"  • Human Run Summary:    {output_dir}/run_summary.md")
        print(f"  • Structured Run Log:   {output_dir}/run_log.jsonl")
        print(f"  • CAD Artifacts Saved:  {output_dir}/")
        print("=" * 70)
    else:
        print(f"\n❌ [VERIFICATION FAILED] Iteration limit reached without ground-truth pass.")
        print(f"  • Run ID:          {run_id}")
        print(f"  • Human Run Summary: {output_dir}/run_summary.md")
        print(f"  • Diagnostic Log:    {output_dir}/run_log.jsonl")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
