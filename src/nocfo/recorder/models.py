"""Pydantic models for workflow recording."""

import re
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# IDs that look auto-generated: contain UUIDs, hex hashes, React-style _r_XX_
_UNSTABLE_ID_RE = re.compile(
    r"^_r_|[0-9a-f]{8}-[0-9a-f]{4}-|^[0-9a-f]{12,}$|^:r",
    re.IGNORECASE,
)


class SelectorSet(BaseModel):
    """Multiple selector strategies for a single element."""

    css_path: str | None = None
    id: str | None = None
    data_testid: str | None = None
    aria: str | None = None
    text: str | None = None
    nth_child: str | None = None
    name: str | None = None
    placeholder: str | None = None
    semantic: str | None = None
    container_selector: str | None = None
    container_role: str | None = None
    scoped_css_path: str | None = None

    @property
    def _stable_id(self) -> str | None:
        """Return id only if it looks human-authored, not auto-generated."""
        if self.id and not _UNSTABLE_ID_RE.search(self.id):
            return self.id
        return None

    def _priority(self) -> list[tuple[str | None, object]]:
        return [
            (self.data_testid, lambda v: f'[data-testid="{v}"]'),
            (self._stable_id, lambda v: f"#{v}"),
            (self.aria, lambda v: v),
            (self.name, lambda v: f'[name="{v}"]'),
            (self.scoped_css_path, lambda v: v),
            (self.placeholder, lambda v: f'[placeholder="{v}"]'),
            (self.text, lambda v: f'text="{v}"'),
            (self.css_path, lambda v: v),
            (self.nth_child, lambda v: v),
        ]

    def best(self) -> str | None:
        """Return the most robust selector in priority order."""
        for value, transform in self._priority():
            if value:
                return transform(value)
        return None

    def all_selectors(self) -> list[str]:
        """Return all non-null selectors in priority order."""
        result = []
        for value, transform in self._priority():
            if value:
                result.append(transform(value))
        return result


class WorkflowStep(BaseModel):
    """Single interaction in a recorded workflow."""

    step: int
    action: str
    selectors: SelectorSet = Field(default_factory=SelectorSet)
    value: str | None = None
    url: str | None = None
    tag: str | None = None
    inner_text: str | None = None
    screenshot: str | None = None
    timestamp: datetime | None = None
    wait_before_ms: int = 0


class Workflow(BaseModel):
    """Complete recorded workflow."""

    name: str
    recorded_at: datetime = Field(default_factory=datetime.now)
    start_url: str = ""
    description: str | None = None
    total_steps: int = 0
    steps: list[WorkflowStep] = Field(default_factory=list)

    def to_yaml(self, path: Path) -> None:
        """Serialize workflow to YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json", exclude_none=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, path: Path) -> "Workflow":
        """Load workflow from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
