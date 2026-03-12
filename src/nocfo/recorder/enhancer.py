"""Optional Claude vision enhancement for workflow selectors."""

import base64
from pathlib import Path

import structlog

from .models import Workflow

logger = structlog.get_logger()


def enhance_workflow(workflow: Workflow) -> Workflow:
    """Enhance workflow selectors using Claude vision analysis.

    Sends each step's screenshot to Claude and asks for a semantic
    description of the interacted element. Updates the SelectorSet.semantic field.
    """
    from anthropic import Anthropic

    from nocfo.config import get_settings

    settings = get_settings()
    if not settings.validate_anthropic_key():
        logger.warning("no_anthropic_key", msg="Skipping vision enhancement")
        return workflow

    client = Anthropic(api_key=settings.anthropic_api_key)

    for step in workflow.steps:
        if not step.screenshot or not Path(step.screenshot).exists():
            continue

        try:
            img_data = base64.b64encode(Path(step.screenshot).read_bytes()).decode()

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=256,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    f"This screenshot was taken during a browser automation "
                                    f"recording. The user performed a '{step.action}' action "
                                    f"on a <{step.tag}> element"
                                    f"{' with text: ' + step.inner_text if step.inner_text else ''}"
                                    f". CSS selector: {step.selectors.css_path or 'none'}.\n\n"
                                    f"Provide a brief semantic description of the element that "
                                    f"was interacted with (e.g., 'Login button in the top "
                                    f"navigation bar'). Reply with ONLY the description, "
                                    f"no explanation."
                                ),
                            },
                        ],
                    }
                ],
            )

            semantic = response.content[0].text.strip()
            step.selectors.semantic = semantic
            logger.info("step_enhanced", step=step.step, semantic=semantic)

        except Exception as e:
            logger.warning("enhance_step_failed", step=step.step, error=str(e))

    return workflow
