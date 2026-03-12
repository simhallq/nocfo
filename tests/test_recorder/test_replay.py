"""Tests for ReplayEngine with mocked Page."""

from unittest.mock import MagicMock, patch

import pytest

from nocfo.recorder.models import SelectorSet, Workflow, WorkflowStep
from nocfo.recorder.replay import ReplayEngine, StepResult


@pytest.fixture
def mock_page():
    """Create a mock Playwright sync Page."""
    page = MagicMock()
    page.goto = MagicMock()
    page.click = MagicMock()
    page.fill = MagicMock()
    page.select_option = MagicMock()
    page.check = MagicMock()
    page.wait_for_selector = MagicMock()
    page.wait_for_timeout = MagicMock()
    page.wait_for_load_state = MagicMock()
    return page


def make_workflow(steps: list[WorkflowStep], start_url: str = "") -> Workflow:
    return Workflow(
        name="test",
        start_url=start_url,
        total_steps=len(steps),
        steps=steps,
    )


class TestReplayEngine:
    def test_replay_click_step(self, mock_page):
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(id="submit-btn"),
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        assert result.passed == 1
        assert result.failed == 0
        mock_page.click.assert_called_once_with("#submit-btn", timeout=10000)

    def test_replay_fill_step(self, mock_page):
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="fill",
                    selectors=SelectorSet(name="email"),
                    value="test@example.com",
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        mock_page.fill.assert_called_once_with(
            '[name="email"]', "test@example.com", timeout=10000
        )

    def test_replay_select_step(self, mock_page):
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="select",
                    selectors=SelectorSet(id="country"),
                    value="SE",
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        mock_page.select_option.assert_called_once_with("#country", "SE", timeout=10000)

    def test_replay_check_step(self, mock_page):
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="check",
                    selectors=SelectorSet(id="agree"),
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        mock_page.check.assert_called_once_with("#agree", timeout=10000)

    def test_replay_navigate_step(self, mock_page):
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="navigate",
                    url="https://example.com/page2",
                    selectors=SelectorSet(),
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        mock_page.goto.assert_called_with(
            "https://example.com/page2", wait_until="domcontentloaded", timeout=30000
        )

    def test_replay_navigates_to_start_url(self, mock_page):
        workflow = make_workflow(
            [],
            start_url="https://example.com/start",
        )

        engine = ReplayEngine(workflow, mock_page)
        engine.run()

        mock_page.goto.assert_called_once_with(
            "https://example.com/start", wait_until="domcontentloaded", timeout=30000
        )

    def test_selector_fallback(self, mock_page):
        """When the first selector fails, try the next one."""
        mock_page.wait_for_selector.side_effect = [
            Exception("not found"),  # data_testid fails
            None,  # id succeeds
        ]

        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(data_testid="btn", id="fallback"),
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        assert result.step_results[0].selector_used == "#fallback"

    def test_all_selectors_fail(self, mock_page):
        mock_page.wait_for_selector.side_effect = Exception("not found")

        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(id="gone"),
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert not result.success
        assert result.failed == 1

    def test_no_selectors_available(self, mock_page):
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(),
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert not result.success
        assert "No selectors" in result.step_results[0].error

    def test_strict_mode_stops_on_failure(self, mock_page):
        mock_page.wait_for_selector.side_effect = Exception("not found")

        workflow = make_workflow(
            [
                WorkflowStep(step=1, action="click", selectors=SelectorSet(id="a")),
                WorkflowStep(step=2, action="click", selectors=SelectorSet(id="b")),
            ]
        )

        engine = ReplayEngine(workflow, mock_page, strict=True)
        result = engine.run()

        assert result.failed == 1
        assert result.passed == 0
        assert len(result.step_results) == 1  # Stopped after first failure

    def test_non_strict_mode_continues(self, mock_page):
        # First step fails, second succeeds
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("not found")

        mock_page.wait_for_selector.side_effect = side_effect

        workflow = make_workflow(
            [
                WorkflowStep(step=1, action="click", selectors=SelectorSet(id="a")),
                WorkflowStep(step=2, action="click", selectors=SelectorSet(id="b")),
            ]
        )

        engine = ReplayEngine(workflow, mock_page, strict=False)
        result = engine.run()

        assert result.failed == 1
        assert result.passed == 1
        assert len(result.step_results) == 2

    def test_wait_before_ms_applied(self, mock_page):
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(id="btn"),
                    wait_before_ms=2000,
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page, speed=1.0)
        engine.run()

        mock_page.wait_for_timeout.assert_called_once_with(2000)

    def test_speed_multiplier_affects_wait(self, mock_page):
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(id="btn"),
                    wait_before_ms=2000,
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page, speed=2.0)
        engine.run()

        mock_page.wait_for_timeout.assert_called_once_with(1000)

    def test_multiple_steps_sequenced(self, mock_page):
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(id="login"),
                ),
                WorkflowStep(
                    step=2,
                    action="fill",
                    selectors=SelectorSet(name="user"),
                    value="admin",
                ),
                WorkflowStep(
                    step=3,
                    action="click",
                    selectors=SelectorSet(id="submit"),
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        assert result.passed == 3
        assert result.failed == 0

    def test_container_wait_before_selectors(self, mock_page):
        """When step has container_selector, wait for it before trying selectors."""
        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(
                        id="ok-btn",
                        container_selector='[role="dialog"]',
                    ),
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        # First call should be the container wait, second the element wait
        calls = mock_page.wait_for_selector.call_args_list
        assert calls[0][0][0] == '[role="dialog"]'
        assert calls[0][1]["timeout"] == 15000
        assert calls[1][0][0] == "#ok-btn"

    def test_container_wait_failure_still_tries_selectors(self, mock_page):
        """If container wait times out, selectors are still attempted."""
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("timeout waiting for container")

        mock_page.wait_for_selector.side_effect = side_effect

        workflow = make_workflow(
            [
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(
                        id="ok-btn",
                        container_selector='[role="dialog"]',
                    ),
                ),
            ]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        assert result.step_results[0].selector_used == "#ok-btn"

    def test_replay_result_properties(self, mock_page):
        workflow = make_workflow([], start_url="")
        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.success
        assert result.workflow_name == "test"
        assert result.total_steps == 0


class TestVisionFallbackIntegration:
    def test_vision_not_called_when_disabled(self, mock_page):
        """Vision fallback should not be attempted when vision_fallback=False."""
        mock_page.wait_for_selector.side_effect = Exception("not found")

        workflow = make_workflow(
            [WorkflowStep(step=1, action="click", selectors=SelectorSet(id="gone"))]
        )

        with patch(
            "nocfo.recorder.vision_fallback.vision_fallback_step"
        ) as mock_vision:
            engine = ReplayEngine(workflow, mock_page, vision_fallback=False)
            result = engine.run()

            mock_vision.assert_not_called()
            assert not result.success

    def test_vision_called_after_selector_failure(self, mock_page):
        """Vision fallback should be called when selectors fail and vision is enabled."""
        mock_page.wait_for_selector.side_effect = Exception("not found")

        workflow = make_workflow(
            [WorkflowStep(step=1, action="click", selectors=SelectorSet(id="gone"))]
        )

        vision_result = StepResult(
            step=1,
            action="click",
            success=True,
            selector_used="vision(100,200)",
            fallback_used="vision",
        )

        with patch(
            "nocfo.recorder.vision_fallback.vision_fallback_step",
            return_value=vision_result,
        ) as mock_vision:
            engine = ReplayEngine(workflow, mock_page, vision_fallback=True)
            result = engine.run()

            mock_vision.assert_called_once()
            assert result.success
            assert result.step_results[0].fallback_used == "vision"

    def test_vision_called_when_no_selectors(self, mock_page):
        """Vision fallback should be tried even when there are no selectors."""
        workflow = make_workflow(
            [WorkflowStep(step=1, action="click", selectors=SelectorSet())]
        )

        vision_result = StepResult(
            step=1,
            action="click",
            success=True,
            selector_used="vision(50,60)",
            fallback_used="vision",
        )

        with patch(
            "nocfo.recorder.vision_fallback.vision_fallback_step",
            return_value=vision_result,
        ) as mock_vision:
            engine = ReplayEngine(workflow, mock_page, vision_fallback=True)
            result = engine.run()

            mock_vision.assert_called_once()
            assert result.success

    def test_max_vision_fallbacks_budget(self, mock_page):
        """Vision fallback should stop after max_vision_fallbacks attempts."""
        mock_page.wait_for_selector.side_effect = Exception("not found")

        workflow = make_workflow(
            [
                WorkflowStep(step=i, action="click", selectors=SelectorSet(id=f"s{i}"))
                for i in range(1, 5)
            ]
        )

        vision_result = StepResult(
            step=0, action="click", success=True, fallback_used="vision"
        )

        call_count = [0]

        def counted_vision(*args, **kwargs):
            call_count[0] += 1
            return StepResult(
                step=args[1].step,
                action="click",
                success=True,
                fallback_used="vision",
            )

        with patch(
            "nocfo.recorder.vision_fallback.vision_fallback_step",
            side_effect=counted_vision,
        ):
            engine = ReplayEngine(
                workflow, mock_page, vision_fallback=True, max_vision_fallbacks=2, strict=False
            )
            result = engine.run()

            # Only 2 vision calls should happen (budget of 2)
            assert call_count[0] == 2
            # 2 passed via vision, 2 failed (no budget left)
            assert result.passed == 2
            assert result.failed == 2

    def test_fallback_used_field_on_step_result(self, mock_page):
        """StepResult should have empty fallback_used by default."""
        workflow = make_workflow(
            [WorkflowStep(step=1, action="click", selectors=SelectorSet(id="btn"))]
        )

        engine = ReplayEngine(workflow, mock_page)
        result = engine.run()

        assert result.step_results[0].fallback_used == ""
