#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
energy_model.py — Python replika výpočtu backtestu z assets/app.js
==================================================================

Jediné místo pravdy pro Python stranu (testy + kontrola blogu). Marže,
přirážky férového rozmezí a metodický kurz MUSÍ odpovídat CONFIG v app.js.

Důležité rozlišení dvou kurzů:
  · METHODOLOGY_EURCZK (24.20) — pevný kurz, na kterém jsou postavená
    FINÁLNÍ historická čísla v článcích a vestavěná data. Testy i kontrola
    blogu počítají backtest právě tímto kurzem, aby denní pohyb živého
    kurzu (data.json) blogy neshazoval.
  · živý eurczk z data/data.json — pohání jen živý ticker a férové rozmezí
    pro NOVÝ kontrakt na webu.
"""

# --- parametry (shodné s CONFIG v app.js) ---
METHODOLOGY_EURCZK = 24.2
MARGIN = {"ele_fix": 350, "ele_spot": 250, "gas_fix": 300, "gas_spot": 200}
FAIR_OFFSET = {"ele": [250, 550], "gas": [150, 350]}
YEARS = [2022, 2023, 2024, 2025]

# --- vestavěná data (shodná s výchozími hodnotami v app.js) ---
BUILTIN = {
    "eurczk": 24.2,
    "ele": {
        "spot_y": {2021: 2570, 2022: 6080, 2023: 2420, 2024: 2140, 2025: 2400},
        "cal": {
            2022: [55, 62, 83, 128],
            2023: [125, 185, 360, 255],
            2024: [142, 118, 122, 112],
            2025: [76, 81, 92, 96],
            2026: [95, 88, 84, 88],
        },
        "cal_now": 100,
    },
    "gas": {
        "spot_y_eur": {2021: 47, 2022: 123, 2023: 41, 2024: 34.5, 2025: 35},
        "cal": {
            2022: [17, 21, 33, 55],
            2023: [55, 85, 180, 110],
            2024: [55, 48, 52, 46],
            2025: [30, 34, 37, 40],
        },
        "cal_now": 39,
    },
}


def avg(xs):
    return sum(xs) / len(xs)


def _int_keyed(d):
    """Sjednotí klíče roků na int (JSON je má jako string)."""
    return {int(k): v for k, v in d.items()}


def backtest(data, is_gas, eurczk=METHODOLOGY_EURCZK):
    """
    Přesná replika funkce backtest() z app.js.
    Vrací dict: {years, fixQ4:[...], transe:[...], spot:[...], mix:[...],
                 avg:{fixQ4,transe,spot,mix}}  (Kč/MWh vč. marže).
    """
    if is_gas:
        spot_y = _int_keyed(data["gas"]["spot_y_eur"])
        cal = _int_keyed(data["gas"]["cal"])
        m_fix, m_spot = MARGIN["gas_fix"], MARGIN["gas_spot"]
    else:
        spot_y = _int_keyed(data["ele"]["spot_y"])
        cal = _int_keyed(data["ele"]["cal"])
        m_fix, m_spot = MARGIN["ele_fix"], MARGIN["ele_spot"]

    out = {"years": list(YEARS), "fixQ4": [], "transe": [], "spot": [], "mix": []}
    for y in YEARS:
        if is_gas:
            spot_avg = spot_y[y] * eurczk + m_spot
            fixq4 = cal[y][3] * eurczk + m_fix
            transe = avg(cal[y]) * eurczk + m_fix
        else:
            spot_avg = spot_y[y] + m_spot          # ověřený Ø OTE v Kč/MWh
            fixq4 = cal[y][3] * eurczk + m_fix
            transe = avg(cal[y]) * eurczk + m_fix
        out["fixQ4"].append(fixq4)
        out["transe"].append(transe)
        out["spot"].append(spot_avg)
        out["mix"].append((fixq4 + spot_avg) / 2)

    out["avg"] = {k: avg(out[k]) for k in ("fixQ4", "transe", "spot", "mix")}
    return out


def fair_range(cal_now_eur, is_gas, eurczk=METHODOLOGY_EURCZK):
    """Férové rozmezí Kč/MWh = cal_now × kurz + přirážky (viz app.js)."""
    off = FAIR_OFFSET["gas" if is_gas else "ele"]
    return [round(cal_now_eur * eurczk + off[0]), round(cal_now_eur * eurczk + off[1])]
