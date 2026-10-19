"""將 Ledger 存讀成 JSON 檔案（僅使用標準庫 json）。"""

import json
import os

from .ledger import Ledger

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ledger.json")


def save(ledger: Ledger, path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger.to_dict(), f, ensure_ascii=False, indent=2)


def load(path: str = DEFAULT_PATH) -> Ledger:
    if not os.path.exists(path):
        return Ledger()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Ledger.from_dict(data)
