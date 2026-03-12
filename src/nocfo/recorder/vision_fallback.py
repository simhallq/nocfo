"""Vision-based fallback for workflow replay — uses Claude to find elements by screenshot."""

import base64
import json
from pathlib import Path

import structlog
from playwright.sync_api import Page

from .models import WorkflowStep
from .replay import StepResult

logger = structlog.get_logger()


def vision_fallback_step(
    page: Page,
    step: WorkflowStep,
    workflow_description: str | None = None,
    anthropic_client: object | None = None,
) -> StepResult:
    """Use Claude vision to locate and interact with an element when selectors fail.

    Takes a fresh screenshot of the current page and compares it with the
    reference screenshot from recording to find the target element coordinates.
    """
    from anthropic import Anthropic

    if anthropic_client is None:
        from nocfo.config import get_settings

        settings = get_settings()
        anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

    # Take fresh screenshot of current page
    current_png = page.screenshot(type="png")
    current_b64 = base64.b64encode(current_png).decode()

    # Load reference screenshot if available
    ref_b64 = None
    if step.screenshot and Path(step.screenshot).exists():
        ref_b64 = base64.b64encode(Path(step.screenshot).read_bytes()).decode()

    # Build the prompt
    content: list[dict] = []

    if ref_b64:
        content.append(
            {
                "type": "text",
                "text": "REFERENCE SCREENSHOT (from when the action was recorded):",
            }
        )
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": ref_b64},
            }
        )

    content.append({"type": "text", "text": "CURRENT SCREENSHOT (live page now):"})
    content.append(
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": current_b64},
        }
    )

    # Build context about the step
    context_parts = [f"Action: {step.action}"]
    if step.tag:
        context_parts.append(f"Element tag: <{step.tag}>")
    if step.inner_text:
        context_parts.append(f"Element text: {step.inner_text!r}")
    if step.selectors.semantic:
        context_parts.append(f"Semantic description: {step.selectors.semantic}")
    if step.value:
        context_parts.append(f"Value to enter: {step.value!r}")
    if workflow_description:
        context_parts.append(f"Workflow context: {workflow_description}")

    instruction = (
        "Find the target element in the CURRENT screenshot and return its pixel "
        "coordinates as JSON: {\"x\": <int>, \"y\": <int>}\n\n"
        "Context:\n" + "\n".join(f"- {p}" for p in context_parts) + "\n\n"
        "Return ONLY the JSON object, no explanation."
    )
    content.append({"type": "text", "text": instruction})

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system=(
                "You are a browser automation assistant. Given screenshots of a web page, "
                "identify the pixel coordinates of a target element. The coordinates should "
                "be the center of the element in the CURRENT screenshot."
            ),
            messages=[{"role": "user", "content": content}],
        )

        text = response.content[0].text.strip()

        # Extract JSON from potential markdown code block
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            text = text[start:end]

        coords = json.loads(text)
        x, y = int(coords["x"]), int(coords["y"])

        logger.info("vision_fallback_coords", step=step.step, x=x, y=y)

        # Execute the action at the coordinates
        if step.action in ("click", "check"):
            page.mouse.click(x, y)
        elif step.action == "fill":
            page.mouse.click(x, y)
            # Select all existing text and replace
            page.keyboard.press("Control+a")
            page.keyboard.type(step.value or "")
        elif step.action == "select":
            # For selects, click to open then use keyboard
            page.mouse.click(x, y)
            if step.value:
                page.keyboard.type(step.value)
                page.keyboard.press("Enter")
        else:
            return StepResult(
                step=step.step,
                action=step.action,
                success=False,
                error=f"Vision fallback unsupported for action: {step.action}",
                fallback_used="vision",
            )

        # Wait for potential navigation
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        return StepResult(
            step=step.step,
            action=step.action,
            success=True,
            selector_used=f"vision({x},{y})",
            fallback_used="vision",
        )

    except Exception as e:
        logger.warning("vision_fallback_failed", step=step.step, error=str(e))
        return StepResult(
            step=step.step,
            action=step.action,
            success=False,
            error=f"Vision fallback failed: {e}",
            fallback_used="vision",
        )
