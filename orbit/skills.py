"""SkillLoader: load specialized knowledge from SKILL.md files.

Skills are markdown files with YAML frontmatter stored under a skills/
directory. Each skill has a name, description (from frontmatter), and
body (the markdown content after the frontmatter).

The skill descriptions are injected into the system prompt so the
model knows which skills are available.
"""

from __future__ import annotations

import re
from pathlib import Path


class SkillLoader:
    """Load and serve SKILL.md files from a skills directory.

    Skills are discovered recursively. Each SKILL.md file can have
    optional YAML frontmatter with `name` and `description` fields.

        skills/
        +------------------------+
        | my-skill/              |
        |   SKILL.md             |
        | another-skill/         |
        |   SKILL.md             |
        +------------------------+
    """

    def __init__(self, skills_dir: Path) -> None:
        """Initialize the skill loader and discover all skills.

        Args:
            skills_dir: Path to the skills/ directory.
        """
        self.skills: dict[str, dict] = {}
        self.dir = Path(skills_dir)

        if self.dir.exists():
            for f in sorted(self.dir.rglob("SKILL.md")):
                text = f.read_text(encoding="utf-8")
                match = re.match(
                    r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL
                )
                meta: dict[str, str] = {}
                body = text
                if match:
                    for line in match.group(1).strip().splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip()] = v.strip()
                    body = match.group(2).strip()

                name = meta.get("name", f.parent.name)
                self.skills[name] = {"meta": meta, "body": body}

    def descriptions(self) -> str:
        """Get a summary of all available skills for the system prompt.

        Returns:
            Bullet list of skill names and descriptions, or '(no skills)'.
        """
        if not self.skills:
            return "(no skills)"

        lines: list[str] = []
        for name, s in self.skills.items():
            desc = s["meta"].get("description", "-")
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    def load(self, name: str) -> str:
        """Load a skill's full body by name.

        Args:
            name: The skill name (from frontmatter or directory name).

        Returns:
            The skill body wrapped in a <skill> tag, or an error message
            listing available skills if the name is unknown.
        """
        s = self.skills.get(name)
        if not s:
            available = ", ".join(sorted(self.skills.keys()))
            return f"Error: Unknown skill '{name}'. Available: {available}"
        return f"<skill name=\"{name}\">\n{s['body']}\n</skill>"

    @property
    def names(self) -> list[str]:
        """List of all available skill names."""
        return sorted(self.skills.keys())
