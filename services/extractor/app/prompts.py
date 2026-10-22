"""Prompts. The document goes after the <<<DOCUMENT>>> marker; the rules provider reads only that part."""
import json

CLASSIFY_SYSTEM = """Ты классифицируешь входящие бухгалтерские документы российской компании.
Типы:
- invoice  — счёт на оплату (есть реквизиты для оплаты, «Счёт №», «Всего к оплате»)
- act      — акт выполненных работ / оказанных услуг (подписи исполнителя и заказчика)
- upd      — универсальный передаточный документ (УПД, «Статус 1/2», счёт-фактура + передаточный)
- contract — договор (предмет, права и обязанности сторон)
- other    — всё остальное (письмо, коммерческое предложение, прайс, неразборчивый текст)
Ответь только JSON-объектом: {"doc_type": "...", "confidence": число 0..1, "reason": "коротко почему"}.
confidence ниже 0.8, если текст неполный, повреждён или признаки противоречат друг другу."""

EXTRACT_SYSTEM = """Ты извлекаешь реквизиты из бухгалтерского документа в строгий JSON по схеме.
Правила:
- Только данные из текста. Если поля нет или оно не читается — null. Ничего не придумывай и не пересчитывай.
- Даты — YYYY-MM-DD. Суммы — числа с точкой, без пробелов и знака валюты (1 234,50 → 1234.5).
- ИНН/КПП/БИК/счёт — только цифры (КПП может содержать латинские буквы в 5–6 знаках).
- Поставщик (supplier) — продавец/исполнитель/поставщик; покупатель (buyer) — покупатель/заказчик/плательщик.
- vat_rate — ставка НДС в процентах числом (22, 20, 10, 0); «без НДС» → null и vat_amount 0.
- lines — позиции таблицы: name, qty, unit, price (без НДС), amount (без НДС). Если в таблице суммы с НДС — переведи их по ставке документа только если это явно указано, иначе перепиши как есть.
- Строки вида [PERSON_1], [ACCOUNT_1], [INN12_1], [PHONE_1] — это скрытые персональные данные. Копируй их в ответ точно как есть, не меняя.
Ответь только JSON-объектом по схеме:
"""


def classify_messages(text: str) -> tuple[str, str]:
    return CLASSIFY_SYSTEM, "Определи тип документа.\n<<<DOCUMENT>>>\n" + text


def extract_messages(doc_type: str, schema: dict, text: str) -> tuple[str, str]:
    return (EXTRACT_SYSTEM + json.dumps(schema, ensure_ascii=False),
            f"Тип документа: {doc_type}. Извлеки поля.\n<<<DOCUMENT>>>\n" + text)


def repair_messages(doc_type: str, schema: dict, text: str, bad: dict, errors: list[str]) -> tuple[str, str]:
    system, user = extract_messages(doc_type, schema, text)
    return system, (user + "\n\nПредыдущий ответ не прошёл проверку схемы:\n" + "\n".join(errors[:10])
                    + "\nПредыдущий ответ:\n" + json.dumps(bad, ensure_ascii=False)[:3000] + "\nВерни исправленный JSON.")
