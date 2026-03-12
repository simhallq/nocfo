"""Tests for recorder models — YAML round-trip and SelectorSet priority."""

from datetime import datetime
from pathlib import Path

from nocfo.recorder.models import SelectorSet, Workflow, WorkflowStep


class TestSelectorSet:
    def test_best_returns_data_testid_first(self):
        s = SelectorSet(
            data_testid="login-btn",
            id="btn1",
            css_path="div > button",
        )
        assert s.best() == '[data-testid="login-btn"]'

    def test_best_returns_id_when_no_testid(self):
        s = SelectorSet(id="btn1", css_path="div > button")
        assert s.best() == "#btn1"

    def test_best_returns_aria_when_no_id(self):
        s = SelectorSet(aria='[aria-label="Submit"]', css_path="div > button")
        assert s.best() == '[aria-label="Submit"]'

    def test_best_returns_name(self):
        s = SelectorSet(name="username", css_path="div > input")
        assert s.best() == '[name="username"]'

    def test_best_returns_text(self):
        s = SelectorSet(text="Click me", css_path="div > button")
        assert s.best() == 'text="Click me"'

    def test_best_returns_css_path(self):
        s = SelectorSet(css_path="div > button:nth-of-type(2)")
        assert s.best() == "div > button:nth-of-type(2)"

    def test_best_returns_nth_child(self):
        s = SelectorSet(nth_child="div > button:nth-child(3)")
        assert s.best() == "div > button:nth-child(3)"

    def test_best_skips_unstable_ids(self):
        # React-style _r_XX_ IDs
        s = SelectorSet(id="_r_1h_", text="Settings", css_path="a#_r_1h_")
        assert s.best() == 'text="Settings"'

        # UUID-style IDs
        s = SelectorSet(id="item-c82fb730-da40-4e12-b5f4-4fb36e632de8", text="Billing")
        assert s.best() == 'text="Billing"'

        # Stable IDs still work
        s = SelectorSet(id="submit-btn", text="Submit")
        assert s.best() == "#submit-btn"

    def test_best_returns_none_when_empty(self):
        s = SelectorSet()
        assert s.best() is None

    def test_best_returns_scoped_css_before_text(self):
        s = SelectorSet(
            scoped_css_path='[role="dialog"] section > button',
            text="OK",
            css_path="div > button",
        )
        assert s.best() == '[role="dialog"] section > button'

    def test_best_returns_placeholder(self):
        s = SelectorSet(placeholder="Search...", css_path="div > input")
        assert s.best() == '[placeholder="Search..."]'

    def test_all_selectors_order(self):
        s = SelectorSet(
            data_testid="x",
            id="y",
            name="z",
            scoped_css_path='[role="dialog"] div > span',
            placeholder="hint",
            text="label",
            css_path="div > span",
            nth_child="div > span:nth-child(1)",
        )
        result = s.all_selectors()
        assert result == [
            '[data-testid="x"]',
            "#y",
            '[name="z"]',
            '[role="dialog"] div > span',
            '[placeholder="hint"]',
            'text="label"',
            "div > span",
            "div > span:nth-child(1)",
        ]

    def test_all_selectors_empty(self):
        s = SelectorSet()
        assert s.all_selectors() == []


class TestWorkflowStep:
    def test_defaults(self):
        step = WorkflowStep(step=1, action="click")
        assert step.step == 1
        assert step.action == "click"
        assert step.value is None
        assert step.wait_before_ms == 0
        assert step.selectors.best() is None

    def test_with_selectors(self):
        step = WorkflowStep(
            step=1,
            action="fill",
            selectors=SelectorSet(id="email", name="email"),
            value="test@example.com",
        )
        assert step.selectors.best() == "#email"
        assert step.value == "test@example.com"


class TestWorkflow:
    def test_to_yaml_and_from_yaml(self, tmp_path: Path):
        workflow = Workflow(
            name="test_flow",
            recorded_at=datetime(2026, 1, 15, 10, 30, 0),
            start_url="https://example.com",
            total_steps=2,
            steps=[
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(id="login-btn", css_path="button#login-btn"),
                    tag="button",
                    inner_text="Log in",
                    url="https://example.com",
                    wait_before_ms=0,
                ),
                WorkflowStep(
                    step=2,
                    action="fill",
                    selectors=SelectorSet(name="username"),
                    value="admin",
                    tag="input",
                    url="https://example.com",
                    wait_before_ms=1200,
                ),
            ],
        )

        yaml_path = tmp_path / "test_flow.yaml"
        workflow.to_yaml(yaml_path)
        assert yaml_path.exists()

        loaded = Workflow.from_yaml(yaml_path)
        assert loaded.name == "test_flow"
        assert loaded.start_url == "https://example.com"
        assert loaded.total_steps == 2
        assert len(loaded.steps) == 2

        assert loaded.steps[0].action == "click"
        assert loaded.steps[0].selectors.id == "login-btn"
        assert loaded.steps[0].inner_text == "Log in"

        assert loaded.steps[1].action == "fill"
        assert loaded.steps[1].value == "admin"
        assert loaded.steps[1].wait_before_ms == 1200

    def test_yaml_creates_parent_dirs(self, tmp_path: Path):
        workflow = Workflow(name="nested", total_steps=0)
        yaml_path = tmp_path / "sub" / "dir" / "nested.yaml"
        workflow.to_yaml(yaml_path)
        assert yaml_path.exists()

    def test_round_trip_preserves_selectors(self, tmp_path: Path):
        workflow = Workflow(
            name="selectors_test",
            total_steps=1,
            steps=[
                WorkflowStep(
                    step=1,
                    action="click",
                    selectors=SelectorSet(
                        data_testid="submit",
                        id="btn-submit",
                        aria='[aria-label="Submit form"]',
                        name="submit",
                        text="Submit",
                        css_path="form > button.submit",
                        nth_child="form > button:nth-child(2)",
                        placeholder="Enter value",
                        semantic="Submit button in the login form",
                        container_selector='[data-testid="login-modal"]',
                        container_role="dialog",
                        scoped_css_path='[data-testid="login-modal"] form > button.submit',
                    ),
                ),
            ],
        )

        yaml_path = tmp_path / "selectors.yaml"
        workflow.to_yaml(yaml_path)
        loaded = Workflow.from_yaml(yaml_path)

        s = loaded.steps[0].selectors
        assert s.data_testid == "submit"
        assert s.id == "btn-submit"
        assert s.aria == '[aria-label="Submit form"]'
        assert s.name == "submit"
        assert s.text == "Submit"
        assert s.css_path == "form > button.submit"
        assert s.nth_child == "form > button:nth-child(2)"
        assert s.placeholder == "Enter value"
        assert s.semantic == "Submit button in the login form"
        assert s.container_selector == '[data-testid="login-modal"]'
        assert s.container_role == "dialog"
        assert s.scoped_css_path == '[data-testid="login-modal"] form > button.submit'
