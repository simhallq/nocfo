"""ReplayEngine — executes recorded workflows."""

from dataclasses import dataclass, field

import structlog
from playwright.sync_api import Page

from .models import Workflow, WorkflowStep

logger = structlog.get_logger()


@dataclass
class StepResult:
    """Result of replaying a single step."""

    step: int
    action: str
    success: bool
    selector_used: str = ""
    error: str = ""


@dataclass
class ReplayResult:
    """Result of replaying an entire workflow."""

    workflow_name: str
    total_steps: int = 0
    passed: int = 0
    failed: int = 0
    step_results: list[StepResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0


class ReplayEngine:
    """Executes a recorded workflow against a browser page."""

    def __init__(
        self,
        workflow: Workflow,
        page: Page,
        speed: float = 1.0,
        strict: bool = True,
    ) -> None:
        self._workflow = workflow
        self._page = page
        self._speed = speed
        self._strict = strict

    def run(self) -> ReplayResult:
        """Execute all steps in the workflow."""
        result = ReplayResult(
            workflow_name=self._workflow.name,
            total_steps=self._workflow.total_steps,
        )

        # Navigate to start URL
        if self._workflow.start_url:
            logger.info("replay_navigating", url=self._workflow.start_url)
            self._page.goto(
                self._workflow.start_url, wait_until="networkidle", timeout=30000
            )

        for step in self._workflow.steps:
            step_result = self._execute_step(step)
            result.step_results.append(step_result)

            if step_result.success:
                result.passed += 1
            else:
                result.failed += 1
                if self._strict:
                    logger.error(
                        "replay_step_failed_strict",
                        step=step.step,
                        error=step_result.error,
                    )
                    break

        logger.info(
            "replay_complete",
            name=self._workflow.name,
            passed=result.passed,
            failed=result.failed,
        )
        return result

    def _execute_step(self, step: WorkflowStep) -> StepResult:
        """Execute a single workflow step with selector fallback."""
        # Apply wait
        if step.wait_before_ms > 0:
            wait_ms = int(step.wait_before_ms / self._speed)
            self._page.wait_for_timeout(wait_ms)

        # Handle navigation action
        if step.action == "navigate" and step.url:
            try:
                self._page.goto(step.url, wait_until="networkidle", timeout=30000)
                return StepResult(step=step.step, action="navigate", success=True)
            except Exception as e:
                return StepResult(
                    step=step.step, action="navigate", success=False, error=str(e)
                )

        # Try selectors in priority order
        selectors = step.selectors.all_selectors()
        if not selectors:
            return StepResult(
                step=step.step,
                action=step.action,
                success=False,
                error="No selectors available",
            )

        last_error = ""
        for selector in selectors:
            try:
                self._page.wait_for_selector(selector, state="visible", timeout=10000)
                self._run_action(step.action, selector, step.value)
                logger.info(
                    "replay_step_ok",
                    step=step.step,
                    action=step.action,
                    selector=selector,
                )
                return StepResult(
                    step=step.step,
                    action=step.action,
                    success=True,
                    selector_used=selector,
                )
            except Exception as e:
                last_error = str(e)
                continue

        return StepResult(
            step=step.step,
            action=step.action,
            success=False,
            error=f"All {len(selectors)} selectors failed. Last: {last_error}",
        )

    def _run_action(self, action: str, selector: str, value: str | None) -> None:
        """Execute a Playwright action."""
        if action == "click":
            self._page.click(selector, timeout=10000)
        elif action == "fill":
            self._page.fill(selector, value or "", timeout=10000)
        elif action == "select":
            self._page.select_option(selector, value or "", timeout=10000)
        elif action == "check":
            self._page.check(selector, timeout=10000)
        else:
            raise ValueError(f"Unknown action: {action}")

        # Wait for potential navigation/network activity
        try:
            self._page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass  # Timeout on networkidle is non-fatal
