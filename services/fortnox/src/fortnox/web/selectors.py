"""Selector resolution with ordered fallbacks for Fortnox UI elements.

Three-stage resolution:
1. YAML selectors — static definitions from selectors.yaml
2. Learned selectors — persisted from previous vision discoveries
3. Vision fallback — Claude screenshot analysis (when API key is set)
"""

from pathlib import Path
from typing import Any

import structlog
import yaml
from playwright.sync_api import ElementHandle, Page, TimeoutError as PlaywrightTimeout

from fortnox.web.learned import LearnedSelectors

logger = structlog.get_logger()

_SELECTORS: dict[str, Any] | None = None
_learned: LearnedSelectors | None = None


def _load_selectors() -> dict[str, Any]:
    """Load selector definitions from YAML."""
    global _SELECTORS
    if _SELECTORS is None:
        yaml_path = Path(__file__).parent / "selectors.yaml"
        with open(yaml_path) as f:
            _SELECTORS = yaml.safe_load(f)
    return _SELECTORS


def _get_learned() -> LearnedSelectors:
    """Get the shared LearnedSelectors instance."""
    global _learned
    if _learned is None:
        _learned = LearnedSelectors()
    return _learned


def _resolve_node(key: str) -> Any:
    """Resolve a dotted key to its raw YAML node (dict or list)."""
    selectors = _load_selectors()
    parts = key.split(".")
    node: Any = selectors
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"Selector key not found: {key!r} (failed at {part!r})")
        node = node[part]
    return node


def _resolve_key(key: str, **kwargs: str) -> list[str]:
    """Resolve a dotted key (e.g. 'login.bankid_tab') to a list of selectors.

    Handles both formats:
    - Old: leaf is a list of selector strings
    - New: leaf is a dict with 'selectors' list and optional 'description'

    Template variables in selectors are substituted from kwargs.
    """
    node = _resolve_node(key)

    # New format: dict with 'selectors' key
    if isinstance(node, dict) and "selectors" in node:
        raw_selectors = node["selectors"]
    elif isinstance(node, list):
        raw_selectors = node
    else:
        raise ValueError(f"Selector key {key!r} does not resolve to a list or selector dict: {type(node)}")

    # Substitute template variables
    resolved = []
    for sel in raw_selectors:
        try:
            resolved.append(sel.format(**kwargs))
        except KeyError:
            # Skip selectors with unresolved templates
            continue
    return resolved


def _resolve_description(key: str) -> str:
    """Get the description field for a selector key, or a fallback."""
    try:
        node = _resolve_node(key)
        if isinstance(node, dict) and "description" in node:
            return node["description"]
    except (KeyError, ValueError):
        pass
    # Fallback: derive from key
    return key.replace(".", " ").replace("_", " ")


def find(
    page: Page,
    key: str,
    timeout: int = 10000,
    *,
    vision_api_key: str = "",
    **kwargs: str,
) -> ElementHandle:
    """Try each fallback selector for a key. Return the first match.

    Three stages:
    1. YAML selectors (static definitions)
    2. Learned selectors (from previous vision discoveries)
    3. Vision fallback (Claude screenshot analysis, if API key is set)

    Raises TimeoutError if none match.
    """
    yaml_selectors = _resolve_key(key, **kwargs)
    if not yaml_selectors:
        raise ValueError(f"No selectors resolved for key: {key!r}")

    # --- Stage 1: YAML selectors ---
    per_selector_timeout = max(timeout // max(len(yaml_selectors), 1), 2000)

    for i, selector in enumerate(yaml_selectors):
        try:
            handle = page.wait_for_selector(selector, timeout=per_selector_timeout, state="visible")
            if handle:
                logger.debug(
                    "selector_found",
                    key=key,
                    selector=selector,
                    stage="yaml",
                    fallback_level=i,
                )
                return handle
        except PlaywrightTimeout:
            continue

    # --- Stage 2: Learned selectors ---
    learned = _get_learned()
    learned_selectors = learned.get(key)
    for selector in learned_selectors:
        try:
            handle = page.wait_for_selector(selector, timeout=3000, state="visible")
            if handle:
                learned.increment_used(key)
                logger.debug(
                    "selector_found",
                    key=key,
                    selector=selector,
                    stage="learned",
                )
                return handle
        except PlaywrightTimeout:
            # Prune failed learned selector
            learned.remove(key, selector)
            continue

    # --- Stage 3: Vision fallback ---
    if vision_api_key:
        from fortnox.web.vision import find_element

        description = _resolve_description(key)
        handle = find_element(page, key, description, api_key=vision_api_key)
        if handle:
            # Extract the selector that worked (we can't easily, so we note the description)
            logger.info("selector_found", key=key, stage="vision")
            return handle

    raise PlaywrightTimeout(
        f"No selector matched for {key!r} within {timeout}ms. "
        f"Tried: {yaml_selectors}"
    )


def click(page: Page, key: str, timeout: int = 10000, **kwargs: str) -> None:
    """Find an element by selector key and click it."""
    element = find(page, key, timeout=timeout, **kwargs)
    element.click()
    logger.debug("selector_click", key=key)


def fill(page: Page, key: str, value: str, timeout: int = 10000, **kwargs: str) -> None:
    """Find an element by selector key and fill it with text."""
    element = find(page, key, timeout=timeout, **kwargs)
    element.fill(value)
    logger.debug("selector_fill", key=key, value_len=len(value))


def wait_for(page: Page, key: str, timeout: int = 30000, **kwargs: str) -> ElementHandle:
    """Wait for any selector in the fallback list to appear."""
    return find(page, key, timeout=timeout, **kwargs)
