#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_market_section.py — měsíční „živá" sekce trhu do pilířových článků
=========================================================================

Deterministicky (bez LLM) vloží / aktualizuje v pilířových stránkách
`cena-elektriny-pro-firmy` a `cena-plynu-pro-firmy` blok:

    <!-- MARKET-UPDATE-START --> … <!-- MARKET-UPDATE-END -->

s aktuálním férovým rozmezím + FAKTICKÝM měsíčním pohybem CAL (z
data/data.json a data/cal_history.csv) + komentářem, co to znamená pro
firmu, která teď fixuje. Bumpuje `dateModified` v JSON-LD (obsah se reálně
mění → legitimní freshness, ne fake). Historická backtestová čísla ani
zbytek článku se nedotýká. Idempotentní — druhý běh dá stejný výsledek.

Spuštění:  python3 pipeline/update_market_section.py
"""
import csv
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "tests"))
import json  # noqa: E402
from energy_model import fair_range  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_JSON = os.path.join(ROOT, "data", "data.json")
CAL_HISTORY = os.path.join(ROOT, "data", "cal_history.csv")

MARK_START = "<!-- MARKET-UPDATE-START -->"
MARK_END = "<!-- MARKET-UPDATE-END -->"
ANCHOR_RE = re.compile(r'(<div class="meta mono">.*?</div>)', re.S)

CZ_MONTHS = ["", "leden", "únor", "březen", "duben", "květen", "červen",
             "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]

PAGES = {
    "ele": {"file": "blog-cena-elektriny-pro-firmy.html",
            "label": "silové elektřiny", "unit_eur_note": "roční kontrakt CAL27"},
    "gas": {"file": "blog-cena-plynu-pro-firmy.html",
            "label": "plynu (komodity)", "unit_eur_note": "roční kontrakt na 2027"},
}


def fmt(n):
    return f"{int(round(n)):,}".replace(",", " ")


def load_data():
    with open(DATA_JSON, encoding="utf-8") as f:
        return json.load(f)


def month_change(commodity):
    """(now_eur, change_pct, window_days) z cal_history; None když málo dat."""
    if not os.path.exists(CAL_HISTORY):
        return None
    rows = []
    with open(CAL_HISTORY, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("commodity") == commodity and r.get("price_eur"):
                try:
                    rows.append((dt.date.fromisoformat(r["date"]),
                                 float(r["price_eur"])))
                except ValueError:
                    continue
    if len(rows) < 2:
        return None
    rows.sort()
    latest_d, latest_v = rows[-1]
    target = latest_d - dt.timedelta(days=30)
    base_d, base_v = min(rows, key=lambda rv: abs((rv[0] - target).days))
    window = (latest_d - base_d).days
    if window < 5 or base_v == 0:
        return (latest_v, None, window)
    return (latest_v, (latest_v - base_v) / base_v * 100.0, window)


def commentary(change_pct, window_days):
    """Faktický komentář keyed na pohyb — žádné vymyšlené příčiny."""
    if change_pct is None:
        return ("Řada dat se teprve buduje; sledujeme denní settlement "
                "ročního kontraktu.")
    ap = abs(change_pct)
    win = f"za posledních ~{window_days} dní"
    if change_pct >= 5:
        return (f"Roční kontrakt {win} vzrostl o {ap:.0f} % — kdo fixuje teď, "
                "platí víc než před měsícem. O důvod víc rozložit nákup do "
                "tranší než podepsat celý objem naráz.")
    if change_pct <= -5:
        return (f"Roční kontrakt {win} klesl o {ap:.0f} % — otevřelo se "
                "levnější okno pro fixaci. I tak nakupujte raději po tranších, "
                "ať netrefujete jeden den.")
    return (f"Roční kontrakt je {win} zhruba stabilní ({change_pct:+.0f} %) — "
            "klidnější období pro rozhodování. Hlídejte si výpovědní lhůty a "
            "nakupujte v tranších.")


def build_block(commodity, data, today):
    cfg = PAGES[commodity]
    is_gas = commodity == "gas"
    cal_now = data["gas" if is_gas else "ele"]["cal_now"]
    lo, hi = fair_range(cal_now, is_gas)
    mc = month_change(commodity)
    now_eur = mc[0] if mc else cal_now
    change_pct = mc[1] if mc else None
    window = mc[2] if mc else 0
    m = today.month
    heading = f"Aktuální stav trhu — {CZ_MONTHS[m]} {today.year}"
    datestr = f"{today.day}. {today.month}. {today.year}"

    inner = (
        f'<div style="border:1.5px solid #1B232E;background:#FFF7DC;'
        f'padding:18px 22px;margin:24px 0">'
        f'<h2 style="margin-top:0">{heading}</h2>'
        f'<p><strong>Férové rozmezí fixní ceny {cfg["label"]} na rok 2027 je '
        f'nyní cca {fmt(lo)}–{fmt(hi)} Kč/MWh</strong> bez DPH '
        f'({cfg["unit_eur_note"]} kolem {now_eur:.0f} EUR/MWh, kurz 24,20 '
        f'a obvyklá marže dodavatele). {commentary(change_pct, window)} '
        f'<a href="index.html#analyzer">Férové rozmezí pro váš objem '
        f'spočítá kalkulačka →</a></p>'
        f'<p class="mono" style="font-size:12px;color:#5B6470;margin-bottom:0">'
        f'Aktualizováno {datestr} · zdroj: PXE/EEX (CAL), OTE (spot). '
        f'Historické backtestové hodnoty níže se nemění.</p>'
        f'</div>'
    )
    return f"{MARK_START}\n{inner}\n{MARK_END}"


def upsert(html, block):
    if MARK_START in html and MARK_END in html:
        return re.sub(re.escape(MARK_START) + r".*?" + re.escape(MARK_END),
                      lambda _: block, html, flags=re.S)
    m = ANCHOR_RE.search(html)
    if not m:
        raise RuntimeError("kotva <div class=meta mono> nenalezena")
    return html[:m.end()] + "\n" + block + html[m.end():]


def set_date_modified(html, today):
    iso = today.isoformat()
    if '"dateModified"' in html:  # aktualizuj hodnotu
        return re.sub(r'"dateModified":\s*"[^"]*"',
                      f'"dateModified": "{iso}"', html, count=1)
    # vlož před datePublished (jediný výskyt, v Article JSON-LD)
    return re.sub(r'("datePublished":\s*"[^"]*")',
                  f'"dateModified": "{iso}", \\1', html, count=1)


def main():
    today = dt.date.today()
    data = load_data()
    changed = []
    for commodity, cfg in PAGES.items():
        path = os.path.join(ROOT, cfg["file"])
        html = open(path, encoding="utf-8").read()
        new = set_date_modified(upsert(html, build_block(commodity, data, today)),
                                today)
        if new != html:
            open(path, "w", encoding="utf-8").write(new)
            changed.append(cfg["file"])
    if changed:
        print("Aktualizováno:", ", ".join(changed))
    else:
        print("Beze změny (obsah shodný).")


if __name__ == "__main__":
    main()
