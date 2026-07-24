#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_blog_consistency.py — hlídač konzistence článků vůči výpočtu
==================================================================

Po každé změně data/data.json ověří, že klíčová ODVOZENÁ čísla citovaná
v článcích blog-*.html stále odpovídají výpočtu. Když ne, vypíše seznam
konkrétních míst (soubor + veličina + očekávaná hodnota) k aktualizaci.

Backtestové (historické) hodnoty se počítají PEVNÝM metodickým kurzem
24,20 (viz energy_model), takže denní pohyb živého kurzu články neshodí.
Férová rozmezí reagují na cal_now z data.json — když se změní settlement,
kontrola upozorní, že prose v článcích je potřeba přepsat.

    python3 tests/check_blog_consistency.py     # exit 1 při nesouladu
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from energy_model import (BUILTIN, backtest, fair_range,  # noqa: E402
                          METHODOLOGY_EURCZK)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_JSON = os.path.join(ROOT, "data", "data.json")

# mezery, které se v HTML používají jako oddělovač tisíců
_SPACES = [" ", " ", " ", " "]


def load_data():
    if os.path.exists(DATA_JSON):
        try:
            with open(DATA_JSON, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] data.json nečitelné ({e}); použita vestavěná data")
    return BUILTIN


def numbers_with_unit(text, unit):
    """Vrátí množinu celých čísel uvedených před jednotkou `unit`."""
    for s in _SPACES:
        text = text.replace(s, " ")
    out = set()
    for m in re.finditer(r"(\d(?:[ \d]*\d)?)\s*" + re.escape(unit), text):
        try:
            out.add(int(m.group(1).replace(" ", "")))
        except ValueError:
            pass
    return out


def build_checks(data):
    """
    Seznam kontrol: (soubor, popis, hodnota, jednotka, tolerance, hard).

    hard=True  — HISTORICKÁ backtestová čísla (fixní kurz 24,20 + neměnná
                 historická CAL). Nikdy nedriftují → nesoulad = skutečná
                 chyba, blokuje (exit 1).
    hard=False — FÉROVÁ ROZMEZÍ vázaná na živý cal_now. Hýbou se s trhem
                 (denně), takže by z principu neměly shazovat build. Jen
                 varují („prose je zastaralá, zvaž refresh").
    """
    ele = backtest(data, False, METHODOLOGY_EURCZK)
    gas = backtest(data, True, METHODOLOGY_EURCZK)
    ele_fair = fair_range(data["ele"]["cal_now"], False)
    gas_fair = fair_range(data["gas"]["cal_now"], True)

    r = round
    return [
        # --- TVRDÉ: tabulka strategií / headline (stabilní, blokují) ---
        ("blog-fix-nebo-spot.html", "ele fixQ4 Ø", r(ele["avg"]["fixQ4"]), "Kč/MWh", 1, True),
        ("blog-fix-nebo-spot.html", "ele spot Ø", r(ele["avg"]["spot"]), "Kč/MWh", 1, True),
        ("blog-fix-nebo-spot.html", "ele spot 2022", r(ele["spot"][0]), "Kč/MWh", 1, True),
        ("blog-kdy-fixovat-elektrinu.html", "ele fixQ4−tranše",
         r(ele["avg"]["fixQ4"] - ele["avg"]["transe"]), "Kč/MWh", 1, True),
        ("blog-cena-plynu-pro-firmy.html", "plyn fixQ4 Ø", r(gas["avg"]["fixQ4"]), "Kč/MWh", 1, True),
        ("blog-cena-plynu-pro-firmy.html", "plyn tranše Ø", r(gas["avg"]["transe"]), "Kč/MWh", 1, True),
        ("blog-cena-plynu-pro-firmy.html", "plyn spot Ø", r(gas["avg"]["spot"]), "Kč/MWh", 1, True),
        ("blog-cena-plynu-pro-firmy.html", "plyn fixQ4−tranše",
         r(gas["avg"]["fixQ4"] - gas["avg"]["transe"]), "Kč/MWh", 1, True),
        ("blog-cena-plynu-pro-firmy.html", "plyn spot 2022", r(gas["spot"][0]), "Kč/MWh", 10, True),
        # --- MĚKKÉ: férová rozmezí vázaná na cal_now (driftují, jen varují) ---
        ("blog-kdy-fixovat-elektrinu.html", "ele férové horní", ele_fair[1], "Kč/MWh", 40, False),
        ("blog-cena-elektriny-pro-firmy.html", "ele férové horní", ele_fair[1], "Kč/MWh", 40, False),
        ("blog-cena-plynu-pro-firmy.html", "plyn férové horní", gas_fair[1], "Kč/MWh", 40, False),
    ]


def main():
    data = load_data()
    checks = build_checks(data)
    cache = {}
    hard_fail, soft_fail = [], []

    for fname, label, value, unit, tol, hard in checks:
        path = os.path.join(ROOT, fname)
        if path not in cache:
            try:
                with open(path, encoding="utf-8") as f:
                    cache[path] = f.read()
            except FileNotFoundError:
                (hard_fail if hard else soft_fail).append(
                    (fname, label, value, unit, "SOUBOR CHYBÍ"))
                continue
        present = numbers_with_unit(cache[path], unit)
        if not any(abs(n - value) <= tol for n in present):
            near = sorted(present, key=lambda n: abs(n - value))[:3]
            (hard_fail if hard else soft_fail).append(
                (fname, label, value, unit, f"nenalezeno; nejbližší: {near}"))

    if soft_fail:
        print("UPOZORNĚNÍ — férová rozmezí v článcích zastarala (trh se pohnul, "
              "neblokuje):")
        for fname, label, value, unit, note in soft_fail:
            print(f"  ~ {fname}: {label} → nyní ~{value} {unit} ({note})")
        print("  → až budeš mít chvíli, přepiš „cca X–Y Kč/MWh“ v perexu/tabulce.\n")

    if hard_fail:
        print("CHYBA — historická čísla nesedí (musí se opravit):")
        for fname, label, value, unit, note in hard_fail:
            print(f"  • {fname}: {label} → čekáno ~{value} {unit} ({note})")
        return 1

    print(f"OK — historická čísla v článcích odpovídají výpočtu "
          f"(kurz {METHODOLOGY_EURCZK}, cal_now ele={data['ele']['cal_now']}, "
          f"gas={data['gas']['cal_now']}"
          + (f"; {len(soft_fail)} férových rozmezí k refreshi)" if soft_fail else ")"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
