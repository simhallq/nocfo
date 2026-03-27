"""ISO 20022 pain.001 (CustomerCreditTransferInitiation) XML generator.

Generates payment instruction files compliant with the Swedish ISO 20022
standard for credit transfers, replacing the legacy Bankgirot LB format
(sunset July 1, 2026).

Supports:
- Bankgiro payments (Swedish bankgiro number)
- Plusgiro payments (Swedish plusgiro number)
- Domestic bank transfers (clearing + account number)

Reference: Bankgirot ISO 20022 implementation guidelines for Sweden.
"""

import secrets
from datetime import date, datetime
from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, tostring

from fortnox.svea.api.models import SveaPaymentOrder

# ISO 20022 namespace
NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"


def generate_pain001(
    payments: list[SveaPaymentOrder],
    debtor_name: str,
    debtor_account: str,
    debtor_bic: str = "SWEDSESS",
    batch_id: str | None = None,
    execution_date: date | None = None,
) -> bytes:
    """Generate an ISO 20022 pain.001.001.03 XML document.

    Args:
        payments: List of payment orders to include.
        debtor_name: Name of the paying company.
        debtor_account: Debtor's clearing + account number (BBAN).
        debtor_bic: BIC of debtor's bank (default: Svea Bank).
        batch_id: Unique batch identifier (auto-generated if omitted).
        execution_date: Requested execution date (default: today).

    Returns:
        UTF-8 encoded XML bytes with XML declaration.
    """
    if not payments:
        raise ValueError("At least one payment is required")

    if batch_id is None:
        batch_id = f"NOCFO-{secrets.token_hex(8).upper()}"
    if execution_date is None:
        execution_date = date.today()

    total_amount = sum(p.amount for p in payments)
    creation_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    doc = Element("Document", xmlns=NS)
    cstmr = SubElement(doc, "CstmrCdtTrfInitn")

    grp_hdr = SubElement(cstmr, "GrpHdr")
    SubElement(grp_hdr, "MsgId").text = batch_id
    SubElement(grp_hdr, "CreDtTm").text = creation_time
    SubElement(grp_hdr, "NbOfTxs").text = str(len(payments))
    SubElement(grp_hdr, "CtrlSum").text = _fmt_amount(total_amount)
    initg_pty = SubElement(grp_hdr, "InitgPty")
    SubElement(initg_pty, "Nm").text = debtor_name

    pmt_inf = SubElement(cstmr, "PmtInf")
    SubElement(pmt_inf, "PmtInfId").text = f"{batch_id}-001"
    SubElement(pmt_inf, "PmtMtd").text = "TRF"
    SubElement(pmt_inf, "NbOfTxs").text = str(len(payments))
    SubElement(pmt_inf, "CtrlSum").text = _fmt_amount(total_amount)

    pmt_tp_inf = SubElement(pmt_inf, "PmtTpInf")
    svc_lvl = SubElement(pmt_tp_inf, "SvcLvl")
    SubElement(svc_lvl, "Cd").text = "NURG"

    SubElement(pmt_inf, "ReqdExctnDt").text = execution_date.isoformat()

    dbtr = SubElement(pmt_inf, "Dbtr")
    SubElement(dbtr, "Nm").text = debtor_name

    dbtr_acct = SubElement(pmt_inf, "DbtrAcct")
    dbtr_id = SubElement(dbtr_acct, "Id")
    SubElement(dbtr_id, "Othr").text = debtor_account
    SubElement(dbtr_acct, "Ccy").text = "SEK"

    dbtr_agt = SubElement(pmt_inf, "DbtrAgt")
    fin_instn_id = SubElement(dbtr_agt, "FinInstnId")
    SubElement(fin_instn_id, "BIC").text = debtor_bic

    for i, payment in enumerate(payments, 1):
        _add_transaction(pmt_inf, payment, batch_id, i)

    # Serialize to XML bytes
    xml_bytes = tostring(doc, encoding="utf-8", xml_declaration=True)
    return xml_bytes


def _add_transaction(
    pmt_inf: Element,
    payment: SveaPaymentOrder,
    batch_id: str,
    seq: int,
) -> None:
    """Add a single credit transfer transaction to the payment information block."""
    cdtt = SubElement(pmt_inf, "CdtTrfTxInf")

    pmt_id = SubElement(cdtt, "PmtId")
    SubElement(pmt_id, "EndToEndId").text = f"{batch_id}-{seq:04d}"

    amt = SubElement(cdtt, "Amt")
    instd_amt = SubElement(amt, "InstdAmt", Ccy=payment.currency)
    instd_amt.text = _fmt_amount(payment.amount)

    cdtr = SubElement(cdtt, "Cdtr")
    SubElement(cdtr, "Nm").text = payment.recipient_name[:70]

    cdtr_acct = SubElement(cdtt, "CdtrAcct")
    cdtr_id = SubElement(cdtr_acct, "Id")

    acct_num = payment.recipient_account.replace("-", "")
    if payment.account_type == "bankgiro":
        othr = SubElement(cdtr_id, "Othr")
        SubElement(othr, "Id").text = acct_num
        schme = SubElement(othr, "SchmeNm")
        SubElement(schme, "Prtry").text = "BGNR"
    elif payment.account_type == "plusgiro":
        othr = SubElement(cdtr_id, "Othr")
        SubElement(othr, "Id").text = acct_num
        schme = SubElement(othr, "SchmeNm")
        SubElement(schme, "Prtry").text = "PGNR"
    else:
        othr = SubElement(cdtr_id, "Othr")
        SubElement(othr, "Id").text = acct_num
    if payment.reference or payment.message:
        rmt_inf = SubElement(cdtt, "RmtInf")
        if payment.reference:
            # Structured reference (OCR)
            strd = SubElement(rmt_inf, "Strd")
            cdtr_ref_inf = SubElement(strd, "CdtrRefInf")
            SubElement(cdtr_ref_inf, "Ref").text = payment.reference
        elif payment.message:
            # Unstructured message
            SubElement(rmt_inf, "Ustrd").text = payment.message[:140]


def _fmt_amount(amount: Decimal) -> str:
    """Format amount with 2 decimal places."""
    return f"{abs(amount):.2f}"
