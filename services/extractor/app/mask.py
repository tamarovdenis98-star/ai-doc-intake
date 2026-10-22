"""Reversible masking of personal data before text leaves for an external LLM.

Personal data (people, phones, e-mails, personal INN, passports, SNILS, cards) is replaced with placeholders
such as [PERSON_1]; the model is told to copy placeholders as they are, and the answer is unmasked locally.
Bank accounts are masked too: the model never sees them, yet the extracted field gets the real value back.
Legal-entity data (company names, 10-digit INN, KPP, BIK, amounts, dates) stays: it is not personal data
and is exactly what has to be extracted.
"""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")),
    ("SNILS", re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}[ -]\d{2}(?!\d)")),
    ("CARD", re.compile(r"(?<!\d)(?:\d{4}[ -]){3}\d{4}(?!\d)")),
    ("ACCOUNT", re.compile(r"(?<!\d)\d{20}(?!\d)")),
    ("PASSPORT", re.compile(r"(?<!\d)\d{2}\s?\d{2}\s\d{6}(?!\d)")),          # "45 10 123456" / "4510 123456"
    ("INN12", re.compile(r"(?<!\d)\d{12}(?!\d)")),                         # individual (ИП / physical person)
    ("PERSON", re.compile(r"\b[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:вич|вна|ич|чна|кызы|оглы)\b")),
    ("PERSON", re.compile(r"\b[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.")),   # Иванов И.И.
    ("PERSON", re.compile(r"\b[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\b")),   # И.И. Иванов
]
PLACEHOLDER = re.compile(r"\[(?:EMAIL|PHONE|SNILS|CARD|ACCOUNT|PASSPORT|INN12|PERSON)_\d+\]")


def mask(text: str) -> tuple[str, dict[str, str]]:
    """Returns masked text and {placeholder: original}. The same value always gets the same placeholder."""
    mapping: dict[str, str] = {}
    reverse: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}

    for kind, rx in PATTERNS:
        def repl(m: re.Match) -> str:
            value = m.group(0)
            key = (kind, value)
            if key not in reverse:
                counters[kind] = counters.get(kind, 0) + 1
                ph = f"[{kind}_{counters[kind]}]"
                reverse[key] = ph
                mapping[ph] = value
            return reverse[key]
        text = rx.sub(repl, text)
    return text, mapping


def unmask(obj, mapping: dict[str, str]):
    """Puts the original values back into any strings of a (nested) JSON value."""
    if isinstance(obj, str):
        return PLACEHOLDER.sub(lambda m: mapping.get(m.group(0), m.group(0)), obj)
    if isinstance(obj, list):
        return [unmask(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {k: unmask(v, mapping) for k, v in obj.items()}
    return obj


def leaked(text: str) -> list[str]:
    """Personal data patterns still present in text that is about to leave (a guard used in tests and logs)."""
    return [m.group(0) for kind, rx in PATTERNS for m in rx.finditer(text)]
