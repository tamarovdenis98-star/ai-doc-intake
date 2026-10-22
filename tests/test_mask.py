"""Personal data never leaves for an external LLM; placeholders come back as the original values."""
from app.mask import leaked, mask, unmask

DOC = """Счёт на оплату № 17 от 15 сентября 2026 г.
Сч. № 40702810938000012345    БИК 044525225
Поставщик: ИП Петрова Мария Сергеевна, ИНН 500100732259
Покупатель: ООО «Ромашка», ИНН 7707083893, КПП 770701001
Руководитель ____ Иванов И.И.   Тел. +7 (916) 123-45-67   buh@romashka.ru
Главный бухгалтер ____ О.А. Кузнецова   СНИЛС 112-233-445 95   паспорт 45 10 123456
"""


def test_personal_data_is_masked():
    masked, mapping = mask(DOC)
    assert leaked(masked) == []
    for secret in ("Петрова Мария Сергеевна", "500100732259", "40702810938000012345", "Иванов И.И.",
                   "+7 (916) 123-45-67", "buh@romashka.ru", "О.А. Кузнецова", "112-233-445 95", "45 10 123456"):
        assert secret not in masked
        assert secret in mapping.values()


def test_legal_entity_data_is_kept():
    masked, _ = mask(DOC)
    for kept in ("ООО «Ромашка»", "7707083893", "770701001", "044525225", "15 сентября 2026"):
        assert kept in masked


def test_same_value_same_placeholder_and_roundtrip():
    masked, mapping = mask("ИНН 500100732259 и ещё раз 500100732259")
    assert masked.count("[INN12_1]") == 2 and len(mapping) == 1
    answer = {"supplier_inn": "[INN12_1]", "supplier_name": "ИП [PERSON_1]", "lines": [{"name": "x [ACCOUNT_9]"}]}
    m2 = {**mapping, "[PERSON_1]": "Петрова Мария Сергеевна"}
    assert unmask(answer, m2) == {"supplier_inn": "500100732259", "supplier_name": "ИП Петрова Мария Сергеевна",
                                  "lines": [{"name": "x [ACCOUNT_9]"}]}   # unknown placeholder stays visible
