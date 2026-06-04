"""Prompt registry: load, version, and render prompts from markdown + Jinja2."""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from jinja2 import BaseLoader, Environment, TemplateNotFound

logger = logging.getLogger("llm_eval")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_MANIFEST_PATH = _PROMPTS_DIR / "manifest.yaml"


@dataclasses.dataclass(frozen=True)
class PromptMeta:
    """Metadata for a single prompt version."""

    name: str
    version: str
    file: str
    source_of_truth: str
    tags: list[str]
    schema: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class RenderedPrompt:
    """A fully rendered prompt ready to send to an LLM."""

    name: str
    version: str
    system: str | None
    user: str
    schema: dict[str, Any]
    response_format: dict[str, str] | None = None


class _PromptLoader(BaseLoader):
    """Jinja2 loader that reads from the prompts/ directory."""

    def __init__(self, base: Path) -> None:
        self.base = base

    def get_source(self, environment: Environment, template: str) -> tuple[str, str, None]:  # type: ignore[override]
        path = self.base / template
        if not path.exists():
            raise TemplateNotFound(template)
        source = path.read_text(encoding="utf-8")
        return source, str(path), None


class PromptRegistry:
    """Registry of eval prompts loaded from prompts/manifest.yaml + .md files."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self._dir = prompts_dir or _PROMPTS_DIR
        self._manifest_path = self._dir / "manifest.yaml"
        self._jinja = Environment(loader=_PromptLoader(self._dir))
        self._prompts: dict[str, dict[str, PromptMeta]] = {}
        self._load_manifest()

    def _load_manifest(self) -> None:
        if not self._manifest_path.exists():
            logger.warning("Prompt manifest not found: %s", self._manifest_path)
            return
        if yaml is None:
            raise RuntimeError("PyYAML is required for prompt manifest loading")
        raw = yaml.safe_load(self._manifest_path.read_text(encoding="utf-8"))
        for entry in raw.get("prompts", []):
            name = entry["name"]
            self._prompts[name] = {}
            for v in entry.get("versions", []):
                meta = PromptMeta(
                    name=name,
                    version=v["id"],
                    file=v["file"],
                    source_of_truth=v.get("source_of_truth", ""),
                    tags=v.get("tags", []),
                    schema=v.get("schema", {}),
                )
                self._prompts[name][v["id"]] = meta

    def list_prompts(self) -> list[str]:
        return sorted(self._prompts)

    def list_versions(self, name: str) -> list[str]:
        return sorted(self._prompts.get(name, {}))

    def get_meta(self, name: str, version: str | None = None) -> PromptMeta:
        """Get metadata for a prompt. If version is None, uses latest."""
        versions = self._prompts.get(name)
        if not versions:
            raise KeyError(f"Prompt {name!r} not found")
        if version is None:
            version = max(versions)
        meta = versions.get(version)
        if meta is None:
            raise KeyError(f"Version {version!r} not found for prompt {name!r}")
        return meta

    def render(self, name: str, version: str | None = None, **kwargs: Any) -> RenderedPrompt:
        """Render a prompt template with given variables."""
        meta = self.get_meta(name, version)
        tpl = self._jinja.get_template(meta.file)
        raw = tpl.render(**kwargs)

        system, user, response_format = _parse_prompt_md(raw, meta.schema)
        return RenderedPrompt(
            name=name,
            version=meta.version,
            system=system,
            user=user,
            schema=meta.schema,
            response_format=response_format,
        )


def _parse_prompt_md(raw: str, schema: dict[str, Any]) -> tuple[str | None, str, dict[str, str] | None]:
    """Parse a rendered prompt markdown into system/user/response_format.

    Convention:
    - If the markdown contains a `## System` section, its content is the system prompt.
    - The `## User` section (or everything if no sections) is the user prompt.
    - If schema contains `response_format: json_object`, set response_format accordingly.
    """
    system_match = re.search(r"^##\s*System\s*\n(.*?)(?=\n##\s|$)", raw, re.DOTALL | re.IGNORECASE)
    user_match = re.search(r"^##\s*User\s*\n(.*?)(?=\n##\s|$)", raw, re.DOTALL | re.IGNORECASE)

    system = system_match.group(1).strip() if system_match else None
    if user_match:
        user = user_match.group(1).strip()
    else:
        # No sections — the whole thing is the user prompt
        user = raw.strip()

    response_format: dict[str, str] | None = None
    if schema.get("response_format") == "json_object":
        response_format = {"type": "json_object"}

    return system, user, response_format
