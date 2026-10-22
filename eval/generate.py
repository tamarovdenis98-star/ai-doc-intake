#!/usr/bin/env python3
"""Deterministic synthetic dataset: invoices, acts, UPD, contracts and 'other' documents rendered to PDF,
some turned into degraded scans, some with deliberate defects the validator must catch.

  python eval/generate.py [--out eval/dataset] [--seed 2026]
writes <out>/files/*.pdf|*.jpg and <out>/manifest.json (ground truth per document, schema-shaped).
Needs reportlab, pypdfium2, Pillow and a Cyrillic TTF font (DejaVuSans; in the extractor image).
"""
from __future__ import annotations

import argparse
import io
import json
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
TODAY = date(2026, 10, 22)   # fixed "today" so expected decisions (date range, VAT in force) are reproducible
W10, W11, W12 = [2, 4, 10, 3, 5, 9, 4, 6, 8], [7, 2, 4, 10, 3, 5, 9, 4, 6, 8], [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]

COMPANIES = ["ООО «Ромашка»", "ООО «ТехноСнаб»", "АО «СеверСталь Сервис»", "ООО «Вектор-Логистик»", "ООО «Альфа Консалт»",
             "ООО «БизнесСофт»", "ООО «Гранит»", "ООО «Медиа Плюс»", "АО «Энергосбыт Партнёр»", "ООО «КлинингПро»",
             "ООО «ОфисМаркет»", "ООО «ИнтерКом»", "ООО «Стройресурс»", "ООО «ДатаЦентр»"]
PEOPLE = [("Иванов", "Иван", "Иванович"), ("Петрова", "Мария", "Сергеевна"), ("Смирнов", "Алексей", "Петрович"),
          ("Кузнецова", "Ольга", "Андреевна"), ("Соколов", "Дмитрий", "Олегович"), ("Морозова", "Елена", "Викторовна")]
GOODS = [("Бумага офисная А4", "пач"), ("Картридж лазерный", "шт"), ("Монитор 27\"", "шт"), ("Кресло офисное", "шт"),
         ("Кабель UTP Cat6, 305 м", "бухта"), ("Тонер", "шт"), ("Стеллаж металлический", "шт"), ("Ноутбук 15\"", "шт")]
SERVICES = [("Техническое обслуживание серверов", "мес"), ("Уборка офисных помещений", "мес"), ("Консультационные услуги", "ч"),
            ("Доставка груза по Москве", "рейс"), ("Разработка интеграции с CRM", "ч"), ("Аренда офиса", "мес"),
            ("Сопровождение 1С", "ч"), ("Юридическая консультация", "ч")]
BANKS = [("ПАО Сбербанк", "044525225"), ("АО «Т-Банк»", "044525974"), ("АО «Альфа-Банк»", "044525593")]


def ctl(d, w):
    return sum(a * b for a, b in zip(w, d)) % 11 % 10


def inn10(rng):
    d = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(8)]
    return "".join(map(str, d + [ctl(d, W10)]))


def inn12(rng):
    d = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(9)]
    d.append(ctl(d, W11))
    d.append(ctl(d, W12))
    return "".join(map(str, d))


def money(x: float) -> str:
    whole, frac = f"{x:.2f}".split(".")
    return f"{int(whole):,}".replace(",", " ") + "," + frac


def ru_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year} г."


def font():
    for d in FONT_DIRS:
        for regular, bold in (("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"), ("arial.ttf", "arialbd.ttf")):
            if Path(d, regular).exists():
                pdfmetrics.registerFont(TTFont("F", str(Path(d, regular))))
                pdfmetrics.registerFont(TTFont("FB", str(Path(d, bold if Path(d, bold).exists() else regular))))
                return
    raise SystemExit("no Cyrillic TTF font found (install fonts-dejavu-core)")


def party(rng, individual=False):
    if individual:
        f, i, o = rng.choice(PEOPLE)
        return {"name": f"ИП {f} {i} {o}", "inn": inn12(rng), "kpp": None, "person": f"{f} {i[0]}.{o[0]}."}
    inn = inn10(rng)
    f, i, o = rng.choice(PEOPLE)
    return {"name": rng.choice(COMPANIES), "inn": inn, "kpp": inn[:4] + "01001", "person": f"{f} {i[0]}.{o[0]}."}


