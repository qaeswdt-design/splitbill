"""本地網頁伺服器（僅用標準庫 http.server）：同一個 WiFi 下的手機可用瀏覽器操作記帳系統。

核心邏輯完全沿用 Ledger / splitter / settlement，這裡只負責把它們包成 JSON API。
"""

import hmac
import json
import os
import secrets
import socket
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Tuple

from . import splitter, storage
from .expression import eval_amount
from .ledger import Ledger

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MAX_BODY = 64 * 1024
MAX_NAME_LEN = 30
MAX_TEXT_LEN = 100


# ---------- 輸入檢查 ----------


def _dec(value, label: str) -> Decimal:
    try:
        return eval_amount(value)
    except ValueError as e:
        raise ValueError(f"{label}{e}")


def _text(value, label: str, limit: int, required: bool = False) -> str:
    s = str(value if value is not None else "").strip()
    if required and not s:
        raise ValueError(f"{label}不可為空")
    if len(s) > limit:
        raise ValueError(f"{label}最多 {limit} 個字")
    return s


def _name_list(ledger: Ledger, raw) -> List[str]:
    if not isinstance(raw, list):
        raise ValueError("名單格式錯誤")
    names: List[str] = []
    for item in raw:
        name = ledger.resolve_person(str(item))
        if name not in names:
            names.append(name)
    return names


# ---------- API 實作（每個函式：收 Ledger + 請求內容，回傳可轉成 JSON 的結果） ----------


def api_state(ledger: Ledger, body: dict) -> dict:
    balances = ledger.calc_net_balances()
    try:
        suggestions = [
            {"from": a, "to": b, "amount": str(c)} for a, b, c in ledger.suggest_settlement()
        ]
        suggest_error = ""
    except ValueError as e:
        suggestions, suggest_error = [], str(e)
    return {
        "people": [{"code": ledger.code_of(n), "name": n} for n in ledger.people],
        "groups": {g: list(m) for g, m in ledger.groups.items()},
        "balances": {n: str(v) for n, v in balances.items()},
        "suggestions": suggestions,
        "suggest_error": suggest_error,
        "expenses": [e.to_dict() for e in ledger.expenses],
        "payments": [p.to_dict() for p in ledger.payments],
    }


def api_add_person(ledger: Ledger, body: dict) -> dict:
    name = _text(body.get("name"), "姓名", MAX_NAME_LEN, required=True)
    return {"code": ledger.add_person(name)}


def api_remove_person(ledger: Ledger, body: dict) -> dict:
    ledger.remove_person(ledger.resolve_person(str(body.get("name", ""))))
    return {}


def _build_expense(ledger: Ledger, body: dict) -> Tuple[str, Decimal, str, Dict[str, Decimal]]:
    payer = ledger.resolve_person(str(body.get("payer", "")))
    amount = _dec(body.get("amount"), "金額")
    if amount <= 0:
        raise ValueError("金額必須大於 0")
    description = _text(body.get("description"), "說明", MAX_TEXT_LEN) or "(未命名消費)"
    participants = _name_list(ledger, body.get("participants"))
    if not participants:
        raise ValueError("請至少選擇一位參與者")

    method = body.get("method", "equal")
    values = body.get("values") or {}
    if method == "equal":
        shares = splitter.split_equal(amount, participants)
    elif method == "ratio":
        weights = {}
        for n in participants:
            w = _dec(values.get(n, ""), f"「{n}」的權重")
            if w < 0:
                raise ValueError(f"「{n}」的權重不可為負數")
            weights[n] = w
        shares = splitter.split_by_ratio(amount, weights)
    elif method == "fixed":
        fixed = {}
        for n in participants:
            a = _dec(values.get(n, ""), f"「{n}」的分攤金額")
            if a < 0:
                raise ValueError(f"「{n}」的分攤金額不可為負數")
            fixed[n] = a
        shares = splitter.split_by_fixed(amount, fixed)
    else:
        raise ValueError("無效的拆帳方式")
    return payer, amount, description, shares


def api_expense_preview(ledger: Ledger, body: dict) -> dict:
    payer, amount, description, shares = _build_expense(ledger, body)
    return {
        "payer": payer,
        "amount": str(amount),
        "description": description,
        "shares": {n: str(s) for n, s in shares.items()},
    }


def api_expense_add(ledger: Ledger, body: dict) -> dict:
    payer, amount, description, shares = _build_expense(ledger, body)
    expense = ledger.add_expense_fixed(payer, amount, shares, description)
    return {"id": expense.id}


def api_expense_delete(ledger: Ledger, body: dict) -> dict:
    ledger.delete_expense(str(body.get("id", "")))
    return {}


