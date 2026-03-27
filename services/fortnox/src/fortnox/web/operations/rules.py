"""Regelverk (auto-booking rules) management via Fortnox browser UI."""

from typing import Any

import structlog
from playwright.sync_api import Page

from fortnox.web.evidence import EvidenceCapture
from fortnox.web.navigate import open_settings_item

logger = structlog.get_logger()


def list_rules(page: Page) -> dict:
    """List current Regelverk (Automatkontering rules) from Fortnox.

    Navigation: ensure app → settings page → iframe → Automatkontering expander.
    """
    logger.info("rules_list_start")
    evidence = EvidenceCapture("rules")

    try:
        iframe = open_settings_item(page, "Automatkontering")
        if not iframe:
            evidence.capture(page, "automatkontering_not_found")
            return {"status": "error", "message": "Could not open Automatkontering settings"}

        evidence.capture(page, "automatkontering_open")

        # Extract rules from the expanded section
        rules = _extract_rules_from_iframe(iframe)

        logger.info("rules_list_success", count=len(rules))
        evidence.capture(page, "rules_listed")
        return {"status": "ok", "rules": rules}

    except Exception as e:
        logger.error("rules_list_error", error=str(e))
        evidence.capture(page, "error")
        return {"status": "error", "message": str(e)}


def sync_rules(page: Page, *, rules: list[dict[str, Any]]) -> dict:
    """Sync rules to Fortnox — create/update Regelverk entries."""
    logger.info("rules_sync_start", rule_count=len(rules))
    evidence = EvidenceCapture("rules_sync")

    try:
        iframe = open_settings_item(page, "Automatkontering")
        if not iframe:
            return {"status": "error", "message": "Could not open Automatkontering settings"}

        evidence.capture(page, "automatkontering_open")

        created = 0
        failed = 0

        for rule in rules:
            try:
                _sync_single_rule(iframe, rule)
                created += 1
            except Exception as e:
                logger.warning("rule_sync_failed", rule=rule.get("name"), error=str(e))
                failed += 1

        result = {
            "status": "ok" if failed == 0 else "partial",
            "created": created,
            "failed": failed,
            "total": len(rules),
        }
        logger.info("rules_sync_complete", **result)
        evidence.capture(page, "sync_complete")
        return result

    except Exception as e:
        logger.error("rules_sync_error", error=str(e))
        return {"status": "error", "message": str(e)}


def _extract_rules_from_iframe(iframe) -> list[dict[str, Any]]:
    """Extract rule data from the expanded Automatkontering section.

    Table columns: NUMMER | BENÄMNING | KONTO | (delete button)
    """
    rules: list[dict[str, Any]] = []

    rows = iframe.query_selector_all("table tbody tr")
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) >= 2:
            nummer = (cells[0].text_content() or "").strip()
            benamning = (cells[1].text_content() or "").strip()
            konto = (cells[2].text_content() or "").strip() if len(cells) > 2 else ""
            if nummer or benamning:  # Skip empty rows
                rules.append({
                    "number": nummer,
                    "name": benamning,
                    "account": konto,
                })

    return rules


def _sync_single_rule(iframe, rule: dict[str, Any]) -> None:
    """Create or update a single rule in Fortnox."""
    name = rule.get("name", "")

    # Try to find existing rule
    existing = iframe.query_selector(f"tr:has-text('{name}')")
    if existing:
        existing.click()
    else:
        # Create new
        add_btn = iframe.query_selector("button:has-text('Ny'), button:has-text('Lägg till'), .icon-plus-sign")
        if add_btn:
            add_btn.click()
        else:
            raise RuntimeError(f"Could not find add button for rule: {name}")

    iframe.wait_for_timeout(1000)

    # Save
    save_btn = iframe.query_selector("button:has-text('Spara'), input[value='Spara']")
    if save_btn:
        save_btn.click()
        iframe.wait_for_timeout(1000)
    else:
        raise RuntimeError(f"Could not save rule: {name}")
