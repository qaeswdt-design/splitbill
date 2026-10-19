"""純文字命令列介面（不依賴任何第三方套件）。"""

from decimal import Decimal
from typing import List

from . import splitter, storage
from .expression import eval_amount, has_operator
from .ledger import Ledger

MENU = """
========== 朋友聚會拆帳記帳系統 ==========
1. 新增朋友
2. 新增一筆消費並拆帳
3. 查看目前餘額狀況
4. 產生最少轉帳次數的結算建議
5. 記錄一筆轉帳（等待收款方確認）
6. 確認收到轉帳（或標示沒收到）
7. 查看歷史紀錄
8. 刪除朋友
9. 刪除消費紀錄（輸入錯誤時更正用）
10. 刪除轉帳紀錄（輸入錯誤時更正用）
11. 新增/更新常用群組
12. 刪除常用群組
0. 儲存並離開
==========================================
"""


def prompt_decimal(msg: str) -> Decimal:
    """輸入數字或算式（例如 300、42+48+52、42*2+48），算式會顯示加總結果。"""
    while True:
        raw = input(msg).strip()
        try:
            value = eval_amount(raw)
        except ValueError as e:
            print(f"輸入{e}")
            continue
        if has_operator(raw):
            print(f"  → {value}")
        return value


def confirm_yes_no(msg: str) -> bool:
    return input(msg).strip().lower() in ("y", "yes")


def friend_list_display(ledger: Ledger) -> str:
    if not ledger.people:
        return "(尚無資料)"
    return "、".join(f"{ledger.code_of(name)}:{name}" for name in ledger.people)


def group_list_display(ledger: Ledger) -> str:
    if not ledger.groups:
        return "(尚無群組)"
    return "、".join(f"{name}:{'+'.join(members)}" for name, members in ledger.groups.items())


def prompt_person(ledger: Ledger, msg: str) -> str:
    """輸入代號或全名，回傳解析後的全名。輸入錯誤會拋出 ValueError。"""
    print(f"目前朋友名單：{friend_list_display(ledger)}")
    raw = input(msg).strip()
    return ledger.resolve_person(raw)


