"""Screenshot-reason-act loop with Claude for web automation."""

import json
import time

import anthropic
import structlog
from playwright.async_api import Page

from fortnox.config import get_settings
from fortnox.web_agent import actions

logger = structlog.get_logger()

MAX_ITERATIONS = 30
MAX_DURATION_SECONDS = 300  # 5 minutes
MAX_CONSECUTIVE_FAILURES = 3


class WebAgent:
    """Claude-powered web automation agent using screenshot-reason-act loop."""

    def __init__(self, page: Page, system_prompt: str) -> None:
        self._page = page
        self._system_prompt = system_prompt
        self._settings = get_settings()
        self._client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        self._history: list[dict] = []
        self._iteration = 0
        self._consecutive_failures = 0

    async def run(self) -> dict:
        """Execute the screenshot-reason-act loop until completion or timeout."""
        start_time = time.monotonic()
        result = {"status": "unknown", "message": "", "iterations": 0}

        for self._iteration in range(1, MAX_ITERATIONS + 1):
            elapsed = time.monotonic() - start_time
            if elapsed > MAX_DURATION_SECONDS:
                result = {
                    "status": "timeout",
                    "message": f"Timed out after {elapsed:.0f}s",
                    "iterations": self._iteration,
                }
                break

            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                result = {
                    "status": "error",
                    "message": "Too many consecutive failures",
                    "iterations": self._iteration,
                }
                break

            try:
                # Take screenshot
                screenshot_b64 = await actions.screenshot_base64(self._page)

                # Get Claude's decision
                action = await self._reason(screenshot_b64)

                if action.get("action") == "done":
                    result = {
                        "status": "success",
                        "message": action.get("result", "Task completed"),
                        "iterations": self._iteration,
                    }
                    break

                if action.get("action") == "error":
                    result = {
                        "status": "error",
                        "message": action.get("message", "Agent reported error"),
                        "iterations": self._iteration,
                    }
                    break

                # Execute action
                action_result = await self._execute(action)

                # Track failures
                if not action_result.success:
                    self._consecutive_failures += 1
                else:
                    self._consecutive_failures = 0

                # Record in history
                self._history.append(
                    {
                        "iteration": self._iteration,
                        "action": action,
                        "result": action_result.message or action_result.data,
                        "success": action_result.success,
                    }
                )

            except Exception as e:
                logger.error("agent_iteration_error", iteration=self._iteration, error=str(e))
                self._consecutive_failures += 1
                self._history.append(
                    {
                        "iteration": self._iteration,
                        "action": {"action": "error"},
                        "result": str(e),
                        "success": False,
                    }
                )
        else:
            result = {
                "status": "max_iterations",
                "message": f"Reached {MAX_ITERATIONS} iterations",
                "iterations": MAX_ITERATIONS,
            }

        logger.info("agent_run_complete", **result)
        return result

    async def _reason(self, screenshot_b64: str) -> dict:
        """Send screenshot to Claude and get the next action."""
        # Build message with history context
        history_text = ""
        if self._history:
            recent = self._history[-5:]  # Last 5 actions
            lines = []
            for h in recent:
                status = "OK" if h["success"] else "FAILED"
                lines.append(f"  Step {h['iteration']}: {h['action']} -> {status}: {h['result']}")
            history_text = "Recent action history:\n" + "\n".join(lines)

        user_content: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"Iteration {self._iteration}/{MAX_ITERATIONS}.\n"
                    f"{history_text}\n\n"
                    "Analyze the current screenshot and decide the next action. "
                    "Respond with a single JSON object."
                ),
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
            },
        ]

        response = self._client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )

        # Parse JSON from response
        text = response.content[0].text
        # Extract JSON from potential markdown code block
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            text = text[start:end]

        try:
            return json.loads(text)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            logger.warning("failed_to_parse_agent_response", text=text[:200])
            return {"action": "error", "message": "Failed to parse agent response"}

    async def _execute(self, action: dict) -> actions.ActionResult:
        """Execute a browser action returned by Claude."""
        action_type = action.get("action", "")

        match action_type:
            case "click":
                return await actions.click(self._page, action["selector"])
            case "fill":
                return await actions.fill(self._page, action["selector"], action["value"])
            case "select":
                return await actions.select_option(self._page, action["selector"], action["value"])
            case "scroll":
                return await actions.scroll(
                    self._page,
                    action.get("direction", "down"),
                    action.get("amount", 500),
                )
            case "navigate":
                return await actions.navigate(self._page, action["url"])
            case "extract_text":
                return await actions.extract_text(self._page, action.get("selector", "body"))
            case "extract_table":
                return await actions.extract_table(self._page, action["selector"])
            case _:
                return actions.ActionResult(success=False, message=f"Unknown action: {action_type}")
