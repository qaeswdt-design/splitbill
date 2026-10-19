"""資料模型：消費紀錄（Expense）與轉帳紀錄（Payment）。"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List


@dataclass
class Expense:
    """一筆聚會消費，以及每個參與者應分攤的金額。"""

    id: str
    description: str
    payer: str
    amount: Decimal
    participants: List[str]
    shares: Dict[str, Decimal]  # 參與者 -> 應分攤金額，總和須等於 amount
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "payer": self.payer,
            "amount": str(self.amount),
            "participants": list(self.participants),
            "shares": {k: str(v) for k, v in self.shares.items()},
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(data: dict) -> "Expense":
        return Expense(
            id=data["id"],
            description=data["description"],
            payer=data["payer"],
            amount=Decimal(data["amount"]),
            participants=list(data["participants"]),
            shares={k: Decimal(v) for k, v in data["shares"].items()},
            timestamp=data["timestamp"],
        )


@dataclass
class Payment:
    """一筆使用者手動輸入的轉帳紀錄，需收款方確認才會計入餘額。"""

    id: str
    payer: str  # 轉出方
    payee: str  # 收款方
    amount: Decimal
    timestamp: str
    confirmed: bool = False
    confirmed_at: str = ""
    note: str = ""
    rejected: bool = False  # 收款方表示「沒收到」：保留紀錄，但不計入餘額

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "payer": self.payer,
            "payee": self.payee,
            "amount": str(self.amount),
            "timestamp": self.timestamp,
            "confirmed": self.confirmed,
            "confirmed_at": self.confirmed_at,
            "note": self.note,
            "rejected": self.rejected,
        }

    @staticmethod
    def from_dict(data: dict) -> "Payment":
        return Payment(
            id=data["id"],
            payer=data["payer"],
            payee=data["payee"],
            amount=Decimal(data["amount"]),
            timestamp=data["timestamp"],
            confirmed=data.get("confirmed", False),
            confirmed_at=data.get("confirmed_at", ""),
            note=data.get("note", ""),
            rejected=data.get("rejected", False),
        )
