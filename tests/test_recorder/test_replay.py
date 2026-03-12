"""Tests for ReplayEngine with mocked Page."""

from unittest.mock import MagicMock

import pytest

from nocfo.recorder.models import SelectorSet, Workflow, WorkflowStep
from nocfo.recorder.replay import ReplayEngine


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
