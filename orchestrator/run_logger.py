"""
Structured Observability Run Logger for ForgeAgent.
Appends typed RunEntry records to a JSONL log file per execution run,
prints real-time transparent progress to the terminal, and generates run_summary.md.
"""

import asyncio
from pathlib import Path
from typing import List, Any, Optional
from orchestrator.models import RunEntry


class RunLogger:
    def __init__(
        self,
        run_id: str,
        output_dir: str = "artifacts/run_logs",
        verbose: bool = True,
        on_step_callback: Optional[Any] = None
    ):
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.output_dir / "run_log.jsonl"
        self.summary_file = self.output_dir / "run_summary.md"
        self.verbose = verbose
        self.on_step_callback = on_step_callback
        self.entries: List[RunEntry] = []

    def log_step(
        self,
        agent: str,
        status: str,  # "PASS", "FAIL", "ERROR", "ESCALATE"
        part_id: Optional[str] = None,
        iteration: int = 1,
        diagnostics: Optional[List[Any]] = None,
        latency_ms: float = 0.0,
        llm_tokens_used: Optional[int] = None
    ) -> RunEntry:
        """
        Logs a single agent execution step to the JSONL log file,
        prints real-time terminal output, and appends to run summary.
        """
        entry = RunEntry(
            run_id=self.run_id,
            agent=agent,
            part_id=part_id,
            iteration=iteration,
            status=status,
            diagnostics=diagnostics or [],
            latency_ms=round(latency_ms, 2),
            llm_tokens_used=llm_tokens_used
        )
        self.entries.append(entry)

        # 1. Append to JSONL log
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(entry.model_dump_json() + "\n")
        except Exception:
            pass

        # 2. Real-time Terminal Logging
        if self.verbose:
            self._print_terminal_step(entry)

        # 3. Live Graph Hook Callback
        if self.on_step_callback:
            try:
                res = self.on_step_callback(entry)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        asyncio.run(res)
            except Exception:
                pass

        return entry

    def _print_terminal_step(self, entry: RunEntry):
        """Prints a clean, informative human-readable terminal log line."""
        icon = "✅" if entry.status == "PASS" else ("❌" if entry.status in ("FAIL", "ERROR") else "⚠️")
        part_tag = f"[{entry.part_id}]" if entry.part_id else ""
        lat_tag = f"({entry.latency_ms:.0f}ms)" if entry.latency_ms > 0 else ""

        if entry.agent == "planner_agent":
            print(f"  {icon} [PlannerAgent] Decomposed prompt into AssemblyGraph {lat_tag}")
        elif entry.agent == "constraint_validator":
            print(f"  {icon} [ConstraintValidator] Pre-design consistency rules {lat_tag}")
        elif entry.agent == "code_generator_agent":
            print(f"  {icon} [Designer] {part_tag} CadQuery code generated (Attempt {entry.iteration}) {lat_tag}")
        elif entry.agent == "cad_kernel_sandbox":
            if entry.status == "ERROR":
                print(f"  ❌ [Sandbox] {part_tag} CadQuery execution failed (Attempt {entry.iteration})")
            else:
                print(f"  ✅ [Sandbox] {part_tag} OpenCascade solid built successfully")
        elif entry.agent == "part_verifier_agent":
            if entry.status == "PASS":
                print(f"  {icon} [PartVerifier] {part_tag} 6-Pillar DFM checks passed {lat_tag}")
            else:
                fails = [d.get("message", "") for d in entry.diagnostics if isinstance(d, dict) and d.get("status") == "FAIL"]
                err_summary = fails[0] if fails else "DFM rule violation"
                print(f"  {icon} [PartVerifier] {part_tag} Verification check failed: {err_summary} {lat_tag}")
        elif entry.agent == "part_repair_agent":
            print(f"  🔧 [PartRepair] {part_tag} Formulated repair feedback for Designer (Attempt {entry.iteration})")
        elif entry.agent == "assembly_agent":
            print(f"  {icon} [AssemblyAgent] Mated parts via InterfacePorts (Assembly Iteration {entry.iteration}) {lat_tag}")
        elif entry.agent == "assembly_verifier_agent":
            if entry.status == "PASS":
                print(f"  {icon} [AssemblyVerifier] Interference=0.0mm³, Fit Clearance & Kinematics PASSED {lat_tag}")
            else:
                fails = [d.get("message", "") for d in entry.diagnostics if isinstance(d, dict) and d.get("status") == "FAIL"]
                err_summary = fails[0] if fails else "Assembly check violation"
                print(f"  {icon} [AssemblyVerifier] Assembly check failed: {err_summary} {lat_tag}")
        elif entry.agent == "assembly_repair_agent":
            diag = entry.diagnostics[0] if entry.diagnostics and isinstance(entry.diagnostics[0], dict) else {}
            fault = diag.get("fault_type", "diagnostic")
            target = diag.get("target_agent", "pipeline")
            print(f"  🔧 [AssemblyRepair] Diagnosed {fault} fault -> Routing corrective payload to '{target}'")
        elif entry.agent == "reporter_agent":
            print(f"  💾 [Reporter] {part_tag} CAD artifacts exported (.py, .step, .stl)")

    def generate_summary_markdown(self, prompt: str, passed: bool) -> str:
        """Writes a clean Markdown summary table of all agent steps to run_summary.md."""
        verdict_icon = "✅ PASSED" if passed else "❌ FAILED"
        lines = [
            f"# ForgeAgent Run Summary: `{self.run_id}`",
            f"**Prompt:** {prompt}  ",
            f"**Overall Verdict:** {verdict_icon}  ",
            f"**Total Steps Logged:** {len(self.entries)}  \n",
            "| # | Agent | Part ID | Iteration | Status | Latency | Diagnostics |",
            "|---|---|---|---|---|---|---|"
        ]

        for idx, e in enumerate(self.entries, 1):
            p_id = e.part_id or "-"
            lat = f"{e.latency_ms:.1f}ms" if e.latency_ms > 0 else "-"
            diag_snippet = ""
            if e.diagnostics:
                first = e.diagnostics[0]
                if isinstance(first, dict):
                    diag_snippet = first.get("message") or first.get("prompt") or str(first)[:60]
                else:
                    diag_snippet = str(first)[:60]
            diag_snippet = diag_snippet.replace("|", "/")
            lines.append(f"| {idx} | `{e.agent}` | `{p_id}` | {e.iteration} | **{e.status}** | {lat} | {diag_snippet} |")

        md_content = "\n".join(lines) + "\n"
        try:
            with open(self.summary_file, "w", encoding="utf-8") as f:
                f.write(md_content)
        except Exception:
            pass

        return md_content
