import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from splitbill import splitter
from splitbill.cli import resolve_participant_tokens
from splitbill.ledger import Ledger
from splitbill.settlement import suggest_transfers


class TestSplitter(unittest.TestCase):
    def test_split_equal_exact(self):
        shares = splitter.split_equal(Decimal("300"), ["A", "B", "C"])
        self.assertEqual(sum(shares.values()), Decimal("300"))
        self.assertEqual(shares["A"], Decimal("100"))

    def test_split_equal_with_remainder(self):
        shares = splitter.split_equal(Decimal("100"), ["A", "B", "C"])
        self.assertEqual(sum(shares.values()), Decimal("100"))
        # 100/3 = 33.33.., 餘數應分給前幾位
        self.assertEqual(sorted(shares.values(), reverse=True)[0], Decimal("34"))

    def test_split_by_ratio(self):
        shares = splitter.split_by_ratio(Decimal("300"), {"A": Decimal("2"), "B": Decimal("1")})
        self.assertEqual(sum(shares.values()), Decimal("300"))
        self.assertEqual(shares["A"], Decimal("200"))
        self.assertEqual(shares["B"], Decimal("100"))

    def test_non_whole_amount_rejected(self):
        with self.assertRaises(ValueError):
            splitter.split_equal(Decimal("100.5"), ["A", "B", "C"])
        with self.assertRaises(ValueError):
            splitter.split_by_ratio(Decimal("100.5"), {"A": Decimal("1"), "B": Decimal("1")})
        # 100.0 其實就是整數，可以接受
        shares = splitter.split_equal(Decimal("100.0"), ["A", "B"])
        self.assertEqual(sum(shares.values()), Decimal("100"))

    def test_split_by_fixed_mismatch_raises(self):
        with self.assertRaises(ValueError):
            splitter.split_by_fixed(Decimal("300"), {"A": Decimal("100"), "B": Decimal("150")})


class TestSettlement(unittest.TestCase):
    def test_simple_two_person(self):
        transfers = suggest_transfers({"A": Decimal("50"), "B": Decimal("-50")})
        self.assertEqual(transfers, [("B", "A", Decimal("50"))])

    def test_three_person_min_transfers(self):
        # A 墊了 300 由三人均分(各100)：A淨收200, B淨付100, C淨付100
        transfers = suggest_transfers(
            {"A": Decimal("200"), "B": Decimal("-100"), "C": Decimal("-100")}
        )
        self.assertEqual(len(transfers), 2)
        total_to_a = sum(amt for f, t, amt in transfers if t == "A")
        self.assertEqual(total_to_a, Decimal("200"))

    def test_chain_reduces_to_one_transfer(self):
        # A欠B 100, B欠C 100 -> 應簡化成 A直接付C 100 (1筆而非2筆)
        transfers = suggest_transfers(
            {"A": Decimal("-100"), "B": Decimal("0"), "C": Decimal("100")}
        )
        self.assertEqual(transfers, [("A", "C", Decimal("100"))])

    def test_balance_sum_not_zero_raises(self):
        with self.assertRaises(ValueError):
            suggest_transfers({"A": Decimal("50"), "B": Decimal("-40")})

    def test_empty_when_all_settled(self):
        self.assertEqual(suggest_transfers({"A": Decimal("0"), "B": Decimal("0")}), [])


