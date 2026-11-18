"""Reproducible multi-module receipt import fixture; no provider calls."""

from pathlib import Path

PROMPT = '''Fix the receipt importer end to end. It should trim receipt IDs before deduplication, count invalid records as rejected without writing them, and use decimal half-up rounding to cents. Keep the import report consistent with the stored receipts, preserve existing valid behavior, and run the tests before reporting. Scope: this repository only.'''

FILES = {
    'README.md': '''# Receipt import

A batch import job for the accounting service. Public entry point:
`receipt_import.service.import_batch`. Run `python3 -m unittest discover -s tests -v`.
The `reporting`, `exports`, and `examples` packages have adjacent but separate responsibilities.
''',
    'pyproject.toml': '[project]\nname = "receipt-import"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n',
    'receipt_import/__init__.py': '',
    'receipt_import/normalize.py': '''from dataclasses import dataclass

from .money import cents


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    amount_cents: int


def normalize(record):
    receipt_id = record.get("id", "")
    if not isinstance(receipt_id, str) or not receipt_id:
        raise ValueError("A receipt ID is required")
    return Receipt(receipt_id, cents(record.get("amount")))
''',
    'receipt_import/money.py': '''from decimal import Decimal, InvalidOperation


def cents(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError("An amount must be finite and non-negative")
        return int(amount * 100)
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc
''',
    'receipt_import/repository.py': '''class Repository:
    def __init__(self):
        self.receipts = {}

    def add(self, receipt):
        if receipt.receipt_id in self.receipts:
            return False
        self.receipts[receipt.receipt_id] = receipt.amount_cents
        return True
''',
    'receipt_import/service.py': '''from .normalize import normalize
from .report import ImportReport


def import_batch(records, repository):
    report = ImportReport()
    for record in records:
        try:
            receipt = normalize(record)
        except ValueError:
            continue
        if repository.add(receipt):
            report.accepted += 1
            report.amount_cents += receipt.amount_cents
        else:
            report.duplicates += 1
    return report
''',
    'receipt_import/report.py': '''from dataclasses import dataclass


@dataclass
class ImportReport:
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    amount_cents: int = 0
''',
    'reporting/receipt_totals.py': '''def sum_receipts(report_lines):
    return sum(line.amount_cents for line in report_lines)
''',
    'exports/receipt_csv.py': '''import csv


def write_receipts(file, receipts):
    writer = csv.writer(file)
    writer.writerow(["receipt_id", "amount_cents"])
    writer.writerows(receipts.items())
''',
    'examples/import_receipts.py': '''from receipt_import.repository import Repository
from receipt_import.service import import_batch


def example():
    return import_batch([{"id": "R-1", "amount": "1.00"}], Repository())
''',
}

TESTS = '''import unittest

from receipt_import.repository import Repository
from receipt_import.service import import_batch


class ReceiptImportTests(unittest.TestCase):
    def setUp(self):
        self.repository = Repository()

    def test_trims_ids_before_deduplication(self):
        result = import_batch([{"id": " r1 ", "amount": "2"},
                               {"id": "r1", "amount": "4"}], self.repository)
        self.assertEqual(self.repository.receipts, {"r1": 200})
        self.assertEqual((result.accepted, result.duplicates), (1, 1))

    def test_rejects_invalid_without_writing(self):
        records = [{"id": " ", "amount": "1.00"}, {"id": "X", "amount": "NaN"},
                   {"id": None, "amount": "1"}, {"id": "Y", "amount": "-1"}]
        result = import_batch(records, self.repository)
        self.assertEqual(result.rejected, len(records))
        self.assertEqual(self.repository.receipts, {})

    def test_rounds_to_cents_half_up(self):
        result = import_batch([{"id": "a", "amount": "1.005"},
                               {"id": "b", "amount": "1.004"}], self.repository)
        self.assertEqual(self.repository.receipts, {"a": 101, "b": 100})
        self.assertEqual(result.amount_cents, 201)

    def test_preserves_valid_records(self):
        result = import_batch([{"id": "a", "amount": "1.23"},
                               {"id": "b", "amount": "2.45"}], self.repository)
        self.assertEqual((result.accepted, result.rejected, result.amount_cents), (2, 0, 368))
'''


def materialize(root: Path) -> None:
    for name, text in {**FILES, 'tests/test_import_batch.py': TESTS}.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
