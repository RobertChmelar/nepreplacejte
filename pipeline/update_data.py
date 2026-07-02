#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_data.py — denní aktualizace tržních dat pro nepřeplácejte.cz
====================================================================

Stáhne a zapíše data/data.json PŘESNĚ ve formátu, který čte assets/app.js
(loader okolo řádku 500). Zdroje:

  (a) Ceny denního trhu CZ  — https://api.energy-charts.info/price?bzn=CZ
        · dnešní průměr           -> spot_today_czk  (v Kč, přepočet kurzem)
        · průběžný roční průměr   -> ele.spot_y[<letošní rok>]  (v Kč)
  (b) Kurz EUR/CZK          — veřejné API ČNB (denní kurz, txt)
        -> eurczk
  (c) Settlement ročních kontraktů (BL CAL elektřina + plyn) — kurzovní
      lístek pxe.cz
        · aktuální CAL na příští rok -> ele.cal_now / gas.cal_now (EUR/MWh)
        · všechny denní CAL kotace   -> appendují se do data/cal_history.csv
          (date, commodity, contract, price_eur) pro pozdější výpočet
          budoucích čtvrtletních průměrů (viz backfill_cal.py).

FILOZOFIE ROBUSTNOSTI: každý zdroj je v try/except. Když spadne, použije se
poslední známá hodnota z existujícího data/data.json (nebo vestavěný
fallback shodný s app.js) a zapíše se WARNING. Skript tak nikdy neshodí
GitHub Action a web zůstane na posledních platných datech.

