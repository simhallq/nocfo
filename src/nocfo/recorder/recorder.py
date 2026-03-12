"""WorkflowRecorder — captures browser interactions into a replayable workflow."""

import json
import time
from datetime import datetime
from pathlib import Path

import structlog
from playwright.sync_api import Page

from .injector import inject_recorder, reinject_js
from .models import SelectorSet, Workflow, WorkflowStep

logger = structlog.get_logger()


class WorkflowRecorder:
    """Records user interactions in a browser page to a replayable workflow."""

    def __init__(
        self,
        name: str,
        page: Page,
        workflows_dir: Path = Path("data/workflows"),
        screenshots_dir: Path = Path("data/screenshots"),
        enhance_with_vision: bool = False,
    ) -> None:
        self._name = name
        self._page = page
        self._workflows_dir = workflows_dir
        self._screenshots_dir = screenshots_dir / f"record_{name}"
        self._enhance = enhance_with_vision
        self._steps: list[WorkflowStep] = []
        self._start_url = ""
        self._last_event_time: float | None = None
        self._recording = False

    @property
    def steps(self) -> list[WorkflowStep]:
        return list(self._steps)

    def start(self) -> None:
        """Begin recording interactions."""
        self._start_url = self._page.url
        self._recording = True
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)

        inject_recorder(self._page, self._on_event)
        self._page.on("load", lambda: reinject_js(self._page))

        logger.info("recording_started", name=self._name, url=self._start_url)

    def stop(self) -> Workflow:
        """Stop recording and save the workflow."""
        self._recording = False

        workflow = Workflow(
            name=self._name,
            recorded_at=datetime.now(),
            start_url=self._start_url,
            total_steps=len(self._steps),
            steps=self._steps,
        )

        yaml_path = self._workflows_dir / f"{self._name}.yaml"
        workflow.to_yaml(yaml_path)

        logger.info(
            "recording_saved",
            name=self._name,
            steps=len(self._steps),
            path=str(yaml_path),
        )

        if self._enhance:
            try:
                from .enhancer import enhance_workflow

                workflow = enhance_workflow(workflow)
                workflow.to_yaml(yaml_path)
                logger.info("workflow_enhanced", name=self._name)
            except Exception as e:
                logger.warning("enhancement_failed", error=str(e))

        return workflow

    def _on_event(self, event_json: str) -> None:
        """Handle an interaction event from the injected JS."""
        if not self._recording:
            return

        try:
            data = json.loads(event_json)
        except json.JSONDecodeError:
            logger.warning("invalid_event_json", raw=event_json[:200])
            return

        now = time.monotonic()
        wait_ms = 0
        if self._last_event_time is not None:
            wait_ms = int((now - self._last_event_time) * 1000)
        self._last_event_time = now

        step_num = len(self._steps) + 1

        # Take screenshot
        screenshot_path = None
        try:
            screenshot_file = self._screenshots_dir / f"step_{step_num:03d}.png"
            self._page.screenshot(path=str(screenshot_file))
            screenshot_path = str(screenshot_file)
        except Exception as e:
            logger.warning("screenshot_failed", step=step_num, error=str(e))

        selectors = SelectorSet.model_validate(data.get("selectors", {}))

        step = WorkflowStep(
            step=step_num,
            action=data.get("action", "click"),
            selectors=selectors,
            value=data.get("value"),
            url=data.get("url"),
            tag=data.get("tag"),
            inner_text=data.get("inner_text"),
            screenshot=screenshot_path,
            timestamp=(
                datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else None
            ),
            wait_before_ms=wait_ms,
        )

        self._steps.append(step)
        logger.info(
            "step_recorded",
            step=step_num,
            action=step.action,
            tag=step.tag,
            selector=selectors.best(),
        )
