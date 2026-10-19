import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from splitbill import splitter, web
from splitbill.expression import eval_amount, has_operator
from splitbill.ledger import Ledger


class TestEvalAmount(unittest.TestCase):
    def test_plain_numbers(self):
        self.assertEqual(eval_amount("300"), Decimal("300"))
        self.assertEqual(eval_amount("  12.5 "), Decimal("12.5"))

    def test_sum(self):
        self.assertEqual(eval_amount("42+48+52"), Decimal("142"))
        self.assertEqual(eval_amount("42 + 48 + 52"), Decimal("142"))
        self.assertEqual(eval_amount("42＋48"), Decimal("90"))  # 全形加號

    def test_multiplication_binds_tighter_than_addition(self):
        self.assertEqual(eval_amount("42*2+48"), Decimal("132"))
        self.assertEqual(eval_amount("42x2+48"), Decimal("132"))
        self.assertEqual(eval_amount("42×2+3*3"), Decimal("93"))

    def test_decimals_stay_exact(self):
        self.assertEqual(eval_amount("0.1+0.2"), Decimal("0.3"))

    def test_rejects_garbage(self):
        for bad in ["", "   ", "abc", "42+", "+42", "42++48", "*5", "5*", "-5", "4-2", "1e3",
                    "NaN", "Infinity", "(1+2)", "42/2", "__import__('os')", "1,000", "4 2"]:
            with self.assertRaises(ValueError, msg=bad):
                eval_amount(bad)

    def test_rejects_too_large_or_too_long(self):
        with self.assertRaises(ValueError):
            eval_amount("999999999999+1")
        with self.assertRaises(ValueError):
            eval_amount("1+" * 60 + "1")

    def test_has_operator(self):
        self.assertTrue(has_operator("42+48"))
        self.assertTrue(has_operator("42x2"))
        self.assertFalse(has_operator("42"))


class TestExpressionsInExpenseForm(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()
        for n in ["A", "B", "C"]:
            self.ledger.add_person(n)

    def test_ratio_weights_can_be_sums(self):
        # 甜甜圈三種價位 42/48/52：A 買 42+48、B 買 52*2、C 買 42；實付 300
        body = {
            "payer": "A", "amount": "300", "participants": ["A", "B", "C"], "method": "ratio",
            "values": {"A": "42+48", "B": "52*2", "C": "42"},
        }
        shares = web.api_expense_preview(self.ledger, body)["shares"]
        expected = splitter.split_by_ratio(
            Decimal("300"), {"A": Decimal("90"), "B": Decimal("104"), "C": Decimal("42")}
        )
        self.assertEqual(shares, {k: str(v) for k, v in expected.items()})
        self.assertEqual(sum(Decimal(v) for v in shares.values()), Decimal("300"))

    def test_fixed_amounts_and_total_can_be_sums(self):
        body = {
            "payer": "A", "amount": "100+50+150", "participants": ["A", "B"], "method": "fixed",
            "values": {"A": "100+100", "B": "50+50"},
        }
        shares = web.api_expense_preview(self.ledger, body)["shares"]
        self.assertEqual(shares, {"A": "200", "B": "100"})

    def test_bad_expression_error_names_the_field(self):
        body = {
            "payer": "A", "amount": "300", "participants": ["A", "B"], "method": "ratio",
            "values": {"A": "1+", "B": "1"},
        }
        with self.assertRaises(ValueError) as ctx:
            web.api_expense_preview(self.ledger, body)
        self.assertIn("「A」的權重", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
