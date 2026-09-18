"""
Dynamic Mechanical Engineering Skill Registry.
Discovers, indexes, and loads modular skill packs from the skills/ directory.
Prevents bloating agent system prompts and harnesses with hardcoded mechanism rules.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any


class SkillDefinition:
    def __init__(self, name: str, description: str, file_path: Path, content: str):
        self.name = name
        self.description = description
        self.file_path = file_path
        self.content = content

    def __repr__(self) -> str:
        return f"<Skill '{self.name}': {self.description[:40]}...>"


class SkillRegistry:
    """Discovers, indexes, and resolves modular skills for agents dynamically."""

    def __init__(self, root_dir: Optional[str] = None):
        if root_dir:
            self.root_dir = Path(root_dir)
        else:
            # Default to repo root / skills
            self.root_dir = Path(__file__).resolve().parent.parent.parent / "skills"
        self._skills: Dict[str, SkillDefinition] = {}
        self._discover_skills()

    def _discover_skills(self):
        """Recursively scans skills/ directory for SKILL.md files and parses YAML frontmatter."""
        if not self.root_dir.exists():
            return

        for path in self.root_dir.glob("**/SKILL.md"):
            try:
                raw_text = path.read_text(encoding="utf-8")
                # Parse frontmatter
                name = path.parent.name
                description = ""
                content = raw_text

                m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw_text, re.DOTALL)
                if m:
                    frontmatter, body = m.group(1), m.group(2)
                    content = body
                    for line in frontmatter.splitlines():
                        if line.startswith("name:"):
                            name = line.split("name:", 1)[1].strip().strip('"\'')
                        elif line.startswith("description:"):
                            description = line.split("description:", 1)[1].strip().strip('"\'')

                self._skills[name] = SkillDefinition(
                    name=name,
                    description=description,
                    file_path=path,
                    content=content.strip()
                )
            except Exception as e:
                print(f"  ⚠️  [SkillRegistry] Failed reading skill at {path}: {e}")

    def list_skills(self) -> List[str]:
        """Returns all discovered skill names."""
        return sorted(list(self._skills.keys()))

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """Gets a SkillDefinition by exact name or sub-name."""
        if name in self._skills:
            return self._skills[name]
        for k, v in self._skills.items():
            if name.lower() in k.lower() or k.lower() in name.lower():
                return v
        return None

    def get_skill_content(self, name: str) -> str:
        """Returns the markdown text of a skill."""
        skill = self.get_skill(name)
        return skill.content if skill else ""

    def format_catalog_for_planner(self) -> str:
        """
        Formats a concise catalog of all available engineering skills for the PlannerAgent prompt.
        Allows the Planner LLM to understand what modular skills exist and select them
        dynamically during requirement decomposition, eliminating hardcoded keyword routing.
        """
        lines = []
        for name in self.list_skills():
            skill = self.get_skill(name)
            desc = skill.description if skill and skill.description else "Domain engineering skill."
            lines.append(f"- `{name}`: {desc}")
        return "\n".join(lines)

    def resolve_skills(
        self,
        prompt: str = "",
        mechanism_type: str = "",
        part_type: str = "",
        process: str = "",
        is_compliant: bool = False,
        explicit_skills: Optional[List[str]] = None,
        part_types: Optional[List[str]] = None
    ) -> List[str]:
        """
        Dynamically identifies the list of skill names that apply to a part or assembly.
        Prefers typed explicit_skills (from PartSpec/AssemblyGraph) planned by the LLM.
        """
        resolved: List[str] = []
        if explicit_skills:
            resolved.extend(explicit_skills)
        else:
            pt_str = " ".join(part_types) if part_types else part_type
            text = f"{prompt} {mechanism_type} {pt_str}".lower()

            # 1. Manufacturing Process Skill
            if process:
                proc_key = f"dfm_{process}"
                if proc_key in self._skills:
                    resolved.append(proc_key)
                else:
                    for k in self._skills:
                        if process in k:
                            resolved.append(k)
                            break

            # 2. Mechanism Skills (fallback when no explicit_skills given)
            if any(kw in text for kw in ["cycloid", "cycloidal", "pin wheel", "lobe"]):
                resolved.append("cycloidal_drive")
            if any(kw in text for kw in ["planet", "planetary", "sun gear", "ring gear", "epicyclic"]):
                resolved.append("planetary_gearbox")
            if any(kw in text for kw in ["harmonic", "strain wave", "flexspline", "flexible", "flexure", "snap fit", "clip"]) or is_compliant:
                resolved.append("compliant_mechanisms")

            # 3. Component Skills (fallback when no explicit_skills given)
            if any(kw in text for kw in ["shaft", "spindle", "axle", "journal"]):
                resolved.append("stepped_shaft")
            if any(kw in text for kw in ["bolt", "screw", "nut", "flange", "pcd", "counterbore", "fastener"]):
                resolved.append("fasteners_and_flanges")
            if any(kw in text for kw in ["fit", "clearance", "tolerance", "running fit"]):
                resolved.append("fits_and_tolerances")

        # Always include base CadQuery modeling skill if available
        if "cadquery_modeling" in self._skills and "cadquery_modeling" not in resolved:
            resolved.append("cadquery_modeling")

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for s in resolved:
            if s in self._skills and s not in seen:
                seen.add(s)
                deduped.append(s)
        return deduped

    def format_skills_for_prompt(self, skill_names: List[str]) -> str:
        """Formats and concatenates the selected skills for LLM system prompt injection."""
        sections = []
        for name in skill_names:
            skill = self.get_skill(name)
            if skill:
                sections.append(f"### SKILL: {skill.name.upper()}\n{skill.content}")
        if not sections:
            return ""
        return "\n\n---\n" + "\n\n---\n".join(sections) + "\n---\n"


# Global singleton registry
default_registry = SkillRegistry()
