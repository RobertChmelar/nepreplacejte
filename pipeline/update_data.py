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
  (c) Settlement ročních kontraktů (BL CAL elektřina + plyn) — denní řada
      idb.kurzy.cz (front-year forward PXE, stejný zdroj a endpointy jako
      pipeline/backfill_cal.py; anti-bot je jen na HTML indexu kurzy.cz,
      ne na datovém API)
        · poslední dostupný settlement -> ele.cal_now / gas.cal_now (EUR/MWh)
        · tatáž kotace (se skutečným datem) -> append do data/cal_history.csv
          (date, commodity, contract, price_eur) pro budoucí výpočet
          čtvrtletních průměrů (viz backfill_cal.py).

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
            "2022": [54.31, 65.56, 88.94, 157.04],
            "2023": [149.26, 227.42, 463.59, 350.66],
            "2024": [161.74, 140.93, 136.96, 114.69],
            "2025": [81.89, 94.75, 94.96, 95.5],
            "2026": [94.88, 94.02, 94.39, 94.66],
        },
        "cal_now": 100,
    },
    "gas": {
        "spot_y_eur": {"2021": 47, "2022": 123, "2023": 41, "2024": 34.5, "2025": 35},
        "cal": {
            "2022": [17.5, 21.43, 33.63, 65.48],
            "2023": [60.96, 94.48, 187.21, 137.37],
            "2024": [63.23, 55.54, 55.37, 48.68],
            "2025": [34.08, 38.66, 40.7, 44.15],
            "2026": [40.76, 36.88, 35.26, 31.85],
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
# (c) Roční kontrakty (CAL) — denní řada idb.kurzy.cz (front-year fwd PXE)
# ---------------------------------------------------------------------------
# Stejný zdroj a endpointy jako pipeline/backfill_cal.py. kurzy.cz publikuje
# rolující front-year křivku v EUR/MWh za JSONP endpointem idb.kurzy.cz;
# během roku Y je nejbližší roční kontrakt CAL(Y+1).
KURZY_SERIES = {
    "ele": {
        "endpoint": "https://idb.kurzy.cz/ch-22273-eur-1MWh/history?callback=cb",
        "referer": "https://www.kurzy.cz/komodity/cena-elektriny-graf-vyvoje-ceny/",
    },
    "gas": {
        "endpoint": "https://idb.kurzy.cz/ch-22271-eur-1MWh/history?callback=cb",
        "referer": "https://www.kurzy.cz/komodity/pxe-zemni-plyn-graf-vyvoje-ceny/",
    },
}
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def _fetch_kurzy_last(commodity):
    """
    Poslední dostupný settlement z JSONP řady idb.kurzy.cz.
    Vrací (iso_date, price_eur); při jakémkoli problému vyhazuje výjimku
    (fallback řeší volající).
    """
    cfg = KURZY_SERIES[commodity]
    req = urllib.request.Request(cfg["endpoint"], headers={
        "User-Agent": BROWSER_UA,
        "Referer": cfg["referer"],
        "Accept": "application/json, text/javascript, */*",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    i, j = body.find("["), body.rfind("]")
    if i < 0 or j < 0:
        raise ValueError("v odpovědi není JSON pole (anti-bot stránka?)")
    data = json.loads(body[i:j + 1])
    last = None
    for ts, val in data:                      # [[ts_ms, EUR/MWh], ...]
        if val is not None:
            last = (ts, float(val))
    if last is None:
        raise ValueError("řada neobsahuje žádnou hodnotu")
    day = dt.datetime.fromtimestamp(last[0] / 1000, tz=dt.timezone.utc).date()
    return day.isoformat(), round(last[1], 2)


def fetch_pxe_cal(fallback_ele, fallback_gas):
    """
    Aktuální settlement ročních kontraktů (elektřina BL + plyn, EUR/MWh)
    z denní řady idb.kurzy.cz. Vrací:
        (ele_cal_now, gas_cal_now, rows)
    kde rows = [{date, commodity, contract, price_eur}] se skutečným datem
    kotace pro append do cal_history.csv. Při výpadku kterékoli řady
    zůstává poslední známá hodnota (fallback) a zaloguje se WARNING.
    """
    rows = []
    now = {"ele": fallback_ele, "gas": fallback_gas}
    for commodity in ("ele", "gas"):
        try:
            day, price = _fetch_kurzy_last(commodity)
            contract = f"CAL-{(int(day[:4]) + 1) % 100:02d}"   # front-year
            now[commodity] = price
            rows.append({"date": day, "commodity": commodity,
                         "contract": contract, "price_eur": price})
            log("INFO", f"kurzy.cz {commodity}: {contract} = {price} EUR/MWh "
                        f"(settlement {day})")
        except Exception as e:
            log("WARN", f"kurzy.cz {commodity} selhal ({e}); "
                        f"cal_now zůstává {now[commodity]}")
    return now["ele"], now["gas"], rows


def append_cal_history(rows):
    """Přidá denní CAL kotace do rostoucí historie (idempotentně podle
    skutečného data settlementu — víkendy/svátky se nedublují)."""
    if not rows:
        return
    existing = set()
    if os.path.exists(CAL_HISTORY):
        with open(CAL_HISTORY, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing.add((r["date"], r["commodity"], r["contract"]))
    new_rows = []
    for r in rows:
        day = r.get("date") or dt.date.today().isoformat()
        key = (day, r["commodity"], r["contract"])
        if key not in existing:
            new_rows.append([day, r["commodity"], r["contract"], r["price_eur"]])
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
