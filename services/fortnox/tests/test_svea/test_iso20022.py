"""Tests for ISO 20022 pain.001 XML generation."""

from datetime import date
from decimal import Decimal
from xml.etree.ElementTree import fromstring

import pytest

from fortnox.svea.api.models import SveaPaymentOrder
from fortnox.svea.payments.iso20022 import NS, generate_pain001


def _parse(xml_bytes: bytes):
    """Parse XML and return root with namespace-aware tag helper."""
    root = fromstring(xml_bytes)
    return root


def _find(element, path):
    """Find element using namespace-aware path."""
    ns_path = "/".join(f"{{{NS}}}{tag}" for tag in path.split("/"))
    return element.find(ns_path)


def _findtext(element, path):
    """Find element text using namespace-aware path."""
    el = _find(element, path)
    return el.text if el is not None else None


class TestGeneratePain001:
    def _make_payment(self, **kwargs):
        defaults = {
            "recipient_name": "Leverantör AB",
            "recipient_account": "123-4567",
            "account_type": "bankgiro",
            "amount": Decimal("15000.00"),
            "currency": "SEK",
            "reference": "OCR123456",
        }
        defaults.update(kwargs)
        return SveaPaymentOrder(**defaults)

    def test_basic_generation(self):
        """Generate valid XML with one payment."""
        payment = self._make_payment()
        xml = generate_pain001(
            payments=[payment],
            debtor_name="Min Firma AB",
            debtor_account="9960-1234567",
            batch_id="TEST-001",
            execution_date=date(2026, 4, 1),
        )
        assert xml.startswith(b"<?xml")
        root = _parse(xml)
        assert root.tag == f"{{{NS}}}Document"

    def test_group_header(self):
        """Group header has correct fields."""
        payments = [self._make_payment(), self._make_payment(amount=Decimal("5000"))]
        xml = generate_pain001(
            payments=payments,
            debtor_name="Test AB",
            debtor_account="9960-123",
            batch_id="BATCH-001",
        )
        root = _parse(xml)

        msg_id = _findtext(root, "CstmrCdtTrfInitn/GrpHdr/MsgId")
        assert msg_id == "BATCH-001"

        nb_txs = _findtext(root, "CstmrCdtTrfInitn/GrpHdr/NbOfTxs")
        assert nb_txs == "2"

        ctrl_sum = _findtext(root, "CstmrCdtTrfInitn/GrpHdr/CtrlSum")
        assert ctrl_sum == "20000.00"

        nm = _findtext(root, "CstmrCdtTrfInitn/GrpHdr/InitgPty/Nm")
        assert nm == "Test AB"

    def test_payment_info(self):
        """Payment information block has correct debtor details."""
        xml = generate_pain001(
            payments=[self._make_payment()],
            debtor_name="Firma AB",
            debtor_account="9960-1234567",
            debtor_bic="SWEDSESS",
            execution_date=date(2026, 5, 15),
        )
        root = _parse(xml)

        pmt_mtd = _findtext(root, "CstmrCdtTrfInitn/PmtInf/PmtMtd")
        assert pmt_mtd == "TRF"

        exec_dt = _findtext(root, "CstmrCdtTrfInitn/PmtInf/ReqdExctnDt")
        assert exec_dt == "2026-05-15"

        dbtr_nm = _findtext(root, "CstmrCdtTrfInitn/PmtInf/Dbtr/Nm")
        assert dbtr_nm == "Firma AB"

    def test_bankgiro_payment(self):
        """Bankgiro payment has BGNR scheme."""
        payment = self._make_payment(
            account_type="bankgiro",
            recipient_account="123-4567",
        )
        xml = generate_pain001(
            payments=[payment],
            debtor_name="Test",
            debtor_account="9960-123",
        )
        root = _parse(xml)

        # Find the creditor account scheme
        txn_path = "CstmrCdtTrfInitn/PmtInf/CdtTrfTxInf"
        txn = _find(root, txn_path)
        assert txn is not None

        prtry = _findtext(txn, "CdtrAcct/Id/Othr/SchmeNm/Prtry")
        assert prtry == "BGNR"

        acct_id = _findtext(txn, "CdtrAcct/Id/Othr/Id")
        assert acct_id == "1234567"  # Stripped of dash

    def test_plusgiro_payment(self):
        """Plusgiro payment has PGNR scheme."""
        payment = self._make_payment(
            account_type="plusgiro",
            recipient_account="12345-6",
        )
        xml = generate_pain001(
            payments=[payment],
            debtor_name="Test",
            debtor_account="9960-123",
        )
        root = _parse(xml)

        txn = _find(root, "CstmrCdtTrfInitn/PmtInf/CdtTrfTxInf")
        prtry = _findtext(txn, "CdtrAcct/Id/Othr/SchmeNm/Prtry")
        assert prtry == "PGNR"

    def test_domestic_payment(self):
        """Domestic bank transfer has no scheme (plain BBAN)."""
        payment = self._make_payment(
            account_type="domestic",
            recipient_account="6789-1234567",
        )
        xml = generate_pain001(
            payments=[payment],
            debtor_name="Test",
            debtor_account="9960-123",
        )
        root = _parse(xml)

        txn = _find(root, "CstmrCdtTrfInitn/PmtInf/CdtTrfTxInf")
        # Domestic should have Othr/Id but no SchmeNm
        acct_id = _findtext(txn, "CdtrAcct/Id/Othr/Id")
        assert acct_id == "67891234567"

        schme = _find(txn, "CdtrAcct/Id/Othr/SchmeNm")
        assert schme is None

    def test_ocr_reference(self):
        """Structured reference (OCR) is included."""
        payment = self._make_payment(reference="12345678901234")
        xml = generate_pain001(
            payments=[payment],
            debtor_name="Test",
            debtor_account="9960-123",
        )
        root = _parse(xml)

        txn = _find(root, "CstmrCdtTrfInitn/PmtInf/CdtTrfTxInf")
        ref = _findtext(txn, "RmtInf/Strd/CdtrRefInf/Ref")
        assert ref == "12345678901234"

    def test_free_text_message(self):
        """Unstructured message is included when no reference."""
        payment = self._make_payment(reference="", message="Invoice 2026-001")
        xml = generate_pain001(
            payments=[payment],
            debtor_name="Test",
            debtor_account="9960-123",
        )
        root = _parse(xml)

        txn = _find(root, "CstmrCdtTrfInitn/PmtInf/CdtTrfTxInf")
        ustrd = _findtext(txn, "RmtInf/Ustrd")
        assert ustrd == "Invoice 2026-001"

    def test_amount_formatting(self):
        """Amounts are formatted with 2 decimal places."""
        payment = self._make_payment(amount=Decimal("1234.50"))
        xml = generate_pain001(
            payments=[payment],
            debtor_name="Test",
            debtor_account="9960-123",
        )
        root = _parse(xml)

        txn = _find(root, "CstmrCdtTrfInitn/PmtInf/CdtTrfTxInf")
        amt = _find(txn, "Amt/InstdAmt")
        assert amt is not None
        assert amt.text == "1234.50"
        assert amt.get("Ccy") == "SEK"

    def test_multiple_payments(self):
        """Multiple payments produce multiple CdtTrfTxInf blocks."""
        payments = [
            self._make_payment(amount=Decimal("1000"), recipient_name="A"),
            self._make_payment(amount=Decimal("2000"), recipient_name="B"),
            self._make_payment(amount=Decimal("3000"), recipient_name="C"),
        ]
        xml = generate_pain001(
            payments=payments,
            debtor_name="Test",
            debtor_account="9960-123",
            batch_id="MULTI-001",
        )
        root = _parse(xml)

        pmt_inf = _find(root, "CstmrCdtTrfInitn/PmtInf")
        txns = pmt_inf.findall(f"{{{NS}}}CdtTrfTxInf")
        assert len(txns) == 3

    def test_empty_payments_raises(self):
        """Empty payment list raises ValueError."""
        with pytest.raises(ValueError, match="At least one payment"):
            generate_pain001(
                payments=[],
                debtor_name="Test",
                debtor_account="9960-123",
            )

    def test_auto_generated_batch_id(self):
        """Batch ID is auto-generated when not provided."""
        payment = self._make_payment()
        xml = generate_pain001(
            payments=[payment],
            debtor_name="Test",
            debtor_account="9960-123",
        )
        root = _parse(xml)
        msg_id = _findtext(root, "CstmrCdtTrfInitn/GrpHdr/MsgId")
        assert msg_id.startswith("NOCFO-")

    def test_end_to_end_ids_sequential(self):
        """Each transaction gets a sequential EndToEndId."""
        payments = [self._make_payment() for _ in range(3)]
        xml = generate_pain001(
            payments=payments,
            debtor_name="Test",
            debtor_account="9960-123",
            batch_id="SEQ-001",
        )
        root = _parse(xml)

        pmt_inf = _find(root, "CstmrCdtTrfInitn/PmtInf")
        txns = pmt_inf.findall(f"{{{NS}}}CdtTrfTxInf")
        e2e_ids = [_findtext(t, "PmtId/EndToEndId") for t in txns]
        assert e2e_ids == ["SEQ-001-0001", "SEQ-001-0002", "SEQ-001-0003"]
