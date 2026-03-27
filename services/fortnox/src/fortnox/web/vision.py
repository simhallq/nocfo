"""Claude vision fallback for element discovery in Fortnox UI."""

import base64
import json
import re

import structlog
from playwright.sync_api import ElementHandle, Page, TimeoutError as PlaywrightTimeout

logger = structlog.get_logger()


def find_element(
    page: Page,
    key: str,
    description: str,
    *,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    timeout: int = 5000,
) -> ElementHandle | None:
    """Screenshot the page, ask Claude for a selector, try it.

    Returns the element handle if found, None otherwise.
    Requires the anthropic package and a valid API key.
    """
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("vision_fallback_skip", reason="anthropic package not installed")
        return None

    try:
        # Take screenshot
        screenshot_bytes = page.screenshot(type="png")
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")

        # Ask Claude for a selector
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f"I'm automating the Fortnox accounting UI (Swedish). "
                                f"I need to find: **{description}**. "
                                f"Page URL: {page.url}. "
                                f"Suggest a Playwright CSS selector. "
                                f'Respond with JSON: {{"selector": "...", "confidence": "high|medium|low"}}'
                            ),
                        },
                    ],
                }
            ],
        )

        # Parse response
        text = response.content[0].text
        # Extract JSON from response (may be wrapped in ```json ... ```)
        json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        else:
            # Try to find raw JSON object
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                text = json_match.group(0)

        parsed = json.loads(text)
        selector = parsed["selector"]
        confidence = parsed.get("confidence", "unknown")

        logger.info(
            "vision_selector_suggested",
            key=key,
            selector=selector,
            confidence=confidence,
        )

        # Try the suggested selector
        handle = page.wait_for_selector(selector, timeout=timeout, state="visible")
        if handle:
            logger.info("vision_selector_found", key=key, selector=selector)
            return handle

    except PlaywrightTimeout:
        logger.warning("vision_selector_not_found", key=key)
    except Exception as e:
        logger.warning("vision_fallback_error", key=key, error=str(e))

    return None
