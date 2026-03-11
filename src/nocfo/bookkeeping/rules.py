"""YAML-driven rule engine for auto-categorizing bank transactions."""

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()


@dataclass
class CategorizedTransaction:
    """Result of categorizing a bank transaction."""

    rule_name: str
    description: str
    debit_account: int
    credit_account: int
    vat_code: str | None
    confidence: float = 1.0


@dataclass
class UncategorizedTransaction:
    """A transaction that didn't match any rule."""

    original_description: str
    amount: Decimal
    reason: str = "no_matching_rule"


class RuleEngine:
    """Loads categorization rules from YAML and matches transactions."""

    def __init__(self, rules_path: Path | None = None) -> None:
        self._rules_path = rules_path or Path("rules.yaml")
        self._compiled_rules: list[tuple[re.Pattern, dict]] = []
        self._default_action: str = "flag_for_review"

    def load(self) -> None:
        """Load rules from YAML file and pre-compile regex patterns."""
        if not self._rules_path.exists():
            logger.warning("rules_file_not_found", path=str(self._rules_path))
            return

        with open(self._rules_path) as f:
            data = yaml.safe_load(f)

        rules = data.get("rules", [])
        default = data.get("default", {})
        self._default_action = default.get("action", "flag_for_review")

        self._compiled_rules = []
        for rule in rules:
            flags = re.IGNORECASE if rule.get("case_insensitive", False) else 0
            self._compiled_rules.append((re.compile(rule["pattern"], flags), rule))

        logger.info("rules_loaded", count=len(self._compiled_rules))

    def categorize(
        self,
        description: str,
        amount: Decimal,
    ) -> CategorizedTransaction | UncategorizedTransaction:
        """Match a bank transaction description against rules.

        Rules define debit/credit accounts per transaction type.
        """
        for pattern, rule in self._compiled_rules:
            if pattern.search(description):
                logger.debug(
                    "transaction_categorized",
                    rule=rule["name"],
                    description=description[:50],
                )
                return CategorizedTransaction(
                    rule_name=rule["name"],
                    description=rule.get("description", description),
                    debit_account=rule["debit_account"],
                    credit_account=rule["credit_account"],
                    vat_code=rule.get("vat_code"),
                )

        logger.info("transaction_uncategorized", description=description[:50])
        return UncategorizedTransaction(
            original_description=description,
            amount=amount,
        )
