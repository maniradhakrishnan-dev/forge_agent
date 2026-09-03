"""
Reporter Agent.
Exports STEP/STL CAD artifacts and logs final run summaries.
"""

from typing import Dict, Any, Optional
from tools.cad_kernel import export_cad_artifacts
from orchestrator.run_logger import RunLogger
from orchestrator.toolbox import AgentToolbox


class ReporterAgent:
    """Exports CAD STEP/STL artifacts and logs structured run summaries."""

    async def report_and_export(
        self,
        cad_object: Any,
        output_dir: str,
        file_name: str,
        logger: Optional[RunLogger] = None
    ) -> Dict[str, str]:
        """
        Exports STEP/STL artifacts and records reporter step in run log.
        """
        AgentToolbox.enforce("reporter_agent", "cad_kernel_export")
        
        artifact_paths = await export_cad_artifacts(cad_object, output_dir, file_name)
        
        if logger:
            logger.log_step(agent="reporter_agent", status="PASS", diagnostics=[f"Exported artifacts: {list(artifact_paths.keys())}"])
            
        return artifact_paths
