"""金額算式：讓金額/權重欄位可以直接輸入加總，例如 42+48+52 或 42*2+48。

只支援數字、加號與乘號（乘號可用 * 、x 、×），不使用 eval，避免任何程式碼注入的可能。
"""

import re
from decimal import Decimal

MAX_VALUE = Decimal("1000000000000")
MAX_LENGTH = 100
_NUMBER = re.compile(r"\d+(?:\.\d+)?|\.\d+")
_OPERATORS = re.compile(r"[+*]")

FORMAT_HINT = "格式錯誤，請輸入數字或算式（例如 42+48+52 或 42*2+48）"


def eval_amount(text) -> Decimal:
    """把「42+48+52」這類算式算成 Decimal；格式不對時丟出 ValueError。"""
    s = str(text if text is not None else "").strip()
    s = s.replace("＋", "+").replace("×", "*").replace("x", "*").replace("X", "*")
    s = re.sub(r"\s*([+*])\s*", r"\1", s)  # 運算符號前後的空白可以忽略
    if not s or len(s) > MAX_LENGTH or re.search(r"\s", s):  # 數字中間夾空白（如 "4 2"）視為錯誤
        raise ValueError(FORMAT_HINT)

    total = Decimal(0)
    for term in s.split("+"):
        if not term:
            raise ValueError(FORMAT_HINT)
        product = Decimal(1)
        for factor in term.split("*"):
            if not _NUMBER.fullmatch(factor):
                raise ValueError(FORMAT_HINT)
            product *= Decimal(factor)
        total += product

    if total >= MAX_VALUE:
        raise ValueError("過大")
    return total


def has_operator(text) -> bool:
    s = str(text).replace("＋", "+").replace("×", "*").replace("x", "*").replace("X", "*")
    return bool(_OPERATORS.search(s))