def api_payment_add(ledger: Ledger, body: dict) -> dict:
    payer = ledger.resolve_person(str(body.get("payer", "")))
    payee = ledger.resolve_person(str(body.get("payee", "")))
    if payer == payee:
        raise ValueError("轉出方和收款方不能是同一個人")
    amount = _dec(body.get("amount"), "金額")
    note = _text(body.get("note"), "備註", MAX_TEXT_LEN)
    return {"id": ledger.record_payment(payer, payee, amount, note).id}


def api_payment_confirm(ledger: Ledger, body: dict) -> dict:
    ledger.confirm_payment(str(body.get("id", "")))
    return {}


def api_payment_reject(ledger: Ledger, body: dict) -> dict:
    ledger.reject_payment(str(body.get("id", "")))
    return {}


def api_payment_delete(ledger: Ledger, body: dict) -> dict:
    ledger.delete_payment(str(body.get("id", "")))
    return {}


def api_group_save(ledger: Ledger, body: dict) -> dict:
    name = _text(body.get("name"), "群組名稱", MAX_NAME_LEN, required=True)
    ledger.save_group(name, _name_list(ledger, body.get("members")))
    return {}


def api_group_delete(ledger: Ledger, body: dict) -> dict:
    ledger.delete_group(str(body.get("name", "")))
    return {}


# 路徑 -> (處理函式, 是否會改動資料；會改動的在成功後自動存檔)
ROUTES: Dict[str, Tuple[Callable[[Ledger, dict], dict], bool]] = {
    "/api/state": (api_state, False),
    "/api/person/add": (api_add_person, True),
    "/api/person/remove": (api_remove_person, True),
    "/api/expense/preview": (api_expense_preview, False),
    "/api/expense/add": (api_expense_add, True),
    "/api/expense/delete": (api_expense_delete, True),
    "/api/payment/add": (api_payment_add, True),
    "/api/payment/confirm": (api_payment_confirm, True),
    "/api/payment/reject": (api_payment_reject, True),
    "/api/payment/delete": (api_payment_delete, True),
    "/api/group/save": (api_group_save, True),
    "/api/group/delete": (api_group_delete, True),
}


# ---------- HTTP 層 ----------


class LedgerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, ledger: Ledger, token: str, save_path: str):
        super().__init__(address, Handler)
        self.ledger = ledger
        self.token = token
        self.save_path = save_path
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server: LedgerServer

    def log_message(self, fmt, *args):
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'unsafe-inline'; "
            "style-src 'unsafe-inline'; connect-src 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        given = self.headers.get("X-Key", "")
        return hmac.compare_digest(given.encode("utf-8"), self.server.token.encode("utf-8"))

    def _dispatch(self, body: dict) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "存取金鑰錯誤，請用終端機顯示的完整網址開啟"})
            return
        route = ROUTES.get(self.path.split("?")[0])
        if route is None:
            self._send_json(404, {"error": "找不到這個功能"})
            return
        func, mutates = route
        srv = self.server
        try:
            with srv.lock:
                result = func(srv.ledger, body)
                if mutates:
                    storage.save(srv.ledger, srv.save_path)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return
        except OSError:
            self._send_json(500, {"error": "存檔失敗，請檢查資料夾權限"})
            return
        self._send_json(200, result)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(STATIC_DIR, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif path == "/api/state":
            self._dispatch({})
        else:
            self._send_json(404, {"error": "找不到頁面"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "請求格式錯誤"})
            return
        if length < 0 or length > MAX_BODY:
            self._send_json(413, {"error": "請求內容過大"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send_json(400, {"error": "請求格式錯誤"})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "請求格式錯誤"})
            return
        self._dispatch(body)


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # UDP 不會真的送出封包，只是借此問出本機對外的網卡位址
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def run(port: int = 8000, save_path: str = storage.DEFAULT_PATH) -> None:
    ledger = storage.load(save_path)
    token = secrets.token_urlsafe(6)
    server = LedgerServer(("0.0.0.0", port), ledger, token, save_path)
    port = server.server_address[1]

    print("網頁版已啟動。讓手機連上跟這台電腦「同一個 WiFi」，用瀏覽器開啟：", flush=True)
    print(f"  http://{lan_ip()}:{port}/?k={token}", flush=True)
    print(f"（本機測試：http://127.0.0.1:{port}/?k={token}）", flush=True)
    print("注意：任何拿到這個完整網址的人都能修改帳目，請只分享給朋友。按 Ctrl+C 停止。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with server.lock:
            storage.save(server.ledger, save_path)
        server.server_close()
        print("\n已停止並存檔。")
