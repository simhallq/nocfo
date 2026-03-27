"""Process a PDF invoice into a Fortnox voucher using Claude Vision."""

import base64
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import anthropic
import structlog

from fortnox.bookkeeping.prompt_builder import AccountingPromptBuilder
from fortnox.api.accounts import AccountService
from fortnox.api.client import FortnoxClient
from fortnox.api.file_connections import FileConnectionService
from fortnox.api.inbox import InboxService
from fortnox.api.models import Voucher, VoucherRow
from fortnox.api.vouchers import VoucherService

logger = structlog.get_logger()


@dataclass
class InvoiceAnalysis:
    """Result of analyzing a PDF invoice."""

    supplier_name: str
    invoice_number: str
    invoice_date: date
    payment_date: date
    description: str
    items: list[dict]
    total_net: Decimal
    total_vat: Decimal
    total_gross: Decimal
    vat_rate: int
    confidence: str
    notes: str

    def to_voucher(self, transaction_date: date | None = None) -> Voucher:
        """Convert analysis to a Fortnox Voucher."""
        txn_date = transaction_date or self.payment_date

        rows = [
            VoucherRow(account=1930, debit=Decimal("0"), credit=self.total_gross),
        ]

        for item in self.items:
            rows.append(VoucherRow(
                account=item["suggested_account"],
                debit=Decimal(str(item["net_amount"])),
                credit=Decimal("0"),
                transaction_information=item["description"],
            ))

        if self.total_vat > 0:
            rows.append(VoucherRow(
                account=2640,
                debit=self.total_vat,
                credit=Decimal("0"),
            ))

        return Voucher(
            description=self.supplier_name,
            voucher_series="A",
            transaction_date=txn_date,
            rows=rows,
        )

    def preview(self) -> str:
        """Human-readable preview of the proposed voucher."""
        lines = [
            f"  Supplier:     {self.supplier_name}",
            f"  Invoice:      #{self.invoice_number} ({self.invoice_date})",
            f"  Payment date: {self.payment_date}",
            f"  Description:  {self.description}",
            f"  Confidence:   {self.confidence}",
            "",
            f"  {'KONTO':<8} {'BESKRIVNING':<45} {'DEBET':>12} {'KREDIT':>12}",
            f"  {'─'*8} {'─'*45} {'─'*12} {'─'*12}",
            f"  {'1930':<8} {'Företagskonto':<45} {'':>12} {self.total_gross:>12,.2f}",
        ]
        for item in self.items:
            acct = item["suggested_account"]
            desc = item["description"][:45]
            lines.append(
                f"  {acct:<8} {desc:<45} {Decimal(str(item['net_amount'])):>12,.2f} {'':>12}"
            )
        if self.total_vat > 0:
            lines.append(
                f"  {'2640':<8} {'Ingående moms':<45} {self.total_vat:>12,.2f} {'':>12}"
            )
        lines.extend([
            f"  {'─'*8} {'─'*45} {'─'*12} {'─'*12}",
            f"  {'':8} {'Summa':<45} {self.total_gross:>12,.2f} {self.total_gross:>12,.2f}",
        ])

        if self.notes:
            lines.extend(["", f"  Notes: {self.notes}"])

        for item in self.items:
            lines.append(f"  Account {item['suggested_account']}: {item['account_reasoning']}")

        return "\n".join(lines)


async def analyze_invoice(
    pdf_path: Path,
    accounts: list[dict],
    anthropic_api_key: str,
    transaction_year: int | None = None,
    customer_id: str | None = None,
    supplier_history: list[dict] | None = None,
) -> InvoiceAnalysis:
    """Use Claude Vision to analyze a PDF invoice and suggest bookkeeping entries."""
    pdf_bytes = pdf_path.read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode()

    # Build compact account list for context
    account_list = "\n".join(
        f"{a['number']}\t{a['description']}"
        for a in sorted(accounts, key=lambda x: x["number"])
    )

    # Build rich system prompt from accounting rules
    year = transaction_year or date.today().year
    builder = AccountingPromptBuilder()
    system_prompt = builder.build_system_prompt(
        transaction_year=year,
        customer_id=customer_id,
        supplier_history=supplier_history,
    )

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Analyze this invoice and return the JSON structure "
                            f"as described in your instructions.\n\n"
                            f"Available accounts:\n{account_list}"
                        ),
                    },
                ],
            }
        ],
        system=system_prompt,
    )

    # Extract JSON from response
    text = response.content[0].text
    # Handle markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    data = json.loads(text.strip())

    # Determine dominant VAT rate
    vat_rates = [item.get("vat_rate", 0) for item in data["items"]]
    dominant_vat = max(set(vat_rates), key=vat_rates.count) if vat_rates else 0

    return InvoiceAnalysis(
        supplier_name=data["supplier_name"],
        invoice_number=str(data.get("invoice_number", "")),
        invoice_date=date.fromisoformat(data["invoice_date"]),
        payment_date=date.fromisoformat(data["payment_date"]),
        description=data.get("description", data["supplier_name"]),
        items=data["items"],
        total_net=Decimal(str(data["total_net"])),
        total_vat=Decimal(str(data["total_vat"])),
        total_gross=Decimal(str(data["total_gross"])),
        vat_rate=dominant_vat,
        confidence=data.get("confidence", "medium"),
        notes=data.get("notes", ""),
    )


async def create_voucher_from_invoice(
    pdf_path: Path,
    client: FortnoxClient,
    anthropic_api_key: str,
    transaction_date: date | None = None,
    customer_id: str | None = None,
    fetch_history: bool = False,
    dry_run: bool = True,
) -> tuple[InvoiceAnalysis, Voucher | None]:
    """Full flow: analyze invoice PDF → create voucher → attach PDF.

    Returns (analysis, voucher). If dry_run=True, voucher is None.
    """
    # 1. Fetch active accounts
    account_svc = AccountService(client)
    accounts_raw = await account_svc.list()
    active_accounts = [
        {"number": a.number, "description": a.description}
        for a in accounts_raw if a.active
    ]

    # 2. Optionally fetch recent voucher history for supplier context
    supplier_history = None
    if fetch_history:
        voucher_svc = VoucherService(client)
        recent = await voucher_svc.list()
        supplier_history = [
            {
                "date": str(v.transaction_date),
                "description": v.description,
                "accounts": ", ".join(
                    f"{r.account}({'D' if r.debit else 'K'} {r.debit or r.credit})"
                    for r in v.rows
                ),
                "amount": str(sum(r.debit for r in v.rows)),
            }
            for v in recent[-50:]
        ]

    # 3. Analyze invoice with Claude
    txn_year = (transaction_date or date.today()).year
    analysis = await analyze_invoice(
        pdf_path,
        active_accounts,
        anthropic_api_key,
        transaction_year=txn_year,
        customer_id=customer_id,
        supplier_history=supplier_history,
    )

    if dry_run:
        return analysis, None

    # 4. Create voucher
    voucher_svc = VoucherService(client)
    voucher = analysis.to_voucher(transaction_date)
    created = await voucher_svc.create(voucher)

    # 5. Upload PDF and attach to voucher
    inbox_svc = InboxService(client)
    file_id = await inbox_svc.upload(pdf_path)

    fc_svc = FileConnectionService(client)
    await fc_svc.connect_to_voucher(
        file_id, created.voucher_series, created.voucher_number
    )

    logger.info(
        "voucher_created_from_invoice",
        voucher=f"{created.voucher_series}{created.voucher_number}",
        supplier=analysis.supplier_name,
        total=str(analysis.total_gross),
    )

    return analysis, created