class Doc:
    def __init__(self):
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.y = A4[1] - 20 * mm

    def text(self, s, size=10, bold=False, x=18 * mm, gap=5.2 * mm):
        self.c.setFont("FB" if bold else "F", size)
        self.c.drawString(x, self.y, s)
        self.y -= gap

    def table(self, header, rows, widths):
        x0 = 18 * mm
        def row(cells, bold=False):
            x = x0
            self.c.setFont("FB" if bold else "F", 8.5)
            for cell, w in zip(cells, widths):
                self.c.rect(x, self.y - 1.8 * mm, w, 6 * mm)
                self.c.drawString(x + 1.2 * mm, self.y, str(cell))
                x += w
            self.y -= 6 * mm
        row(header, True)
        for r in rows:
            row(r)
        self.y -= 3 * mm

    def pdf(self) -> bytes:
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def lines_for(rng, kind, n, rate):
    pool = GOODS if kind in ("invoice", "upd") else SERVICES
    out = []
    for name, unit in rng.sample(pool, n):
        qty = rng.choice([1, 1, 2, 3, 5, 10, 12, 20]) if unit in ("шт", "пач") else rng.choice([1, 1, 2, 8, 16, 40])
        price = round(rng.uniform(150, 48000), 2)
        out.append({"name": name, "qty": qty, "unit": unit, "price": price, "amount": round(qty * price, 2)})
    base = round(sum(ln["amount"] for ln in out), 2)
    vat = round(base * rate / 100, 2) if rate else 0.0
    return out, base, vat, round(base + vat, 2)


def render(kind, t, sup, buy, extra):
    d = Doc()
    num, dt = t["number"], date.fromisoformat(t["date"])
    rate_txt = f"НДС {t['vat_rate']}%" if t.get("vat_rate") else "Без НДС"
    if kind == "invoice":
        d.text(f"{extra['bank'][0]}    БИК {t['supplier_bik']}", 9)
        d.text(f"Сч. № {t['supplier_account']}    Получатель: {sup['name']}", 9)
        d.y -= 3 * mm
        d.text(f"Счёт на оплату № {num} от {ru_date(dt)}", 14, True, gap=8 * mm)
    elif kind == "act":
        d.text(f"Акт № {num} от {ru_date(dt)}", 14, True)
        d.text("об оказании услуг (выполнении работ)", 11, gap=8 * mm)
    else:
        d.text("Универсальный передаточный документ", 13, True)
        d.text(f"Статус: {t['upd_status']}    Счёт-фактура № {num} от {ru_date(dt)}", 10, gap=8 * mm)
    role_s, role_b = {"invoice": ("Поставщик", "Покупатель"), "act": ("Исполнитель", "Заказчик"), "upd": ("Продавец", "Покупатель")}[kind]
    kpp_s = f", КПП {sup['kpp']}" if sup["kpp"] else ""
    kpp_b = f", КПП {buy['kpp']}" if buy["kpp"] else ""
    d.text(f"{role_s}: {sup['name']}, ИНН {t['supplier_inn']}{kpp_s}", 10)
    d.text(f"{role_b}: {buy['name']}, ИНН {t['buyer_inn']}{kpp_b}", 10, gap=8 * mm)
    rows = [[i + 1, ln["name"], ln["qty"], ln["unit"], money(ln["price"]), money(ln["amount"])] for i, ln in enumerate(t["lines"])]
    d.table(["№", "Наименование", "Кол-во", "Ед.", "Цена", "Сумма"], rows, [8 * mm, 78 * mm, 16 * mm, 14 * mm, 28 * mm, 30 * mm])
    d.text(f"Итого: {money(t['total_without_vat'])}", 10, True, x=120 * mm)
    d.text(f"{rate_txt}: {money(t['vat_amount'])}" if t.get("vat_rate") else "Без НДС", 10, True, x=120 * mm)
    d.text(f"Всего к оплате: {money(t['total'])}", 10, True, x=120 * mm, gap=10 * mm)
    if kind == "act":
        d.text("Вышеперечисленные услуги выполнены полностью и в срок. Заказчик претензий не имеет.", 9, gap=10 * mm)
    d.text(f"Руководитель ____________ {sup['person']}        Тел. {extra['phone']}", 9)
    d.text(f"Главный бухгалтер ____________ {extra['accountant']}        {extra['email']}", 9)
    return d.pdf()


