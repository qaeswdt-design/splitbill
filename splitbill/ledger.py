"""Ledger：整合朋友名單、消費紀錄、轉帳紀錄與餘額計算的主要狀態容器。"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from . import splitter
from .models import Expense, Payment
from .settlement import Transfer, suggest_transfers


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Ledger:
    def __init__(self):
        self.people: List[str] = []
        self.person_codes: Dict[str, str] = {}  # 代號 -> 全名，例如 {"1": "Alice"}
        self._next_code: int = 1
        self.expenses: List[Expense] = []
        self._next_expense_no: int = 1  # 消費紀錄編號（1, 2, 3…），跟朋友代號同一套邏輯
        self.payments: List[Payment] = []
        self._next_payment_no: int = 1  # 轉帳紀錄編號（1, 2, 3…）
        self.groups: Dict[str, List[str]] = {}  # 常用群組名稱 -> 成員全名清單

    # ---------- 朋友名單 ----------

    def add_person(self, name: str) -> str:
        """新增朋友，回傳自動配發的代號（數字字串），供後續輸入時取代全名使用。"""
        name = name.strip()
        if not name:
            raise ValueError("姓名不可為空")
        if name in self.people:
            raise ValueError(f"「{name}」已存在")
        code = str(self._next_code)
        self._next_code += 1
        self.people.append(name)
        self.person_codes[code] = name
        return code

    def remove_person(self, name: str) -> None:
        if name not in self.people:
            raise ValueError(f"「{name}」不在朋友名單中")
        used_in_expense = any(name == e.payer or name in e.shares for e in self.expenses)
        used_in_payment = any(name == p.payer or name == p.payee for p in self.payments)
        if used_in_expense or used_in_payment:
            raise ValueError(f"「{name}」已有消費或轉帳紀錄，刪除會導致帳目不一致，故不允許刪除")
        self.people.remove(name)
        code = self.code_of(name)
        if code is not None:
            del self.person_codes[code]
        for group_name in list(self.groups.keys()):
            if name in self.groups[group_name]:
                self.groups[group_name].remove(name)
                if not self.groups[group_name]:
                    del self.groups[group_name]

    def code_of(self, name: str) -> Optional[str]:
        for code, n in self.person_codes.items():
            if n == name:
                return code
        return None

    def resolve_person(self, token: str) -> str:
        """把使用者輸入的代號或全名，解析成朋友的全名。"""
        token = token.strip()
        if token in self.person_codes:
            return self.person_codes[token]
        if token in self.people:
            return token
        raise ValueError(f"找不到朋友「{token}」（可輸入代號或全名）")

    # ---------- 常用群組 ----------

    def save_group(self, group_name: str, member_names: List[str]) -> None:
        """新增或覆蓋一個常用群組（例如「假日聚餐組」= 固定幾位朋友）。"""
        group_name = group_name.strip()
        if not group_name:
            raise ValueError("群組名稱不可為空")
        if not member_names:
            raise ValueError("群組成員不可為空")
        self._validate_names(member_names)
        deduped: List[str] = []
        for name in member_names:
            if name not in deduped:
                deduped.append(name)
        self.groups[group_name] = deduped

    def delete_group(self, group_name: str) -> None:
        if group_name not in self.groups:
            raise ValueError(f"找不到群組「{group_name}」")
        del self.groups[group_name]

    def resolve_group(self, group_name: str) -> List[str]:
        if group_name not in self.groups:
            raise ValueError(f"找不到群組「{group_name}」")
        return list(self.groups[group_name])

    # ---------- 消費 / 拆帳 ----------

    def add_expense_equal(
        self, payer: str, amount: Decimal, participants: List[str], description: str = ""
    ) -> Expense:
        self._validate_names([payer, *participants])
        shares = splitter.split_equal(amount, participants)
        return self._record_expense(payer, amount, participants, shares, description)

    def add_expense_by_ratio(
        self,
        payer: str,
        amount: Decimal,
        weights: Dict[str, Decimal],
        description: str = "",
    ) -> Expense:
        self._validate_names([payer, *weights.keys()])
        shares = splitter.split_by_ratio(amount, weights)
        return self._record_expense(payer, amount, list(weights.keys()), shares, description)

    def add_expense_fixed(
        self,
        payer: str,
        amount: Decimal,
        fixed: Dict[str, Decimal],
        description: str = "",
    ) -> Expense:
        self._validate_names([payer, *fixed.keys()])
        shares = splitter.split_by_fixed(amount, fixed)
        return self._record_expense(payer, amount, list(fixed.keys()), shares, description)

    def _record_expense(self, payer, amount, participants, shares, description) -> Expense:
        expense = Expense(
            id=str(self._next_expense_no),
            description=description or "(未命名消費)",
            payer=payer,
            amount=amount,
            participants=participants,
            shares=shares,
            timestamp=_now(),
        )
        self._next_expense_no += 1
        self.expenses.append(expense)
        return expense

    def delete_expense(self, expense_id: str) -> Expense:
        for i, e in enumerate(self.expenses):
            if e.id == expense_id:
                return self.expenses.pop(i)
        raise ValueError(f"找不到消費紀錄 {expense_id}")

    # ---------- 轉帳（手動輸入 + 收款方確認） ----------

    def record_payment(self, payer: str, payee: str, amount: Decimal, note: str = "") -> Payment:
        self._validate_names([payer, payee])
        if amount <= 0:
            raise ValueError("轉帳金額必須大於 0")
        payment = Payment(
            id=str(self._next_payment_no),
            payer=payer,
            payee=payee,
            amount=amount,
            timestamp=_now(),
            note=note,
        )
        self._next_payment_no += 1
        self.payments.append(payment)
        return payment

    def confirm_payment(self, payment_id: str) -> Payment:
        payment = self._find_payment(payment_id)
        if payment.confirmed:
            raise ValueError("這筆轉帳已經確認過了")
        if payment.rejected:
            raise ValueError("這筆轉帳已被標記為沒收到，請重新記錄一筆")
        payment.confirmed = True
        payment.confirmed_at = _now()
        return payment

    def reject_payment(self, payment_id: str) -> Payment:
        """收款方表示沒收到款項：保留紀錄但不計入餘額，也不再出現在待確認清單。"""
        payment = self._find_payment(payment_id)
        if payment.confirmed:
            raise ValueError("這筆轉帳已經確認收款，無法改成沒收到（如需更正請刪除該筆紀錄）")
        if payment.rejected:
            raise ValueError("這筆轉帳已經標記為沒收到了")
        payment.rejected = True
        return payment

    def delete_payment(self, payment_id: str) -> Payment:
        for i, p in enumerate(self.payments):
            if p.id == payment_id:
                return self.payments.pop(i)
        raise ValueError(f"找不到轉帳紀錄 {payment_id}")

    def _find_payment(self, payment_id: str) -> Payment:
        for p in self.payments:
            if p.id == payment_id:
                return p
        raise ValueError(f"找不到轉帳紀錄 {payment_id}")

    # ---------- 餘額 / 結算建議 ----------

    def calc_net_balances(self) -> Dict[str, Decimal]:
        """正值 = 應收（別人欠他）；負值 = 應付（他欠別人）。"""
        balances: Dict[str, Decimal] = {name: Decimal("0") for name in self.people}

        for expense in self.expenses:
            balances[expense.payer] = balances.get(expense.payer, Decimal("0")) + expense.amount
            for person, share in expense.shares.items():
                balances[person] = balances.get(person, Decimal("0")) - share

        for payment in self.payments:
            if not payment.confirmed:
                continue
            balances[payment.payer] = balances.get(payment.payer, Decimal("0")) + payment.amount
            balances[payment.payee] = balances.get(payment.payee, Decimal("0")) - payment.amount

        return balances

    def suggest_settlement(self) -> List[Transfer]:
        return suggest_transfers(self.calc_net_balances())

    def pending_payments(self) -> List[Payment]:
        return [p for p in self.payments if not p.confirmed and not p.rejected]

    # ---------- 工具 ----------

    def _validate_names(self, names: List[str]) -> None:
        for name in names:
            if name not in self.people:
                raise ValueError(f"「{name}」不在朋友名單中，請先新增")

    # ---------- 序列化 ----------

    def to_dict(self) -> dict:
        return {
            "people": list(self.people),
            "person_codes": dict(self.person_codes),
            "next_code": self._next_code,
            "expenses": [e.to_dict() for e in self.expenses],
            "next_expense_no": self._next_expense_no,
            "payments": [p.to_dict() for p in self.payments],
            "next_payment_no": self._next_payment_no,
            "groups": {name: list(members) for name, members in self.groups.items()},
        }

    @staticmethod
    def from_dict(data: dict) -> "Ledger":
        ledger = Ledger()
        ledger.people = list(data.get("people", []))
        codes = data.get("person_codes")
        if codes:
            ledger.person_codes = dict(codes)
            ledger._next_code = data.get("next_code", max((int(c) for c in codes), default=0) + 1)
        else:
            # 相容舊版無代號資訊的存檔：依現有順序自動配發代號
            ledger.person_codes = {str(i + 1): name for i, name in enumerate(ledger.people)}
            ledger._next_code = len(ledger.people) + 1

        ledger.expenses = [Expense.from_dict(e) for e in data.get("expenses", [])]
        ledger._next_expense_no = data.get("next_expense_no", len(ledger.expenses) + 1)

        ledger.payments = [Payment.from_dict(p) for p in data.get("payments", [])]
        ledger._next_payment_no = data.get("next_payment_no", len(ledger.payments) + 1)

        ledger.groups = {
            name: list(members) for name, members in data.get("groups", {}).items()
        }

        return ledger
