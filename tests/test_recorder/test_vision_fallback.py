"""Tests for vision fallback module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nocfo.recorder.models import SelectorSet, WorkflowStep
from nocfo.recorder.vision_fallback import vision_fallback_step


@pytest.fixture
def mock_page():
    page = MagicMock()
    page.screenshot.return_value = b"\x89PNG\r\n\x1a\nfake"
    page.mouse = MagicMock()
    page.keyboard = MagicMock()
    page.wait_for_load_state = MagicMock()
    return page


@pytest.fixture
def mock_anthropic():
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text='{"x": 450, "y": 320}')]
    client.messages.create.return_value = response
    return client


def make_step(action="click", **kwargs):
    return WorkflowStep(step=1, action=action, **kwargs)


class TestVisionFallbackStep:
    def test_click_action(self, mock_page, mock_anthropic):
        step = make_step(
            action="click",
            selectors=SelectorSet(semantic="Login button"),
            tag="button",
            inner_text="Log in",
        )

        result = vision_fallback_step(
            mock_page, step, anthropic_client=mock_anthropic
        )

        assert result.success
        assert result.fallback_used == "vision"
        assert result.selector_used == "vision(450,320)"
        mock_page.mouse.click.assert_called_once_with(450, 320)

    def test_fill_action(self, mock_page, mock_anthropic):
        step = make_step(
            action="fill",
            selectors=SelectorSet(name="email"),
            value="test@example.com",
        )

        result = vision_fallback_step(
            mock_page, step, anthropic_client=mock_anthropic
        )

        assert result.success
        mock_page.mouse.click.assert_called_once_with(450, 320)
        mock_page.keyboard.press.assert_called_once_with("Control+a")
        mock_page.keyboard.type.assert_called_once_with("test@example.com")

    def test_check_action(self, mock_page, mock_anthropic):
        step = make_step(action="check", selectors=SelectorSet(id="agree"))

        result = vision_fallback_step(
            mock_page, step, anthropic_client=mock_anthropic
        )

        assert result.success
        mock_page.mouse.click.assert_called_once_with(450, 320)

    def test_select_action(self, mock_page, mock_anthropic):
        step = make_step(
            action="select",
            selectors=SelectorSet(id="country"),
            value="SE",
        )

        result = vision_fallback_step(
            mock_page, step, anthropic_client=mock_anthropic
        )

        assert result.success
        mock_page.mouse.click.assert_called_once_with(450, 320)
        mock_page.keyboard.type.assert_called_once_with("SE")
        mock_page.keyboard.press.assert_called_once_with("Enter")

    def test_unsupported_action(self, mock_page, mock_anthropic):
        step = make_step(action="hover", selectors=SelectorSet())

        result = vision_fallback_step(
            mock_page, step, anthropic_client=mock_anthropic
        )

        assert not result.success
        assert "unsupported" in result.error.lower()
        assert result.fallback_used == "vision"

    def test_prompt_includes_both_images(self, mock_page, mock_anthropic, tmp_path):
        ref_img = tmp_path / "ref.png"
        ref_img.write_bytes(b"\x89PNG\r\n\x1a\nreference")

        step = make_step(
            selectors=SelectorSet(semantic="Settings link"),
            screenshot=str(ref_img),
            tag="a",
            inner_text="Settings",
        )

        vision_fallback_step(mock_page, step, anthropic_client=mock_anthropic)

        call_args = mock_anthropic.messages.create.call_args
        content = call_args[1]["messages"][0]["content"]

        # Should have: ref text, ref image, current text, current image, instruction
        image_blocks = [b for b in content if b.get("type") == "image"]
        assert len(image_blocks) == 2

    def test_prompt_without_reference_screenshot(self, mock_page, mock_anthropic):
        step = make_step(selectors=SelectorSet(), screenshot=None)

        vision_fallback_step(mock_page, step, anthropic_client=mock_anthropic)

        call_args = mock_anthropic.messages.create.call_args
        content = call_args[1]["messages"][0]["content"]

        image_blocks = [b for b in content if b.get("type") == "image"]
        assert len(image_blocks) == 1  # Only current screenshot

    def test_prompt_includes_context(self, mock_page, mock_anthropic):
        step = make_step(
            selectors=SelectorSet(semantic="Submit button"),
            tag="button",
            inner_text="Submit",
            value="hello",
        )

        vision_fallback_step(
            mock_page,
            step,
            workflow_description="Logs into the admin portal",
            anthropic_client=mock_anthropic,
        )

        call_args = mock_anthropic.messages.create.call_args
        content = call_args[1]["messages"][0]["content"]
        text_blocks = [b["text"] for b in content if b.get("type") == "text"]
        instruction = text_blocks[-1]

        assert "click" in instruction
        assert "Submit button" in instruction
        assert "Submit" in instruction or "button" in instruction
        assert "Logs into the admin portal" in instruction

    def test_handles_markdown_code_block(self, mock_page):
        client = MagicMock()
        response = MagicMock()
        response.content = [MagicMock(text='```json\n{"x": 100, "y": 200}\n```')]
        client.messages.create.return_value = response

        step = make_step(selectors=SelectorSet())
        result = vision_fallback_step(mock_page, step, anthropic_client=client)

        assert result.success
        mock_page.mouse.click.assert_called_once_with(100, 200)

    def test_handles_bad_json(self, mock_page):
        client = MagicMock()
        response = MagicMock()
        response.content = [MagicMock(text="I cannot determine the coordinates")]
        client.messages.create.return_value = response

        step = make_step(selectors=SelectorSet())
        result = vision_fallback_step(mock_page, step, anthropic_client=client)

        assert not result.success
        assert "Vision fallback failed" in result.error

    def test_handles_api_error(self, mock_page):
        client = MagicMock()
        client.messages.create.side_effect = Exception("API rate limit")

        step = make_step(selectors=SelectorSet())
        result = vision_fallback_step(mock_page, step, anthropic_client=client)

        assert not result.success
        assert "API rate limit" in result.error
        assert result.fallback_used == "vision"
