"""Deterministic baseline 'provider': keywords and regular expressions, no network, no cost.

It keeps the pipeline testable without LLM keys and is the baseline the LLMs are compared against in eval/.
It is deliberately simple: header fields and totals from printed labels, table rows of one known layout.
"""
from __future__ import annotations

import re
import time

from .base import LLMResult, Provider

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
          "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
CLASS_RULES = [
    ("upd", re.compile(r"универсальн\w*\s+передаточн\w*\s+документ|\bУПД\b", re.I)),
    ("invoice", re.compile(r"сч[её]т\s+на\s+оплату|сч[её]т\s+№", re.I)),
    ("act", re.compile(r"\bакт\b.{0,60}(?:выполнен|оказани|оказанн|сдачи|при[её]мки)", re.I | re.S)),
    ("contract", re.compile(r"\bдоговор\b.{0,30}№|\bдоговор\s+(?:поставки|оказания|подряда|аренды)", re.I | re.S)),
]
NUM = r"(\d[\d\s]*[.,]\d{2})"


def _money(s: str | None):
    return float(s.replace(" ", "").replace(" ", "").replace(",", ".")) if s else None


def _date(text: str):
    m = re.search(r"от\s+(\d{1,2})[.](\d{1,2})[.](\d{4})", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"от\s+[«\"]?(\d{1,2})[»\"]?\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", text, re.I)
    if m:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


class RulesProvider(Provider):
    name = "rules"
    model = "regex-v1"

    def complete_json(self, task, system, user, schema, max_tokens):
        t0 = time.monotonic()
        text = user.split("<<<DOCUMENT>>>", 1)[-1]
        out = self._classify(text) if task == "classify" else self._extract(text, schema)
        return LLMResult(out, self.name, self.model, 0, 0, int((time.monotonic() - t0) * 1000))

    def _classify(self, text):
        head = text[:1500]
        for doc_type, rx in CLASS_RULES:
            if rx.search(head):
                return {"doc_type": doc_type, "confidence": 0.9, "reason": f"keyword: {rx.pattern[:40]}"}
        return {"doc_type": "other", "confidence": 0.5, "reason": "no known title"}

    def _extract(self, text, schema):
        props = schema.get("properties", {})
        inns = re.findall(r"ИНН\s*:?\s*(\d{10}|\d{12}|\[INN12_\d+\])", text)
        kpps = re.findall(r"КПП\s*:?\s*(\d{4}[0-9A-Z]{2}\d{3})", text)
        names = re.findall(r"(?:Поставщик|Исполнитель|Продавец)\s*:?\s*([^\n,]{3,80})", text)
        buyers = re.findall(r"(?:Покупатель|Заказчик)\s*:?\s*([^\n,]{3,80})", text)
        num = re.search(r"№\s*([A-Za-zА-Яа-я0-9/\-]+)", text)
        total = re.search(r"(?:Всего\s+к\s+оплате|Итого\s+с\s+НДС|Всего\s+с\s+НДС)\s*:?\s*" + NUM, text, re.I)
        base = re.search(r"Итого(?:\s+без\s+НДС)?\s*:?\s*" + NUM, text, re.I)
        vat = re.search(r"НДС\s*\(?(\d{1,2})\s*%\)?\s*:?\s*" + NUM, text, re.I)
        no_vat = re.search(r"без\s+НДС", text, re.I) and not vat
        acc = re.search(r"(?:Р/с|р/с|Расч[её]тный\s+сч[её]т)\s*:?\s*(\d{20}|\[ACCOUNT_\d+\])", text)
        bik = re.search(r"БИК\s*:?\s*(\d{9})", text)
        # table rows "№  name  qty  unit  price  amount" (a known layout; LLMs are for unknown ones)
        lines = []
        for m in re.finditer(r"^\s*\d{1,3}\s+(.+?)\s+(\d+(?:[.,]\d+)?)\s+(\S{1,6})\s+(\d[\d ]*,\d{2})\s+(\d[\d ]*,\d{2})\s*$", text, re.M):
            lines.append({"name": m.group(1).strip(), "qty": float(m.group(2).replace(",", ".")), "unit": m.group(3),
                          "price": _money(m.group(4)), "amount": _money(m.group(5))})
        out = {
            "number": num.group(1) if num else None,
            "date": _date(text),
            "supplier_name": names[0].strip() if names else None,
            "supplier_inn": inns[0] if inns else None,
            "supplier_kpp": kpps[0] if kpps else None,
            "buyer_name": buyers[0].strip() if buyers else None,
            "buyer_inn": inns[1] if len(inns) > 1 else None,
            "buyer_kpp": kpps[1] if len(kpps) > 1 else None,
            "lines": lines,
            "total_without_vat": _money(base.group(1)) if base else None,
            "vat_rate": int(vat.group(1)) if vat else (None if no_vat else None),
            "vat_amount": _money(vat.group(2)) if vat else (0.0 if no_vat else None),
            "total": _money(total.group(1)) if total else None,
            "supplier_account": acc.group(1) if acc else None,
            "supplier_bik": bik.group(1) if bik else None,
            "upd_status": (int(m.group(1)) if (m := re.search(r"Статус\s*:?\s*([12])", text)) else None),
            "subject": None, "valid_until": None,
        }
        return {k: v for k, v in out.items() if k in props}