def render_contract(t, sup, buy, extra):
    d = Doc()
    d.text(f"ДОГОВОР № {t['number']}", 14, True)
    d.text(f"оказания услуг", 11)
    d.text(f"г. Москва                                                                      {ru_date(date.fromisoformat(t['date']))}", 10, gap=8 * mm)
    d.text(f"{sup['name']} (ИНН {t['supplier_inn']}), именуемое в дальнейшем «Исполнитель», в лице", 10)
    d.text(f"генерального директора {extra['director']}, с одной стороны, и {buy['name']}", 10)
    d.text(f"(ИНН {t['buyer_inn']}), именуемое в дальнейшем «Заказчик», заключили настоящий договор:", 10, gap=8 * mm)
    d.text("1. ПРЕДМЕТ ДОГОВОРА", 11, True)
    d.text(f"1.1. Исполнитель обязуется оказать услуги: {t['subject']}.", 10, gap=7 * mm)
    d.text("2. ЦЕНА И ПОРЯДОК РАСЧЁТОВ", 11, True)
    d.text(f"2.1. Цена договора составляет {money(t['total'])} руб., в т.ч. НДС 22%.", 10, gap=7 * mm)
    d.text("3. СРОК ДЕЙСТВИЯ", 11, True)
    d.text(f"3.1. Договор действует до {ru_date(date.fromisoformat(t['valid_until']))}", 10, gap=10 * mm)
    d.text(f"Исполнитель ____________ {sup['person']}            Заказчик ____________ {buy['person']}", 9)
    return d.pdf()


def render_other(rng, sup):
    d = Doc()
    d.text(sup["name"], 12, True)
    d.text("Коммерческое предложение", 14, True, gap=8 * mm)
    for s in ["Уважаемые коллеги!", "Предлагаем рассмотреть поставку офисной техники на выгодных условиях.",
              f"Скидка {rng.choice([5, 7, 10])}% при заказе до конца месяца. Доставка бесплатно.",
              "Прайс-лист направим по запросу. Будем рады сотрудничеству!", "",
              f"С уважением, менеджер {rng.choice(PEOPLE)[0]} {rng.choice('АБВГДЕ')}.{rng.choice('АБВГДЕ')}.",
              f"Тел. +7 (495) {rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(10, 99)}"]:
        d.text(s, 10)
    return d.pdf()


def to_scan(pdf: bytes, rng) -> bytes:
    import pypdfium2 as pdfium
    page = pdfium.PdfDocument(pdf)[0]
    img = page.render(scale=rng.choice([150, 170, 200]) / 72).to_pil().convert("L")
    img = img.rotate(rng.uniform(-1.6, 1.6), expand=True, fillcolor=255, resample=Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(rng.choice([0.4, 0.7, 1.0])))
    noise = Image.effect_noise(img.size, rng.choice([10, 18, 26]))
    img = Image.blend(img, noise, 0.08)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=rng.choice([40, 55, 70]))
    return out.getvalue()


PLAN = (["invoice"] * 16) + (["act"] * 12) + (["upd"] * 12) + (["contract"] * 8) + (["other"] * 8)
DEFECTS = {3: "bad_total", 7: "bad_vat", 11: "bad_inn", 18: "stale_vat_rate", 22: "future_date",
           29: "bad_line_math", 33: "duplicate_of_1", 40: "bad_total"}
SCANS = {2, 5, 9, 13, 17, 20, 24, 27, 31, 33, 35, 38, 42, 45, 50, 53}   # 33: the duplicate is a scan of invoice 1 (different bytes)


