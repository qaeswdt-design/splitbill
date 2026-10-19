"""最少轉帳次數演算法：把多人互相的欠款，簡化成最少筆數的轉帳。

- 人數較少時（預設 <= EXACT_LIMIT 位有欠款的人）使用回溯法(DFS)搜尋
  「真正最少」的轉帳筆數，這是 NP-hard 問題但朋友聚會人數通常很少，
  搜尋空間可控。
- 人數較多時改用貪婪法（每次配對目前最大債權人與最大債務人），
  轉帳筆數上限為 n-1，雖不保證絕對最少但效能穩定、易懂。
"""

from decimal import Decimal
from typing import Dict, List, Tuple

Transfer = Tuple[str, str, Decimal]  # (付款人, 收款人, 金額)

EXACT_LIMIT = 10  # 有非零餘額的人數 <= 此值時，使用精確的回溯搜尋


def _greedy(balances: Dict[str, Decimal]) -> List[Transfer]:
    """貪婪解：人數較多時使用。不窮舉，每次都讓目前欠最多的人付給目前該收
    最多的人，速度快、筆數上限 n-1，但不保證絕對最少。"""
    creditors = [[name, amt] for name, amt in balances.items() if amt > 0]
    debtors = [[name, -amt] for name, amt in balances.items() if amt < 0]
    creditors.sort(key=lambda x: x[1], reverse=True)
    debtors.sort(key=lambda x: x[1], reverse=True)

    transfers: List[Transfer] = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor_name, debt = debtors[i]
        creditor_name, credit = creditors[j]
        pay = min(debt, credit)
        if pay > 0:
            transfers.append((debtor_name, creditor_name, pay))
        debtors[i][1] -= pay
        creditors[j][1] -= pay
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return transfers


def _exact(balances: Dict[str, Decimal]) -> List[Transfer]:
    """精確解：人數較少時使用（<= EXACT_LIMIT）。呼叫下面的 dfs() 窮舉所有
    抵銷組合，保證找到「真正最少」的轉帳筆數。"""
    names = [n for n, v in balances.items() if v != 0]
    values = [balances[n] for n in names]

    best = {"count": len(values), "transfers": None}  # 記錄目前找到的最佳解

    def dfs(idx: int, values: List[Decimal], transfers: List[Transfer]):
        """回溯法（backtracking）遞迴函式：定義在 _exact 內部，可直接讀寫外層的
        names、best，不用當參數傳遞。每次挑一個還沒歸零的人（idx），嘗試跟後面
        某個金額相反的人互相抵銷，遞迴下去看能不能讓所有人都歸零；若目前路徑的
        轉帳筆數已經不可能比目前最佳解更少，就提前放棄（剪枝）。"""
        while idx < len(values) and values[idx] == 0:
            idx += 1
        if idx == len(values):
            if best["transfers"] is None or len(transfers) < best["count"]:
                best["count"] = len(transfers)
                best["transfers"] = list(transfers)
            return
        if len(transfers) + 1 >= best["count"]:
            return  # 剪枝：不可能比目前最佳解更好

        seen_amounts = set()
        for j in range(idx + 1, len(values)):
            if values[j] * values[idx] >= 0:
                continue  # 同號（同為債權人或同為債務人）不能互相抵銷
            if values[j] in seen_amounts:
                continue  # 避免對相同金額的組合重複搜尋
            seen_amounts.add(values[j])

            values[j] += values[idx]
            if values[idx] < 0:
                transfers.append((names[idx], names[j], -values[idx]))
            else:
                transfers.append((names[j], names[idx], values[idx]))

            dfs(idx + 1, values, transfers)

            transfers.pop()
            values[j] -= values[idx]

    dfs(0, values, [])
    return best["transfers"] or []


def suggest_transfers(balances: Dict[str, Decimal]) -> List[Transfer]:
    """對外的唯一入口（ledger.py 只會呼叫這個函式）。
    輸入每人淨餘額（正=應收，負=應付），依人數多寡分派給 _exact() 或
    _greedy() 計算，回傳建議轉帳清單。"""
    active = {n: v for n, v in balances.items() if v != 0}
    if not active:
        return []
    # 基本檢查：所有人淨額加總應為 0（記帳系統內部一致性）
    total = sum(active.values())
    if total != 0:
        raise ValueError(f"餘額加總不為 0（{total}），帳目可能有誤")

    if len(active) <= EXACT_LIMIT:
        return _exact(active)
    return _greedy(active)
