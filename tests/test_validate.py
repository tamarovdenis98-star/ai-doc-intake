"""Deterministic validator: INN/KPP, arithmetic, VAT rate in force, dates, duplicates, routing."""
from datetime import date

import pytest

from app.validate import inn_valid, kpp_valid, validate

TODAY = date(2026, 10, 22)
REQ = ["number", "date", "supplier_name", "supplier_inn", "buyer_inn", "total", "lines", "vat_rate", "vat_amount"]


def invoice(**over):
    lines = [{"name": "Бумага", "qty": 10, "unit": "пач", "price": 350.0, "amount": 3500.0},
             {"name": "Картридж", "qty": 2, "unit": "шт", "price": 4200.5, "amount": 8401.0}]
    d = {"number": "А-17", "date": "2026-09-15", "supplier_name": "ООО «Ромашка»", "supplier_inn": "7707083893",
         "supplier_kpp": "770701001", "buyer_name": "ООО «Покупатель»", "buyer_inn": "7736207543", "buyer_kpp": "773601001",
         "lines": lines, "total_without_vat": 11901.0, "vat_rate": 22, "vat_amount": 2618.22, "total": 14519.22}
    d.update(over)
    return d


def codes(res, ok=False):
    return {c["code"] for c in res["checks"] if c["ok"] is ok}


def test_clean_invoice_goes_auto():
    res = validate("invoice", invoice(), today=TODAY, class_confidence=0.95, required=REQ)
    assert res["decision"] == "auto" and res["ok"], res["reasons"]


@pytest.mark.parametrize("over, failed", [
    ({"total": 14619.22}, "total_math"),
    ({"vat_amount": 2380.2, "total": 14281.2}, "vat_math"),
    ({"supplier_inn": "7707083894"}, "supplier_inn_checksum"),
    ({"supplier_kpp": "77070100"}, "supplier_kpp"),
    ({"total_without_vat": 11000.0}, "lines_sum"),
    ({"date": "2027-01-10"}, "date_range"),
    ({"date": "2022-01-10", "vat_rate": 20, "vat_amount": 2380.2, "total": 14281.2}, "date_range"),
    ({"vat_rate": 20, "vat_amount": 2380.2, "total": 14281.2}, "vat_rate_actual"),   # 20 % in 2026 is stale
    ({"number": None}, "required_fields"),
])
def test_defects_go_to_review(over, failed):
    res = validate("invoice", invoice(**over), today=TODAY, class_confidence=0.95, required=REQ)
    assert res["decision"] == "review" and failed in codes(res), res["checks"]


def test_line_math():
    d = invoice()
    d["lines"][0]["amount"] = 3510.0
    res = validate("invoice", d, today=TODAY, required=REQ)
    assert "line_math" in codes(res)


def test_vat_included_style_is_accepted():
    """«в т.ч. НДС»: lines and total include VAT; VAT = total × 22/122."""
    lines = [{"name": "Услуга", "qty": 1, "unit": "шт", "price": 12200.0, "amount": 12200.0}]
    d = invoice(lines=lines, total_without_vat=None, vat_amount=2200.0, total=12200.0)
    res = validate("invoice", d, today=TODAY, class_confidence=0.9, required=REQ)
    assert res["decision"] == "auto", res["reasons"]


def test_2025_document_with_20_percent_is_fine():
    d = invoice(date="2025-11-03", vat_rate=20, vat_amount=2380.2, total=14281.2)
    assert validate("invoice", d, today=TODAY, class_confidence=0.9, required=REQ)["decision"] == "auto"


def test_no_vat_for_individual_entrepreneur():
    d = invoice(supplier_inn="500100732259", supplier_kpp=None, vat_rate=None, vat_amount=0, total=11901.0)
    assert validate("invoice", d, today=TODAY, class_confidence=0.9, required=REQ)["decision"] == "auto"


def test_kpp_for_individual_is_an_error():
    d = invoice(supplier_inn="500100732259", supplier_kpp="500101001", vat_rate=None, vat_amount=0, total=11901.0)
    assert "supplier_kpp" in codes(validate("invoice", d, today=TODAY, required=REQ))


def test_business_duplicate_goes_to_review():
    res = validate("invoice", invoice(), today=TODAY, class_confidence=0.95, duplicate_of=12, required=REQ)
    assert res["decision"] == "review" and "not_duplicate" in codes(res)


def test_low_classifier_confidence_goes_to_review():
    res = validate("invoice", invoice(), today=TODAY, class_confidence=0.6, required=REQ)
    assert res["ok"] and res["decision"] == "review"


def test_other_is_never_auto():
    assert validate("other", {}, today=TODAY)["decision"] == "review"


@pytest.mark.parametrize("inn, ok", [("7707083893", True), ("500100732259", True), ("7707083894", False), ("12345", False), (None, False)])
def test_inn(inn, ok):
    assert inn_valid(inn) is ok


@pytest.mark.parametrize("kpp, ok", [("770701001", True), ("7707AB001", True), ("77070100", False), ("7707ab001", False)])
def test_kpp(kpp, ok):
    assert kpp_valid(kpp) is ok
