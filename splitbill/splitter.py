"""拆帳計算邏輯：平均分攤、依比例分攤、自訂金額分攤。

全部使用 Decimal 運算以避免浮點數誤差，並確保每筆分攤總和
「精確等於」原始消費金額（零頭會依序分給前幾位參與者）。
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List

# 貨幣最小單位（新台幣通常無小數，如需支援分則改為 Decimal("0.01")）
CURRENCY_UNIT = Decimal("1")


def _quantize(amount: Decimal) -> Decimal:
    return amount.quantize(CURRENCY_UNIT, rounding=ROUND_HALF_UP)


def _require_whole(amount: Decimal) -> None:
    """金額必須是整數：有小數時零頭無法分配，分攤總和會對不上原金額。"""
    if amount != amount.to_integral_value():
        raise ValueError("金額必須是整數")


def split_equal(amount: Decimal, participants: List[str]) -> Dict[str, Decimal]:
    """將 amount 平均分給 participants，餘數依序分給前幾位以確保總和不失真。"""
    if not participants:
        raise ValueError("參與者名單不可為空")
    _require_whole(amount)
    n = len(participants)
    base = _quantize(amount / n)
    shares = {p: base for p in participants}

    remainder = amount - base * n
    step = CURRENCY_UNIT if remainder > 0 else -CURRENCY_UNIT
    count = int(abs(remainder) / CURRENCY_UNIT)
    for i in range(count):
        shares[participants[i % n]] += step

    return shares


def split_by_ratio(amount: Decimal, weights: Dict[str, Decimal]) -> Dict[str, Decimal]:
    """依權重比例分攤（例如 {"A": 2, "B": 1} 代表 A 出 2/3、B 出 1/3）。"""
    if not weights:
        raise ValueError("權重名單不可為空")
    _require_whole(amount)
    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValueError("權重總和必須大於 0")

    names = list(weights.keys())
    shares: Dict[str, Decimal] = {}
    running_total = Decimal("0")
    for name in names[:-1]:
        share = _quantize(amount * weights[name] / total_weight)
        shares[name] = share
        running_total += share
    # 最後一位拿剩餘金額，確保總和精確等於 amount
    shares[names[-1]] = amount - running_total
    return shares


def split_by_fixed(amount: Decimal, fixed: Dict[str, Decimal]) -> Dict[str, Decimal]:
    """使用者直接指定每人分攤金額，需總和等於 amount。"""
    total = sum(fixed.values())
    if total != amount:
        raise ValueError(f"自訂分攤總和 {total} 與消費金額 {amount} 不符")
    return dict(fixed)