def resolve_participant_tokens(ledger: Ledger, raw: str) -> List[str]:
    """把使用者輸入的一串代號/全名/群組，解析成不重複的全名清單。

    - 留空或輸入 all/全部：代表目前所有朋友
    - 用逗號分隔多個代號或全名
    - 以 @ 開頭代表套用一個常用群組（例如 @聚餐組），可與其他代號混用
    """
    raw = raw.strip()
    if not raw or raw.lower() in ("all", "全部"):
        if not ledger.people:
            raise ValueError("目前沒有任何朋友")
        return list(ledger.people)

    tokens = [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
    names: List[str] = []
    for token in tokens:
        if token.startswith("@"):
            names.extend(ledger.resolve_group(token[1:].strip()))
        else:
            names.append(ledger.resolve_person(token))

    deduped: List[str] = []
    for name in names:
        if name not in deduped:
            deduped.append(name)
    return deduped


def prompt_people_csv(ledger: Ledger, msg: str) -> List[str]:
    """輸入代號/全名/群組清單，回傳解析後不重複的全名清單。"""
    print(f"目前朋友名單：{friend_list_display(ledger)}")
    if ledger.groups:
        print(f"常用群組：{group_list_display(ledger)}（輸入 @群組名稱 套用）")
    raw = input(f"{msg}（直接按 Enter 或輸入 all/全部 代表所有朋友）：")
    return resolve_participant_tokens(ledger, raw)


def action_add_person(ledger: Ledger) -> None:
    name = input("請輸入新朋友的名字：").strip()
    try:
        code = ledger.add_person(name)
    except ValueError as e:
        print(f"錯誤：{e}")
        return
    print(f"已新增「{name}」，代號為 {code}（之後可直接輸入代號取代全名）")
    storage.save(ledger)


def action_add_expense(ledger: Ledger) -> None:
    if not ledger.people:
        print("請先新增朋友")
        return

    try:
        payer = prompt_person(ledger, "這筆消費由誰先付款？（可輸入代號或全名）：")
    except ValueError as e:
        print(f"錯誤：{e}")
        return

    description = input("消費說明（例如：晚餐、KTV）：").strip()
    print("提示：金額與權重都可以直接輸入算式，例如 42+48+52 或 42*2+48（乘號也可打 x）")
    amount = prompt_decimal("總金額：")

    print("拆帳方式：1) 平均分攤  2) 依比例分攤  3) 自訂每人金額")
    method = input("請選擇 [1/2/3]（預設 1）：").strip() or "1"

    try:
        if method == "1":
            participants = prompt_people_csv(ledger, "參與分攤的人（代號/全名/群組，逗號分隔）")
            shares = splitter.split_equal(amount, participants)
        elif method == "2":
            participants = prompt_people_csv(ledger, "參與分攤的人（代號/全名/群組，逗號分隔）")
            weights = {}
            for name in participants:
                w = prompt_decimal(f"「{name}」的權重（例如 1、2，或各項金額相加 42+48）：")
                weights[name] = w
            shares = splitter.split_by_ratio(amount, weights)
        elif method == "3":
            participants = prompt_people_csv(ledger, "參與分攤的人（代號/全名/群組，逗號分隔）")
            shares = {}
            for name in participants:
                a = prompt_decimal(f"「{name}」分攤金額：")
                shares[name] = a
            splitter.split_by_fixed(amount, shares)  # 僅用來驗證總和是否等於總金額
        else:
            print("無效的選項")
            return
    except ValueError as e:
        print(f"錯誤：{e}")
        return

    print("---- 請確認以下內容 ----")
    print(f"付款人：{payer}")
    print(f"說明：{description or '(未命名消費)'}")
    print(f"總金額：{amount}")
    for name, share in shares.items():
        print(f"  - {name} 應分攤 {share}")

    if not confirm_yes_no("確定要新增這筆消費嗎？(Y/N)："):
        print("已取消，未儲存")
        return

    expense = ledger.add_expense_fixed(payer, amount, shares, description)
    print(f"已新增消費「{expense.description}」")
    storage.save(ledger)


def action_show_balances(ledger: Ledger) -> None:
    balances = ledger.calc_net_balances()
    if not balances:
        print("目前尚無資料")
        return
    print("---- 目前餘額狀況 ----")
    for name, amount in balances.items():
        code = ledger.code_of(name)
        label = f"{code}:{name}" if code else name
        if amount > 0:
            print(f"  {label}：應收 {amount}")
        elif amount < 0:
            print(f"  {label}：應付 {-amount}")
        else:
            print(f"  {label}：已結清")

    pending = ledger.pending_payments()
    if pending:
        print("---- 尚待收款方確認的轉帳 ----")
        for p in pending:
            print(f"  [{p.id}] {p.payer} -> {p.payee}：{p.amount}（{p.timestamp}）")


def action_suggest_settlement(ledger: Ledger) -> None:
    try:
        transfers = ledger.suggest_settlement()
    except ValueError as e:
        print(f"錯誤：{e}")
        return

    if not transfers:
        print("目前所有人帳目已結清，不需要轉帳！")
        return

    print(f"---- 建議轉帳方案（共 {len(transfers)} 筆，已是最少次數）----")
    for payer, payee, amount in transfers:
        print(f"  {payer} 轉帳 {amount} 給 {payee}")
    print("提示：完成轉帳後，可使用選單 5 記錄該筆轉帳，再由收款方以選單 6 確認收款。")


def action_record_payment(ledger: Ledger) -> None:
    if not ledger.people:
        print("請先新增朋友")
        return

    try:
        payer = prompt_person(ledger, "轉出方（誰付錢，代號或全名）：")
        payee = prompt_person(ledger, "收款方（誰收錢，代號或全名）：")
    except ValueError as e:
        print(f"錯誤：{e}")
        return

    amount = prompt_decimal("轉帳金額：")
    note = input("備註（可留空）：").strip()

    print(f"---- 請確認：{payer} 轉帳 {amount} 給 {payee} ----")
    if not confirm_yes_no("確定要記錄這筆轉帳嗎？(Y/N)："):
        print("已取消，未儲存")
        return

    try:
        payment = ledger.record_payment(payer, payee, amount, note)
    except ValueError as e:
        print(f"錯誤：{e}")
        return

    print(f"已記錄轉帳 [{payment.id}]，尚待「{payee}」確認收款（選單 6）")
    storage.save(ledger)


def action_confirm_payment(ledger: Ledger) -> None:
    pending = ledger.pending_payments()
    if not pending:
        print("目前沒有待確認的轉帳")
        return
    print("---- 待確認的轉帳 ----")
    for p in pending:
        print(f"  [{p.id}] {p.payer} -> {p.payee}：{p.amount}（{p.timestamp}）備註：{p.note}")

    payment_id = input("請輸入要確認的轉帳編號：").strip()
    payment = next((p for p in pending if p.id == payment_id), None)
    if payment is None:
        print("錯誤：找不到該筆待確認的轉帳")
        return

    print(f"{payment.payer} -> {payment.payee}：{payment.amount}")
    print("請選擇：1) 已收到  2) 沒收到（標示為未收到，不計入餘額）  其他) 取消")
    choice = input("請輸入 [1/2]：").strip()
    if choice == "1":
        if not confirm_yes_no("確定已經收到這筆款項嗎？(Y/N)："):
            print("已取消")
            return
        ledger.confirm_payment(payment.id)
        print(f"已確認收款 {payment.payer} -> {payment.payee}：{payment.amount}")
    elif choice == "2":
        if not confirm_yes_no("確定沒有收到這筆款項嗎？(Y/N)："):
            print("已取消")
            return
        ledger.reject_payment(payment.id)
        print(f"已標示為未收到 {payment.payer} -> {payment.payee}：{payment.amount}")
    else:
        print("已取消")
        return
    storage.save(ledger)


def payment_status(p) -> str:
    if p.confirmed:
        return "已確認"
    return "未收到" if p.rejected else "待確認"


def action_show_history(ledger: Ledger) -> None:
    print("---- 消費紀錄 ----")
    if not ledger.expenses:
        print("  (無)")
    for e in ledger.expenses:
        print(f"  [{e.id}] {e.timestamp} {e.payer} 付了 {e.amount}（{e.description}）")

    print("---- 轉帳紀錄 ----")
    if not ledger.payments:
        print("  (無)")
    for p in ledger.payments:
        print(f"  [{p.id}] {p.timestamp} {p.payer} -> {p.payee}：{p.amount}（{payment_status(p)}）")


def action_remove_person(ledger: Ledger) -> None:
    if not ledger.people:
        print("目前尚無朋友資料")
        return

    try:
        name = prompt_person(ledger, "要刪除哪位朋友？（代號或全名）：")
    except ValueError as e:
        print(f"錯誤：{e}")
        return

    if not confirm_yes_no(f"確定要刪除「{name}」嗎？(Y/N)："):
        print("已取消")
        return

    try:
        ledger.remove_person(name)
    except ValueError as e:
        print(f"錯誤：{e}")
        return
    print(f"已刪除「{name}」")
    storage.save(ledger)


def action_delete_expense(ledger: Ledger) -> None:
    if not ledger.expenses:
        print("目前尚無消費紀錄")
        return
    print("---- 消費紀錄 ----")
    for e in ledger.expenses:
        print(f"  [{e.id}] {e.timestamp} {e.payer} 付了 {e.amount}（{e.description}）")

    expense_id = input("要刪除哪一筆？請輸入編號：").strip()
    expense = next((e for e in ledger.expenses if e.id == expense_id), None)
    if expense is None:
        print("錯誤：找不到該筆消費紀錄")
        return

    if not confirm_yes_no(f"確定要刪除「{expense.description}」（{expense.amount}）嗎？(Y/N)："):
        print("已取消")
        return

    ledger.delete_expense(expense_id)
    print(f"已刪除消費「{expense.description}」（{expense.amount}），餘額已自動重新計算")
    storage.save(ledger)


def action_delete_payment(ledger: Ledger) -> None:
    if not ledger.payments:
        print("目前尚無轉帳紀錄")
        return
    print("---- 轉帳紀錄 ----")
    for p in ledger.payments:
        print(f"  [{p.id}] {p.timestamp} {p.payer} -> {p.payee}：{p.amount}（{payment_status(p)}）")

    payment_id = input("要刪除哪一筆？請輸入編號：").strip()
    payment = next((p for p in ledger.payments if p.id == payment_id), None)
    if payment is None:
        print("錯誤：找不到該筆轉帳紀錄")
        return

    note = "（此筆先前已確認收款，刪除後餘額會自動恢復）" if payment.confirmed else ""
    if not confirm_yes_no(f"確定要刪除 {payment.payer} -> {payment.payee}：{payment.amount}{note} 嗎？(Y/N)："):
        print("已取消")
        return

    ledger.delete_payment(payment_id)
    print(f"已刪除轉帳 {payment.payer} -> {payment.payee}：{payment.amount}{note}")
    storage.save(ledger)


def action_save_group(ledger: Ledger) -> None:
    if not ledger.people:
        print("請先新增朋友")
        return

    if ledger.groups:
        print(f"目前群組：{group_list_display(ledger)}")
    group_name = input("群組名稱（取新名稱=新增，輸入已存在的名稱=覆蓋更新）：").strip()

    try:
        members = prompt_people_csv(ledger, "這個群組包含哪些人（代號/全名，逗號分隔）")
    except ValueError as e:
        print(f"錯誤：{e}")
        return

    print(f"---- 群組「{group_name}」成員：{'、'.join(members)} ----")
    if not confirm_yes_no("確定要儲存這個群組嗎？(Y/N)："):
        print("已取消")
        return

    try:
        ledger.save_group(group_name, members)
    except ValueError as e:
        print(f"錯誤：{e}")
        return
    print(f"已儲存群組「{group_name}」，之後輸入參與者時可打 @{group_name} 套用")
    storage.save(ledger)


def action_delete_group(ledger: Ledger) -> None:
    if not ledger.groups:
        print("目前尚無群組")
        return
    print(f"目前群組：{group_list_display(ledger)}")
    group_name = input("要刪除哪個群組？：").strip()
    if group_name not in ledger.groups:
        print("錯誤：找不到該群組")
        return

    if not confirm_yes_no(f"確定要刪除群組「{group_name}」嗎？(Y/N)："):
        print("已取消")
        return

    ledger.delete_group(group_name)
    print(f"已刪除群組「{group_name}」")
    storage.save(ledger)


ACTIONS = {
    "1": action_add_person,
    "2": action_add_expense,
    "3": action_show_balances,
    "4": action_suggest_settlement,
    "5": action_record_payment,
    "6": action_confirm_payment,
    "7": action_show_history,
    "8": action_remove_person,
    "9": action_delete_expense,
    "10": action_delete_payment,
    "11": action_save_group,
    "12": action_delete_group,
}


def run() -> None:
    ledger = storage.load()
    print("已載入既有記帳資料。" if ledger.people or ledger.expenses else "歡迎使用，目前尚無資料。")

    while True:
        print(MENU)
        choice = input("請選擇功能：").strip()
        if choice == "0":
            storage.save(ledger)
            print("資料已儲存，再見！")
            break

        action = ACTIONS.get(choice)
        if action is None:
            print("無效的選項，請重新輸入")
            continue
        action(ledger)