class TestLedgerEndToEnd(unittest.TestCase):
    def test_full_flow(self):
        ledger = Ledger()
        for name in ["Alice", "Bob", "Carol"]:
            ledger.add_person(name)

        # Alice 請客晚餐 300，三人均分
        ledger.add_expense_equal("Alice", Decimal("300"), ["Alice", "Bob", "Carol"], "晚餐")
        balances = ledger.calc_net_balances()
        self.assertEqual(balances["Alice"], Decimal("200"))
        self.assertEqual(balances["Bob"], Decimal("-100"))
        self.assertEqual(balances["Carol"], Decimal("-100"))

        transfers = ledger.suggest_settlement()
        self.assertEqual(len(transfers), 2)

        # Bob 轉帳給 Alice，但尚未確認前不影響餘額
        payment = ledger.record_payment("Bob", "Alice", Decimal("100"))
        balances_before_confirm = ledger.calc_net_balances()
        self.assertEqual(balances_before_confirm["Bob"], Decimal("-100"))

        ledger.confirm_payment(payment.id)
        balances_after_confirm = ledger.calc_net_balances()
        self.assertEqual(balances_after_confirm["Bob"], Decimal("0"))
        self.assertEqual(balances_after_confirm["Alice"], Decimal("100"))

    def test_unknown_person_rejected(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        with self.assertRaises(ValueError):
            ledger.add_expense_equal("Alice", Decimal("100"), ["Alice", "Ghost"])

    def test_remove_unused_person(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.remove_person("Alice")
        self.assertEqual(ledger.people, [])

    def test_remove_person_in_use_rejected(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        ledger.add_expense_equal("Alice", Decimal("100"), ["Alice", "Bob"])
        with self.assertRaises(ValueError):
            ledger.remove_person("Bob")

    def test_delete_expense_recalculates_balance(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        expense = ledger.add_expense_equal("Alice", Decimal("100"), ["Alice", "Bob"], "測試")
        ledger.delete_expense(expense.id)
        self.assertEqual(ledger.expenses, [])
        balances = ledger.calc_net_balances()
        self.assertEqual(balances["Alice"], Decimal("0"))
        self.assertEqual(balances["Bob"], Decimal("0"))

    def test_delete_confirmed_payment_restores_balance(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        # 沒有任何消費紀錄下，Bob 單純轉了 50 給 Alice
        # -> Bob 淨值變 +50（視同 Alice 欠他），Alice 淨值變 -50
        payment = ledger.record_payment("Bob", "Alice", Decimal("50"))
        ledger.confirm_payment(payment.id)
        self.assertEqual(ledger.calc_net_balances()["Bob"], Decimal("50"))
        self.assertEqual(ledger.calc_net_balances()["Alice"], Decimal("-50"))

        ledger.delete_payment(payment.id)
        balances = ledger.calc_net_balances()
        self.assertEqual(balances["Bob"], Decimal("0"))
        self.assertEqual(balances["Alice"], Decimal("0"))

    def test_delete_unknown_expense_raises(self):
        ledger = Ledger()
        with self.assertRaises(ValueError):
            ledger.delete_expense("no-such-id")

    def test_person_code_assigned_and_resolved(self):
        ledger = Ledger()
        code_a = ledger.add_person("Alice")
        code_b = ledger.add_person("Bob")
        self.assertEqual((code_a, code_b), ("1", "2"))
        self.assertEqual(ledger.resolve_person("1"), "Alice")
        self.assertEqual(ledger.resolve_person("Bob"), "Bob")
        with self.assertRaises(ValueError):
            ledger.resolve_person("99")

    def test_add_expense_by_code(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        payer = ledger.resolve_person("1")
        participants = [ledger.resolve_person(t) for t in ["1", "2"]]
        expense = ledger.add_expense_equal(payer, Decimal("100"), participants)
        self.assertEqual(expense.payer, "Alice")
        self.assertEqual(sum(expense.shares.values()), Decimal("100"))

    def test_remove_person_frees_code_mapping(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.remove_person("Alice")
        self.assertNotIn("1", ledger.person_codes)
        with self.assertRaises(ValueError):
            ledger.resolve_person("1")

    def test_roundtrip_preserves_codes(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        restored = Ledger.from_dict(ledger.to_dict())
        self.assertEqual(restored.person_codes, ledger.person_codes)
        self.assertEqual(restored.resolve_person("2"), "Bob")

    def test_load_legacy_data_without_codes_backfills_them(self):
        legacy = {"people": ["Alice", "Bob"], "expenses": [], "payments": []}
        ledger = Ledger.from_dict(legacy)
        self.assertEqual(ledger.resolve_person("1"), "Alice")
        self.assertEqual(ledger.resolve_person("2"), "Bob")

    def test_expense_and_payment_ids_are_sequential(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        e1 = ledger.add_expense_equal("Alice", Decimal("100"), ["Alice", "Bob"])
        e2 = ledger.add_expense_equal("Alice", Decimal("50"), ["Alice", "Bob"])
        self.assertEqual((e1.id, e2.id), ("1", "2"))

        p1 = ledger.record_payment("Bob", "Alice", Decimal("10"))
        p2 = ledger.record_payment("Bob", "Alice", Decimal("20"))
        self.assertEqual((p1.id, p2.id), ("1", "2"))

    def test_sequential_ids_not_reused_after_delete(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        e1 = ledger.add_expense_equal("Alice", Decimal("100"), ["Alice", "Bob"])
        ledger.delete_expense(e1.id)
        e2 = ledger.add_expense_equal("Alice", Decimal("50"), ["Alice", "Bob"])
        self.assertEqual(e2.id, "2")

    def test_roundtrip_preserves_id_counters(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        ledger.add_expense_equal("Alice", Decimal("100"), ["Alice", "Bob"])
        ledger.record_payment("Bob", "Alice", Decimal("50"))

        restored = Ledger.from_dict(ledger.to_dict())
        next_expense = restored.add_expense_equal("Alice", Decimal("60"), ["Alice", "Bob"])
        next_payment = restored.record_payment("Bob", "Alice", Decimal("30"))
        self.assertEqual(next_expense.id, "2")
        self.assertEqual(next_payment.id, "2")

    def test_reject_payment_keeps_record_but_not_counted(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        ledger.add_expense_equal("Alice", Decimal("100"), ["Alice", "Bob"])
        payment = ledger.record_payment("Bob", "Alice", Decimal("50"))
        ledger.reject_payment(payment.id)
        self.assertTrue(payment.rejected)
        self.assertEqual(ledger.pending_payments(), [])
        self.assertEqual(len(ledger.payments), 1)
        self.assertEqual(ledger.calc_net_balances()["Bob"], Decimal("-50"))

    def test_rejected_payment_cannot_be_confirmed_or_rejected_again(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        payment = ledger.record_payment("Bob", "Alice", Decimal("50"))
        ledger.reject_payment(payment.id)
        with self.assertRaises(ValueError):
            ledger.confirm_payment(payment.id)
        with self.assertRaises(ValueError):
            ledger.reject_payment(payment.id)

    def test_confirmed_payment_cannot_be_rejected(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        payment = ledger.record_payment("Bob", "Alice", Decimal("50"))
        ledger.confirm_payment(payment.id)
        with self.assertRaises(ValueError):
            ledger.reject_payment(payment.id)

    def test_rejected_flag_roundtrip_and_old_files_default_false(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        payment = ledger.record_payment("Bob", "Alice", Decimal("50"))
        ledger.reject_payment(payment.id)
        restored = Ledger.from_dict(ledger.to_dict())
        self.assertTrue(restored.payments[0].rejected)

        old = ledger.to_dict()
        del old["payments"][0]["rejected"]
        self.assertFalse(Ledger.from_dict(old).payments[0].rejected)

    def test_save_and_resolve_group(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        ledger.add_person("Carol")
        ledger.save_group("聚餐組", ["Alice", "Bob"])
        self.assertEqual(ledger.resolve_group("聚餐組"), ["Alice", "Bob"])
        with self.assertRaises(ValueError):
            ledger.resolve_group("不存在的群組")

    def test_save_group_rejects_unknown_member(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        with self.assertRaises(ValueError):
            ledger.save_group("group", ["Alice", "Ghost"])

    def test_save_group_dedupes_members(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        ledger.save_group("g", ["Alice", "Bob", "Alice"])
        self.assertEqual(ledger.resolve_group("g"), ["Alice", "Bob"])

    def test_delete_group(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.save_group("g", ["Alice"])
        ledger.delete_group("g")
        with self.assertRaises(ValueError):
            ledger.resolve_group("g")

    def test_remove_person_shrinks_group_and_drops_if_empty(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        ledger.save_group("g1", ["Alice", "Bob"])
        ledger.save_group("g2", ["Bob"])
        ledger.remove_person("Bob")
        self.assertEqual(ledger.resolve_group("g1"), ["Alice"])
        with self.assertRaises(ValueError):
            ledger.resolve_group("g2")  # Bob 是唯一成員，被移除後群組整個消失

    def test_group_roundtrip(self):
        ledger = Ledger()
        ledger.add_person("Alice")
        ledger.add_person("Bob")
        ledger.save_group("g", ["Alice", "Bob"])
        restored = Ledger.from_dict(ledger.to_dict())
        self.assertEqual(restored.resolve_group("g"), ["Alice", "Bob"])


class TestResolveParticipantTokens(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()
        self.ledger.add_person("Alice")
        self.ledger.add_person("Bob")
        self.ledger.add_person("Carol")
        self.ledger.save_group("聚餐組", ["Alice", "Bob"])

    def test_empty_input_means_all(self):
        self.assertEqual(
            resolve_participant_tokens(self.ledger, ""), ["Alice", "Bob", "Carol"]
        )

    def test_all_keyword(self):
        self.assertEqual(
            resolve_participant_tokens(self.ledger, "all"), ["Alice", "Bob", "Carol"]
        )
        self.assertEqual(
            resolve_participant_tokens(self.ledger, "全部"), ["Alice", "Bob", "Carol"]
        )

    def test_codes_csv(self):
        self.assertEqual(resolve_participant_tokens(self.ledger, "1,2"), ["Alice", "Bob"])

    def test_group_token(self):
        self.assertEqual(
            resolve_participant_tokens(self.ledger, "@聚餐組"), ["Alice", "Bob"]
        )

    def test_group_mixed_with_individual_dedupes(self):
        self.assertEqual(
            resolve_participant_tokens(self.ledger, "@聚餐組,3,1"), ["Alice", "Bob", "Carol"]
        )

    def test_unknown_group_raises(self):
        with self.assertRaises(ValueError):
            resolve_participant_tokens(self.ledger, "@不存在")


if __name__ == "__main__":
    unittest.main()
