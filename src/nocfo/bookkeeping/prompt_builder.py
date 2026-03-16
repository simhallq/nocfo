"""Build rich system prompts for invoice analysis using structured accounting rules."""

from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()

_DEFAULT_CONFIG = Path(__file__).parent / "accounting_rules.yaml"

_ROLE_PREAMBLE = """\
You are a Swedish bookkeeping assistant. You analyze PDF invoices and extract \
structured data for creating Fortnox vouchers (verifikat).

You will receive:
1. A PDF invoice
2. A list of active accounts from the company's Fortnox chart of accounts
3. Swedish accounting rules for correct account selection

Your job is to extract invoice details and suggest the correct bookkeeping entries.

General rules:
- The CREDIT side is always 1930 (Företagskonto) for bank payments
- The DEBIT side has one or more entries for the expense/asset + ingående moms (2640)
"""

_JSON_SCHEMA = """\
Return your analysis as JSON with this exact structure:
{
  "supplier_name": "Name on invoice",
  "invoice_number": "Invoice number",
  "invoice_date": "YYYY-MM-DD",
  "payment_date": "YYYY-MM-DD (due date or payment date)",
  "description": "Short description for the voucher",
  "items": [
    {
      "description": "What was purchased",
      "net_amount": 50000.00,
      "vat_rate": 12,
      "vat_amount": 6000.00,
      "total": 56000.00,
      "suggested_account": 1290,
      "account_reasoning": "Why this account was chosen"
    }
  ],
  "total_net": 50000.00,
  "total_vat": 6000.00,
  "total_gross": 56000.00,
  "confidence": "high/medium/low",
  "notes": "Any concerns or ambiguities"
}
"""


class AccountingPromptBuilder:
    """Loads accounting rules from YAML and assembles system prompts."""

    def __init__(self, config_path: Path | None = None) -> None:
        path = config_path or _DEFAULT_CONFIG
        try:
            self._config = yaml.safe_load(path.read_text())
            logger.debug("accounting_rules_loaded", path=str(path))
        except (FileNotFoundError, yaml.YAMLError) as e:
            logger.warning("accounting_rules_load_failed", error=str(e))
            self._config = {}

    def get_threshold(self, year: int) -> int:
        """Return half prisbasbelopp for the given year."""
        pbb = self._config.get("thresholds", {}).get("prisbasbelopp", {})
        if year in pbb:
            return pbb[year] // 2

        # Fall back to most recent year
        available = sorted(pbb.keys())
        if available:
            fallback = available[-1]
            logger.warning("prisbasbelopp_year_missing", requested=year, using=fallback)
            return pbb[fallback] // 2

        return 29600  # safe default

    def build_system_prompt(
        self,
        transaction_year: int,
        customer_id: str | None = None,
        supplier_history: list[dict] | None = None,
    ) -> str:
        """Assemble a complete system prompt from accounting rules."""
        sections = [_ROLE_PREAMBLE]

        # Threshold rule
        threshold = self.get_threshold(transaction_year)
        threshold_cfg = self._config.get("thresholds", {}).get("asset_vs_expense", {})
        sections.append(self._build_threshold_section(threshold, threshold_cfg))

        # VAT rules
        vat_rules = self._config.get("vat_rules", [])
        if vat_rules:
            sections.append(self._build_vat_section(vat_rules))

        # Account guidance
        guidance = self._config.get("account_guidance", [])
        if guidance:
            sections.append(self._build_account_section(guidance))

        # Company context
        if customer_id:
            companies = self._config.get("companies", {})
            if customer_id in companies:
                sections.append(self._build_company_section(companies[customer_id]))

        # Supplier history
        if supplier_history:
            sections.append(self._build_history_section(supplier_history))

        sections.append(_JSON_SCHEMA)
        return "\n".join(sections)

    @staticmethod
    def _build_threshold_section(threshold: int, cfg: dict) -> str:
        lines = [
            "## Asset vs Expense Threshold",
            f"Half prisbasbelopp for this year: {threshold:,} SEK (ex moms).",
        ]
        if cfg.get("rule"):
            lines.append(cfg["rule"].strip())
        for exc in cfg.get("exceptions", []):
            lines.append(f"EXCEPTION: {exc}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _build_vat_section(rules: list) -> str:
        lines = ["## VAT (Moms) Rules"]
        for r in rules:
            if r.get("name") == "reverse_charge":
                lines.append(f"- Omvänd skattskyldighet: {r.get('note', '').strip()}")
            else:
                lines.append(f"- {r['rate']}%: {r['applies_to']} → konto {r['account']}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _build_account_section(guidance: list) -> str:
        lines = ["## Account Selection Guide"]
        for g in guidance:
            lines.append(f"\n### {g['range']} — {g['label']}")
            lines.append(f"Rule: {g['rule']}")
            for num, desc in g.get("accounts", {}).items():
                lines.append(f"  {num}: {desc}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _build_company_section(company: dict) -> str:
        lines = [
            "## Company Context",
            f"Company: {company['name']}",
            f"Description: {company['description']}",
        ]
        for note in company.get("notes", []):
            lines.append(f"- {note}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _build_history_section(history: list[dict]) -> str:
        lines = [
            "## Recent Voucher History",
            "Use matching suppliers as precedent for account selection:",
        ]
        for h in history[:20]:
            desc = h.get("description", "")
            accts = h.get("accounts", "")
            date = h.get("date", "")
            amount = h.get("amount", "")
            lines.append(f"  {date} | {desc} | {accts} | {amount}")
        return "\n".join(lines) + "\n"