def build(out: Path, seed: int):
    rng = random.Random(seed)
    font()
    files = out / "files"
    files.mkdir(parents=True, exist_ok=True)
    buyers = [party(random.Random(seed + 1)), party(random.Random(seed + 2))]
    manifest, first_invoice = [], None
    for i, kind in enumerate(PLAN, start=1):
        sup = party(rng, individual=(kind in ("invoice", "act") and rng.random() < 0.2))
        buy = rng.choice(buyers)
        dt = TODAY - timedelta(days=rng.randint(3, 420))
        defect = DEFECTS.get(i)
        if defect == "future_date":
            dt = TODAY + timedelta(days=40)
        rate = 22 if dt >= date(2026, 1, 1) else 20
        if sup["kpp"] is None and rng.random() < 0.7:
            rate = None                                  # ИП on the simplified system: no VAT
        if defect == "stale_vat_rate":
            dt, rate = date(2026, 3, 12), 20
        f, im, o = rng.choice(PEOPLE)
        extra = {"bank": rng.choice(BANKS), "phone": f"+7 (9{rng.randint(10, 99)}) {rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(10, 99)}",
                 "email": f"buh{rng.randint(1, 99)}@{rng.choice(['romashka', 'vector', 'alfa', 'granit'])}.ru",
                 "accountant": f"{f} {im[0]}.{o[0]}.", "director": f"{f}а {im}а {o}а" if not f.endswith("а") else f"{f} {im} {o}"}
        number = f"{rng.choice(['', 'А-', 'УТ-', '00'])}{rng.randint(1, 2400)}"
        t = {"number": number, "date": dt.isoformat(), "supplier_name": sup["name"], "supplier_inn": sup["inn"],
             "supplier_kpp": sup["kpp"], "buyer_name": buy["name"], "buyer_inn": buy["inn"], "buyer_kpp": buy["kpp"]}
        if kind in ("invoice", "act", "upd"):
            lines, base, vat, total = lines_for(rng, kind, rng.randint(1, 5), rate)
            t.update({"lines": lines, "total_without_vat": base, "vat_rate": rate, "vat_amount": vat, "total": total})
            if kind == "invoice":
                t.update({"supplier_account": "40702810" + "".join(str(rng.randint(0, 9)) for _ in range(12)), "supplier_bik": extra["bank"][1]})
            if kind == "upd":
                t["upd_status"] = 1 if rate else 2
            if defect == "bad_total":
                t["total"] = round(total + rng.choice([100, 1000, 0.5]), 2)
            if defect == "bad_vat":
                t["vat_amount"] = round(vat * 1.1, 2)
                t["total"] = round(base + t["vat_amount"], 2)
            if defect == "bad_line_math":
                t["lines"][0]["amount"] = round(t["lines"][0]["amount"] + 10, 2)
                t["total_without_vat"] = round(sum(ln["amount"] for ln in t["lines"]), 2)
                t["vat_amount"] = round(t["total_without_vat"] * (rate or 0) / 100, 2)
                t["total"] = round(t["total_without_vat"] + t["vat_amount"], 2)
            if defect == "bad_inn":
                t["supplier_inn"] = t["supplier_inn"][:-1] + str((int(t["supplier_inn"][-1]) + 3) % 10)
            if kind == "invoice" and first_invoice is None and not defect:
                first_invoice = (dict(t), sup, buy, extra)
            if defect == "duplicate_of_1" and first_invoice:
                t, sup, buy, extra = dict(first_invoice[0]), *first_invoice[1:]
                kind = "invoice"
            pdf = render(kind, t, sup, buy, extra)
        elif kind == "contract":
            t.update({"subject": rng.choice(SERVICES)[0].lower(), "total": round(rng.uniform(50000, 900000), 2),
                      "valid_until": (dt + timedelta(days=365)).isoformat()})
            pdf = render_contract(t, sup, buy, extra)
        else:
            t = {}
            pdf = render_other(rng, sup)
        scan = i in SCANS
        data, ext, mime = (to_scan(pdf, rng), "jpg", "image/jpeg") if scan else (pdf, "pdf", "application/pdf")
        name = f"{i:03d}_{kind}{'_scan' if scan else ''}{'_' + defect if defect else ''}.{ext}"
        (files / name).write_bytes(data)
        manifest.append({"id": i, "file": f"files/{name}", "mime": mime, "doc_type": kind, "scan": scan,
                         "defect": defect, "expected_decision": "review" if (defect or kind == "other") else "auto",
                         "expected": t})
    (out / "manifest.json").write_text(json.dumps({"seed": seed, "today": TODAY.isoformat(), "documents": manifest},
                                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(manifest)} documents -> {out} ({sum(m['scan'] for m in manifest)} scans, {sum(bool(m['defect']) for m in manifest)} with defects)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "dataset"))
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    build(Path(a.out), a.seed)
