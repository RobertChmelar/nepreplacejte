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
    """Seznam kontrol: (soubor, popis, hodnota, jednotka, tolerance)."""
    ele = backtest(data, False, METHODOLOGY_EURCZK)
    gas = backtest(data, True, METHODOLOGY_EURCZK)
    ele_fair = fair_range(data["ele"]["cal_now"], False)
    gas_fair = fair_range(data["gas"]["cal_now"], True)

    r = round
    return [
        # elektřina — tabulka strategií / headline čísla
        ("blog-fix-nebo-spot.html", "ele fixQ4 Ø", r(ele["avg"]["fixQ4"]), "Kč/MWh", 1),
        ("blog-fix-nebo-spot.html", "ele spot Ø", r(ele["avg"]["spot"]), "Kč/MWh", 1),
        ("blog-fix-nebo-spot.html", "ele spot 2022", r(ele["spot"][0]), "Kč/MWh", 1),
        ("blog-kdy-fixovat-elektrinu.html", "ele fixQ4−tranše",
         r(ele["avg"]["fixQ4"] - ele["avg"]["transe"]), "Kč/MWh", 1),
        ("blog-kdy-fixovat-elektrinu.html", "ele férové horní", ele_fair[1], "Kč/MWh", 1),
        ("blog-cena-elektriny-pro-firmy.html", "ele férové horní", ele_fair[1], "Kč/MWh", 1),
        # plyn — tabulka strategií / headline čísla
        ("blog-cena-plynu-pro-firmy.html", "plyn fixQ4 Ø", r(gas["avg"]["fixQ4"]), "Kč/MWh", 1),
        ("blog-cena-plynu-pro-firmy.html", "plyn tranše Ø", r(gas["avg"]["transe"]), "Kč/MWh", 1),
        ("blog-cena-plynu-pro-firmy.html", "plyn spot Ø", r(gas["avg"]["spot"]), "Kč/MWh", 1),
        ("blog-cena-plynu-pro-firmy.html", "plyn fixQ4−tranše",
         r(gas["avg"]["fixQ4"] - gas["avg"]["transe"]), "Kč/MWh", 1),
        # férová / prose zaokrouhlená na desítky → tolerance 10
        ("blog-cena-plynu-pro-firmy.html", "plyn férové horní (~1290)", gas_fair[1], "Kč/MWh", 10),
        ("blog-cena-plynu-pro-firmy.html", "plyn spot 2022 (~3180)", r(gas["spot"][0]), "Kč/MWh", 10),
    ]


def main():
    data = load_data()
    checks = build_checks(data)
    cache = {}
    failures = []

    for fname, label, value, unit, tol in checks:
        path = os.path.join(ROOT, fname)
        if path not in cache:
            try:
                with open(path, encoding="utf-8") as f:
                    cache[path] = f.read()
            except FileNotFoundError:
                failures.append((fname, label, value, unit, "SOUBOR CHYBÍ"))
                continue
        present = numbers_with_unit(cache[path], unit)
        if not any(abs(n - value) <= tol for n in present):
            near = sorted(present, key=lambda n: abs(n - value))[:3]
            failures.append((fname, label, value, unit,
                             f"nenalezeno; nejbližší v souboru: {near}"))

    if failures:
        print("NESOULAD — články k aktualizaci:\n")
        for fname, label, value, unit, note in failures:
            print(f"  • {fname}: {label} → čekáno ~{value} {unit} ({note})")
        print(f"\n{len(failures)} míst k revizi. Zkontroluj, zda se změnila "
              "historická data / cal_now v data.json a přepiš prose v článku.")
        return 1

    print(f"OK — {len(checks)} klíčových čísel v článcích odpovídá výpočtu "
          f"(kurz {METHODOLOGY_EURCZK}, cal_now ele={data['ele']['cal_now']}, "
          f"gas={data['gas']['cal_now']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
