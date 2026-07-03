#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_backtest.py — ověření Python repliky backtestu proti ručním výpočtům
=========================================================================

Počítá se nad VESTAVĚNÝMI daty (eurczk = 24,20), aby výsledky odpovídaly
finálním číslům v článcích. Spustitelné dvěma způsoby:

    python3 tests/test_backtest.py     # samostatně (exit != 0 při chybě)
    pytest tests/test_backtest.py      # jako pytest (funkce test_*)

Ruční kontrolní body (elektřina i plyn, vč. marží):
    elektřina  Ø fixQ4 2022–2025 = 4 693 Kč/MWh (±1)
    plyn       Ø fixQ4 2022–2025 = 2 089 Kč/MWh (±1)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from energy_model import BUILTIN, backtest, fair_range, avg  # noqa: E402

# očekávané hodnoty (ručně dopočítané při kurzu 24,20)
EXPECT = {
    "ele": {"fixQ4": 4693, "transe": 4098, "spot": 3510, "mix": 4102,
            "q4_minus_transe": 595, "fair": [2670, 2970]},
    "gas": {"fixQ4": 2089, "transe": 1810, "spot": 1613, "mix": 1851,
            "q4_minus_transe": 279, "fair": [1094, 1294]},
}

TOL = 1  # Kč/MWh


def _close(a, b, tol=TOL):
    return abs(a - b) <= tol


def _check_commodity(name, is_gas, failures):
    bt = backtest(BUILTIN, is_gas)
    exp = EXPECT[name]
    for key in ("fixQ4", "transe", "spot", "mix"):
        got = bt["avg"][key]
        if not _close(got, exp[key]):
            failures.append(f"{name}.{key}: čekáno {exp[key]}, spočteno {got:.2f}")
    diff = bt["avg"]["fixQ4"] - bt["avg"]["transe"]
    if not _close(diff, exp["q4_minus_transe"]):
        failures.append(f"{name}.q4-transe: čekáno {exp['q4_minus_transe']}, "
                        f"spočteno {diff:.2f}")
    cal_now = BUILTIN["gas" if is_gas else "ele"]["cal_now"]
    fr = fair_range(cal_now, is_gas)
    if fr != exp["fair"]:
        failures.append(f"{name}.fair: čekáno {exp['fair']}, spočteno {fr}")


def run():
    failures = []
    _check_commodity("ele", False, failures)
    _check_commodity("gas", True, failures)

    # doplňkově: konkrétní ruční body jednotlivých let
    ele = backtest(BUILTIN, False)
    # 2022: CAL Q4 157.04 × 24.2 + 350 = 4150.37
    assert _close(ele["fixQ4"][0], 4150.37, 0.5), ele["fixQ4"][0]
    # 2022 spot: 6080 + 250 = 6330 (OTE, beze změny)
    assert _close(ele["spot"][0], 6330, 0.001), ele["spot"][0]
    gas = backtest(BUILTIN, True)
    # 2022 plyn spot: 123 × 24.2 + 200 = 3176.6 (TTF, beze změny)
    assert _close(gas["spot"][0], 3176.6, 0.5), gas["spot"][0]

    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("OK — backtest odpovídá ručním výpočtům:")
    print(f"  elektřina Ø fixQ4 = {ele['avg']['fixQ4']:.1f} Kč/MWh (≈4693)")
    print(f"  plyn      Ø fixQ4 = {gas['avg']['fixQ4']:.1f} Kč/MWh (≈2089)")
    return 0


# --- pytest hooky ---
def test_ele_fixq4():
    assert _close(backtest(BUILTIN, False)["avg"]["fixQ4"], 4693)


def test_gas_fixq4():
    assert _close(backtest(BUILTIN, True)["avg"]["fixQ4"], 2089)


def test_ele_q4_minus_transe():
    bt = backtest(BUILTIN, False)
    assert _close(bt["avg"]["fixQ4"] - bt["avg"]["transe"], 595)


def test_gas_q4_minus_transe():
    bt = backtest(BUILTIN, True)
    assert _close(bt["avg"]["fixQ4"] - bt["avg"]["transe"], 279)


def test_fair_ranges():
    assert fair_range(BUILTIN["ele"]["cal_now"], False) == [2670, 2970]
    assert fair_range(BUILTIN["gas"]["cal_now"], True) == [1094, 1294]


if __name__ == "__main__":
    sys.exit(run())