Závislosti: pouze standardní knihovna (urllib) — Action nepotřebuje pip.
"""

import csv
import datetime as dt
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_JSON = os.path.join(ROOT, "data", "data.json")
CAL_HISTORY = os.path.join(ROOT, "data", "cal_history.csv")

# --- Vestavěný fallback: MUSÍ odpovídat výchozím datům v assets/app.js ---
FALLBACK = {
    "asof": "2026-06-11",
    "eurczk": 24.2,
    "ele": {
        "spot_y": {"2021": 2570, "2022": 6080, "2023": 2420, "2024": 2140, "2025": 2400},
        "cal": {
            "2022": [55, 62, 83, 128],
            "2023": [125, 185, 360, 255],
            "2024": [142, 118, 122, 112],
            "2025": [76, 81, 92, 96],
            "2026": [95, 88, 84, 88],
        },
        "cal_now": 100,
    },
    "gas": {
        "spot_y_eur": {"2021": 47, "2022": 123, "2023": 41, "2024": 34.5, "2025": 35},
        "cal": {
            "2022": [17, 21, 33, 55],
            "2023": [55, 85, 180, 110],
            "2024": [55, 48, 52, 46],
            "2025": [30, 34, 37, 40],
        },
        "cal_now": 39,
    },
    "spot_today_czk": 2680,
}

UA = {"User-Agent": "nepreplacejte-pipeline/1.0 (+https://nepreplacejte.cz)"}


def log(level, msg):
    print(f"[{level}] {msg}", file=sys.stderr if level == "WARN" else sys.stdout)


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# (b) Kurz ČNB
# ---------------------------------------------------------------------------
def fetch_cnb_eurczk(fallback):
    """Denní kurz ČNB (txt): řádky 'země|měna|množství|kód|kurz' (des. čárka)."""
    url = ("https://www.cnb.cz/cs/financni-trhy/devizovy-trh/"
           "kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt")
    try:
        txt = http_get(url)
        for line in txt.splitlines():
            parts = line.split("|")
            if len(parts) == 5 and parts[3] == "EUR":
                amount = float(parts[2].replace(",", "."))
                rate = float(parts[4].replace(",", "."))
                val = round(rate / amount, 3)
                log("INFO", f"ČNB EUR/CZK = {val}")
                return val
        raise ValueError("EUR řádek nenalezen v kurzovním lístku ČNB")
    except Exception as e:
        log("WARN", f"ČNB kurz selhal ({e}); fallback {fallback}")
        return fallback


# ---------------------------------------------------------------------------
# (a) energy-charts — denní trh CZ
# ---------------------------------------------------------------------------
def _energy_charts_prices(start=None, end=None):
    url = "https://api.energy-charts.info/price?bzn=CZ"
    if start:
        url += f"&start={start}"
    if end:
        url += f"&end={end}"
    d = json.loads(http_get(url))
    return [v for v in (d.get("price") or []) if v is not None]  # EUR/MWh


def fetch_spot_today_czk(eurczk, fallback):
    """Dnešní průměr denního trhu CZ (Kč/MWh)."""
    try:
        prices = _energy_charts_prices()
        if not prices:
            raise ValueError("prázdná odpověď energy-charts")
        eur = sum(prices) / len(prices)
        val = round(eur * eurczk)
        log("INFO", f"Spot dnes Ø = {val} Kč/MWh ({eur:.2f} EUR × {eurczk})")
        return val
    except Exception as e:
        log("WARN", f"Spot dnes selhal ({e}); fallback {fallback}")
        return fallback


def fetch_spot_year_avg_czk(year, eurczk, fallback):
    """Průběžný roční průměr denního trhu CZ za daný rok (Kč/MWh)."""
    try:
        start = f"{year}-01-01"
        end = dt.date.today().isoformat()
        prices = _energy_charts_prices(start=start, end=end)
        if not prices:
            raise ValueError("prázdná roční řada energy-charts")
        eur = sum(prices) / len(prices)
        val = round(eur * eurczk)
        log("INFO", f"Spot Ø {year} (průběžně) = {val} Kč/MWh z {len(prices)} bodů")
        return val
    except Exception as e:
        log("WARN", f"Roční průměr {year} selhal ({e}); fallback {fallback}")
        return fallback


# ---------------------------------------------------------------------------
# (c) PXE — settlement ročních kontraktů
# ---------------------------------------------------------------------------
def fetch_pxe_cal(fallback_ele, fallback_gas):
    """
    Aktuální settlement CAL kontraktů z veřejného kurzovního lístku PXE.

    PXE zveřejňuje denní výsledky trhu; formát/URL se ale mění, proto je
    tento parser 'best effort' a při jakémkoli problému vrací poslední
    známé hodnoty. Vrací:
        (ele_cal_now, gas_cal_now, rows)
    kde rows = list dictů {commodity, contract, price_eur} pro cal_history.

    Cílový kontrakt = BL CAL na PŘÍŠTÍ kalendářní rok (rok+1).
    """
    next_year = dt.date.today().year + 1
    target = f"CAL-{next_year % 100:02d}"  # např. CAL-27
    rows = []
    ele_now, gas_now = fallback_ele, fallback_gas

    # Veřejný endpoint kurzovního lístku PXE (JSON). Struktura se může lišit;
    # proto tolerantní parsování s vícero variantami klíčů.
    candidates = [
        "https://www.pxe.cz/pxe_downloads/Results/Kurz/PXE_Kurz.json",
        "https://www.pxe.cz/Kurzovni-Listek/Oficialni-KL",
    ]
    for url in candidates:
        try:
            raw = http_get(url)
            data = json.loads(raw)
            found = _parse_pxe_payload(data, next_year)
            if found:
                for commodity, contract, price in found:
                    rows.append({"commodity": commodity, "contract": contract,
                                 "price_eur": price})
                    if contract.upper().endswith(target.split("-")[1]):
                        if commodity == "ele":
                            ele_now = round(price, 2)
                        elif commodity == "gas":
                            gas_now = round(price, 2)
                log("INFO", f"PXE: načteno {len(found)} CAL kotací z {url}")
                break
        except Exception as e:
            log("WARN", f"PXE zdroj {url} selhal ({e})")
            continue

    if not rows:
        log("WARN", "PXE: žádná kotace strojově nepřečtena — "
                    f"cal_now zůstává (ele={ele_now}, gas={gas_now}). "
                    "Zvaž ruční doplnění přes backfill_cal.py / šablonu CSV.")
    return ele_now, gas_now, rows


def _parse_pxe_payload(data, next_year):
    """
    Tolerantní extrakce (commodity, contract, price_eur) z PXE JSONu.
    Rozpozná elektřinu (BL/base) a plyn podle názvu produktu; roční
    kontrakty podle 'CAL' / 'Y' + roku. Vrací list trojic nebo [].
    """
    out = []
    items = data if isinstance(data, list) else data.get("data") or data.get("items") or []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or it.get("product") or it.get("instrument") or "")
        n = name.upper()
        if "CAL" not in n and "Y-" not in n and "YEAR" not in n:
            continue
        # rok kontraktu
        yy = None
        for token in n.replace("-", " ").replace("/", " ").split():
            if token.isdigit() and len(token) in (2, 4):
                yy = int(token) if len(token) == 4 else 2000 + int(token)
        if yy is None:
            continue
        price = it.get("settlement") or it.get("price") or it.get("close") or it.get("last")
        if price is None:
            continue
        try:
            price = float(str(price).replace(",", "."))
        except ValueError:
            continue
        commodity = "gas" if ("GAS" in n or "PLYN" in n or "TTF" in n or "VTP" in n) else "ele"
        out.append((commodity, f"CAL-{yy % 100:02d}", price))
    return out


def append_cal_history(rows):
    """Přidá dnešní CAL kotace do rostoucí historie (idempotentně na den)."""
    if not rows:
        return
    today = dt.date.today().isoformat()
    existing = set()
    if os.path.exists(CAL_HISTORY):
        with open(CAL_HISTORY, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing.add((r["date"], r["commodity"], r["contract"]))
    new_rows = []
    for r in rows:
        key = (today, r["commodity"], r["contract"])
        if key not in existing:
            new_rows.append([today, r["commodity"], r["contract"], r["price_eur"]])
            existing.add(key)
    if not new_rows:
        log("INFO", "cal_history: pro dnešek už zapsáno, přeskočeno")
        return
    header_needed = not os.path.exists(CAL_HISTORY) or os.path.getsize(CAL_HISTORY) == 0
    with open(CAL_HISTORY, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if header_needed:
            w.writerow(["date", "commodity", "contract", "price_eur"])
        w.writerows(new_rows)
    log("INFO", f"cal_history: +{len(new_rows)} řádků")


# ---------------------------------------------------------------------------
# Hlavní běh
# ---------------------------------------------------------------------------
def load_previous():
    if os.path.exists(DATA_JSON):
        try:
            with open(DATA_JSON, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log("WARN", f"Nelze číst stávající data.json ({e}); použit fallback")
    return json.loads(json.dumps(FALLBACK))


def main():
    prev = load_previous()
    year = dt.date.today().year

    # (b) kurz
    eurczk = fetch_cnb_eurczk(prev.get("eurczk", FALLBACK["eurczk"]))

    # (a) spot
    spot_today = fetch_spot_today_czk(eurczk, prev.get("spot_today_czk",
                                                       FALLBACK["spot_today_czk"]))
    prev_year_spot = prev.get("ele", {}).get("spot_y", {}).get(
        str(year), FALLBACK["ele"]["spot_y"].get(str(year)))
    year_avg = fetch_spot_year_avg_czk(year, eurczk, prev_year_spot)

    # (c) PXE CAL
    ele_now, gas_now, cal_rows = fetch_pxe_cal(
        prev.get("ele", {}).get("cal_now", FALLBACK["ele"]["cal_now"]),
        prev.get("gas", {}).get("cal_now", FALLBACK["gas"]["cal_now"]),
    )
    append_cal_history(cal_rows)

    # sestav výstup — historické cal / spot_y (ověřené, finální) zachováváme
    spot_y = dict(prev.get("ele", {}).get("spot_y", FALLBACK["ele"]["spot_y"]))
    if year_avg is not None:                 # letošní klíč jen s reálným číslem
        spot_y[str(year)] = year_avg
    out = {
        "asof": dt.date.today().isoformat(),
        "eurczk": eurczk,
        "ele": {
            "spot_y": spot_y,
            "cal": prev.get("ele", {}).get("cal", FALLBACK["ele"]["cal"]),
            "cal_now": ele_now,
        },
        "gas": {
            "spot_y_eur": prev.get("gas", {}).get("spot_y_eur", FALLBACK["gas"]["spot_y_eur"]),
            "cal": prev.get("gas", {}).get("cal", FALLBACK["gas"]["cal"]),
            "cal_now": gas_now,
        },
        "spot_today_czk": spot_today,
    }

    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log("INFO", f"Zapsáno {DATA_JSON} (asof {out['asof']}, "
                f"eurczk {eurczk}, spot_today {spot_today}, "
                f"ele.cal_now {ele_now}, gas.cal_now {gas_now})")


if __name__ == "__main__":
    main()
