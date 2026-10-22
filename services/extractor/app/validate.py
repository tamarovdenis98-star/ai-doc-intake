"""Deterministic checks of extracted data. No LLM here: every rule is arithmetic or a registry rule.

The result decides the route: all checks pass and the classifier is confident -> 'auto', otherwise 'review'
(a card with buttons in Telegram, stage 7).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

MONEY_TOL = 0.01           # kopecks
VAT_RATES = {22, 20, 10, 5, 7, 0}
VAT_22_FROM = date(2026, 1, 1)   # 425-ФЗ: 22 % for operations from 2026-01-01
MAX_AGE_DAYS = 3 * 365

W10 = [2, 4, 10, 3, 5, 9, 4, 6, 8]
W11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
W12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]


def inn_valid(inn) -> bool:
    s = str(inn or "")
    if not s.isdigit() or len(s) not in (10, 12):
        return False
    d = [int(c) for c in s]
    ctl = lambda w: sum(a * b for a, b in zip(w, d)) % 11 % 10  # noqa: E731
    if len(s) == 10:
        return ctl(W10) == d[9]
    return ctl(W11) == d[10] and ctl(W12) == d[11]


def kpp_valid(kpp) -> bool:
    s = str(kpp or "")
    return len(s) == 9 and s[:4].isdigit() and s[4:6].isalnum() and s[4:6].upper() == s[4:6] and s[6:].isdigit()


@dataclass
class Check:
    code: str
    ok: bool
    message: str


def _eq(a, b, tol=MONEY_TOL) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol + 1e-9


def validate(doc_type: str, data: dict, *, today: date | None = None, duplicate_of: int | None = None,
             class_confidence: float | None = None, min_class_confidence: float = 0.8,
             required: list[str] | None = None) -> dict:
    today = today or date.today()
    checks: list[Check] = []
    add = lambda code, ok, msg: checks.append(Check(code, bool(ok), msg))  # noqa: E731

    if doc_type == "other":
        return {"ok": False, "decision": "review", "checks": [], "reasons": ["document type 'other': not processed automatically"]}

    # vat_rate = null is a value ("без НДС"), not a missing field
    missing = [f for f in (required or []) if f != "vat_rate" and data.get(f) in (None, "", [])]
    add("required_fields", not missing, "all required fields present" if not missing else f"missing: {', '.join(missing)}")

    for side in ("supplier", "buyer"):
        inn, kpp = data.get(f"{side}_inn"), data.get(f"{side}_kpp")
        if inn:
            add(f"{side}_inn_checksum", inn_valid(inn), f"{side} INN {inn}: checksum " + ("ok" if inn_valid(inn) else "mismatch"))
        if kpp:
            ok = kpp_valid(kpp) and len(str(inn or "")) != 12
            add(f"{side}_kpp", ok, f"{side} KPP {kpp}: " + ("ok" if ok else "bad format or KPP for an individual entrepreneur"))

    doc_date = _parse_date(data.get("date"))
    if data.get("date") is not None:
        ok = doc_date is not None and today - timedelta(days=MAX_AGE_DAYS) <= doc_date <= today + timedelta(days=1)
        add("date_range", ok, f"date {data.get('date')}: " + ("ok" if ok else "unparseable, in the future or older than 3 years"))

    if doc_type in ("invoice", "act", "upd"):
        lines = data.get("lines") or []
        bad = [i + 1 for i, ln in enumerate(lines) if not _eq(float(ln["qty"]) * float(ln["price"]), ln["amount"], MONEY_TOL * 2)]
        add("line_math", not bad, "qty × price = amount on every line" if not bad else f"qty × price ≠ amount on lines {bad}")

        base = data.get("total_without_vat")
        if lines:
            s = round(sum(float(ln["amount"]) for ln in lines), 2)
            if base is not None:
                add("lines_sum", _eq(s, base, MONEY_TOL * max(1, len(lines))), f"sum of lines {s} vs total without VAT {base}")
            else:
                base = s

        rate, vat, total = data.get("vat_rate"), data.get("vat_amount"), data.get("total")
        if rate in (None, 0):
            add("vat_math", vat in (None, 0) or _eq(vat, 0), f"no VAT / 0 %: VAT amount {vat}")
        elif rate not in VAT_RATES:
            add("vat_math", False, f"unknown VAT rate {rate} %")
        elif base is not None:
            on_top = round(float(base) * rate / 100, 2)
            included = round(float(total) * rate / (100 + rate), 2) if total is not None else None
            ok = _eq(vat, on_top) or _eq(vat, included)
            add("vat_math", ok, f"VAT {vat} vs {rate} % of {base} = {on_top}" + (f" (or included in total: {included})" if included is not None else ""))
        if rate in (20, 22) and doc_date:
            expected = 22 if doc_date >= VAT_22_FROM else 20
            add("vat_rate_actual", rate == expected, f"VAT {rate} % on {doc_date}: the rate in force is {expected} %")
        if total is not None and base is not None:
            ok = _eq(total, float(base) + float(vat or 0)) or _eq(total, base)
            add("total_math", ok, f"total {total} vs without VAT {base} + VAT {vat or 0}")

    if duplicate_of:
        add("not_duplicate", False, f"same supplier INN, number and date as document #{duplicate_of}")
    else:
        add("not_duplicate", True, "no earlier document with the same supplier INN, number and date")

    failed = [c for c in checks if not c.ok]
    reasons = [c.message for c in failed]
    if class_confidence is not None and class_confidence < min_class_confidence:
        reasons.append(f"classifier confidence {class_confidence} < {min_class_confidence}")
    return {"ok": not failed, "decision": "auto" if not reasons else "review",
            "checks": [asdict(c) for c in checks], "reasons": reasons}


def _parse_date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)) if s else None
    except ValueError:
        return None
