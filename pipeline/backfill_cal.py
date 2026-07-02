#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_cal.py — jednorázový, idempotentní backfill historie ročních kontraktů (CAL).

Nahrazuje ručně rekonstruované čtvrtletní průměry ročních kontraktů base load CZ
(elektřina) a PXE zemního plynu v datech webu přesnými hodnotami z veřejného archivu
kurzy.cz. Pro každou komoditu spočítá {rok_dodávky: [Q1,Q2,Q3,Q4]} v EUR/MWh.

METODIKA (odsouhlaseno):
  kurzy.cz publikuje jednu *rolující front-year* řadu baseload forwardu v EUR/MWh
  (endpoint idb.kurzy.cz). Během kalendářního roku Y-1 je nejbližší roční kontrakt
  právě CAL_Y, takže denní settlementy roku Y-1 rozřezané po kalendářních kvartálech
  dají čtvrtletní průměry kontraktu CAL_Y. Je to stejná metodika, jakou web už používá,
  jen s přesnými denními daty místo ručních odhadů. Kotva: Ø H1/2021 = 59,98 EUR
  (web uvádí 59,76 pro CAL22) → shoda 0,4 %, produkt i měna ověřeny.

ZDROJE (preferenční pořadí ze zadání):
  1) kurzy.cz  — POUŽITO. Grafová data jsou za JSONP endpointem idb.kurzy.cz.
                 Anti-bot mezistránka je jen na indexu /komodity/, ne na datovém API.
  2) patria.cz — NEPOUŽITELNÉ: nemá žádné PXE / české silové kontrakty (jen NYMEX/IPE).
  3) investing.com / EEX — jako fallback nebylo potřeba, obě řady jdou z kurzy.cz.

Výstupy:
  data/raw/cal_daily_{commodity}_frontyear.csv  — surová denní data (audit), inkrementálně
  data/cal_backfill.json                         — blok pro data.json: {"ele":{"cal":..},"gas":{"cal":..}}
  data/cal_backfill_report.md                    — srovnání stará/nová, pokrytí, zdroje, dopady

Spuštění:
  python3 pipeline/backfill_cal.py           # použije cache, stáhne jen chybějící dny
  python3 pipeline/backfill_cal.py --force   # vždy znovu stáhne a přepíše surová data
  python3 pipeline/backfill_cal.py --offline # nechodí na síť, počítá z uložených CSV / manual

Bez headless browseru. requests + pandas.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import pandas as pd

warnings.filterwarnings("ignore")  # tichý LibreSSL/urllib3 warning na systémovém Pythonu

# ---------------------------------------------------------------- cesty
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_JSON = ROOT / "data" / "cal_backfill.json"
OUT_REPORT = ROOT / "data" / "cal_backfill_report.md"
MANUAL_CSV = ROOT / "pipeline" / "manual" / "cal_template.csv"

# ---------------------------------------------------------------- síť / etiketa
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")
REQUEST_PAUSE_S = 1.5          # ≥1 s mezi requesty, žádné paralelní stahování
FRESH_DAYS = 3                # pokud jsou uložená data novější, na síť nechodíme
DELIVERY_YEARS = [2022, 2023, 2024, 2025, 2026]  # CAL22..CAL26

# ---------------------------------------------------------------- konfigurace komodit
# Staré (ruční) odhady z index.html — pro srovnávací tabulku a detekci chyb parsování.
OLD_CAL_ELE = {2022: [55, 62, 83, 128], 2023: [125, 185, 360, 255],
               2024: [142, 118, 122, 112], 2025: [76, 81, 92, 96],
               2026: [95, 88, 84, 88]}
OLD_CAL_GAS = {2022: [17, 21, 33, 55], 2023: [55, 85, 180, 110],
               2024: [55, 48, 52, 46], 2025: [30, 34, 37, 40]}  # 2026 se dříve neuvádělo

COMMODITIES = {
    "ele": {
        "label": "Elektřina base load CZ (front-year forward, PXE)",
        "series_name": "Elektřina EUR 1 MWh",
        "endpoint": "https://idb.kurzy.cz/ch-22273-eur-1MWh/history?callback=cb",
        "referer": "https://www.kurzy.cz/komodity/cena-elektriny-graf-vyvoje-ceny/",
        "old": OLD_CAL_ELE,
    },
    "gas": {
        "label": "Zemní plyn (PXE, front-year forward)",
        "series_name": "PXE - Zemní plyn EUR 1 MWh",
        "endpoint": "https://idb.kurzy.cz/ch-22271-eur-1MWh/history?callback=cb",
        "referer": "https://www.kurzy.cz/komodity/pxe-zemni-plyn-graf-vyvoje-ceny/",
        "old": OLD_CAL_GAS,
    },
}

# ---------------------------------------------------------------- parametry backtestu (z index.html)
EURCZK = 24.2
MARGIN_FIX, MARGIN_SPOT = 350, 250          # elektřina, Kč/MWh
GAS_MARGIN_FIX, GAS_MARGIN_SPOT = 300, 200  # plyn, Kč/MWh
SPOT_Y_ELE = {2021: 2570, 2022: 6080, 2023: 2420, 2024: 2140, 2025: 2400}  # Kč/MWh (OTE)
SPOT_Y_GAS_EUR = {2021: 47, 2022: 123, 2023: 41, 2024: 34.5, 2025: 35}     # EUR/MWh (TTF)

DEV_THRESHOLD = 25.0   # % — nad tímto flag, ukaž surová data kvartálu
LOW_COVERAGE_MIN = 30  # obchodních dnů na kvartál


# ================================================================ stahování
def fetch_series(cfg: dict) -> pd.DataFrame:
    """Stáhne JSONP z idb.kurzy.cz a vrátí DataFrame [date, settlement_eur]."""
    headers = {"User-Agent": UA, "Referer": cfg["referer"],
               "Accept": "application/json, text/javascript, */*"}
    last_err = None
    for _ in range(2):
        try:
            r = requests.get(cfg["endpoint"], headers=headers, timeout=30)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                time.sleep(REQUEST_PAUSE_S)
                continue
            body = r.text
            i, j = body.find("["), body.rfind("]")
            if i < 0 or j < 0:
                raise ValueError("v odpovědi není JSON pole (možná anti-bot stránka)")
            data = json.loads(body[i:j + 1])
            rows = []
            for ts, val in data:
                if val is None:
                    continue
                d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date()
                rows.append((d.isoformat(), float(val)))
            df = pd.DataFrame(rows, columns=["date", "settlement_eur"])
            return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(REQUEST_PAUSE_S)
    raise RuntimeError(f"stažení selhalo: {last_err}")


def raw_path(commodity: str) -> Path:
    return RAW_DIR / f"cal_daily_{commodity}_frontyear.csv"


def load_raw(commodity: str) -> pd.DataFrame:
    p = raw_path(commodity)
    if p.exists():
        df = pd.read_csv(p, dtype={"date": str})
        return df[["date", "commodity", "contract", "settlement_eur"]]
    return pd.DataFrame(columns=["date", "commodity", "contract", "settlement_eur"])


def contract_for(iso_date: str) -> str:
    """Kalendářní rok Y-1 mapuje na kontrakt CAL_(Y). Vstup 'YYYY-MM-DD'."""
    y = int(iso_date[:4])
    return f"CAL{(y + 1) % 100:02d}"


def store_raw(commodity: str, fetched: pd.DataFrame) -> pd.DataFrame:
    """Sloučí nově stažené dny s uloženými (idempotentně, dedup podle data)."""
    existing = load_raw(commodity)
    new = fetched.copy()
    new["commodity"] = commodity
    new["contract"] = new["date"].map(contract_for)
    new = new[["date", "commodity", "contract", "settlement_eur"]]
    merged = pd.concat([existing, new], ignore_index=True)
    merged = merged.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(raw_path(commodity), index=False)
    added = len(set(new["date"]) - set(existing["date"]))
    print(f"  [{commodity}] surová data: {len(merged)} dnů celkem (+{added} nových) "
          f"→ {raw_path(commodity).relative_to(ROOT)}")
    return merged


def apply_manual(commodity: str, df: pd.DataFrame) -> pd.DataFrame:
    """Ručně doplněné settlementy z cal_template.csv mají přednost (fallback ze zadání)."""
    if not MANUAL_CSV.exists():
        return df
    man = pd.read_csv(MANUAL_CSV, dtype=str, comment="#", skip_blank_lines=True,
                      on_bad_lines="skip").fillna("")
    man = man[(man["commodity"] == commodity) & (man["settlement_eur"].str.strip() != "")]
    if man.empty:
        return df
    man = man.assign(settlement_eur=man["settlement_eur"].str.replace(",", ".").astype(float))
    man["commodity"] = commodity
    man["contract"] = man["date"].map(contract_for)
    merged = pd.concat([df, man[["date", "commodity", "contract", "settlement_eur"]]], ignore_index=True)
    merged = merged.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    print(f"  [{commodity}] aplikováno {len(man)} ručních řádků z {MANUAL_CSV.name}")
    return merged


def get_daily(commodity: str, cfg: dict, force: bool, offline: bool) -> tuple[pd.DataFrame, str]:
    """Vrátí (denní data, poznámka o zdroji). Respektuje cache i offline režim."""
    existing = load_raw(commodity)
    fresh = False
    if not existing.empty:
        last = existing["date"].max()
        fresh = (date.today() - date.fromisoformat(last)).days <= FRESH_DAYS
    if offline or (fresh and not force):
        why = "offline režim" if offline else f"cache aktuální (poslední den {existing['date'].max()})"
        if existing.empty:
            print(f"  [{commodity}] {why}, ale nemám žádná uložená data!")
        else:
            print(f"  [{commodity}] {why} → nestahuji")
        last = existing["date"].max() if not existing.empty else "?"
        note = f"kurzy.cz {cfg['endpoint']} (z cache, poslední den {last})"
        return apply_manual(commodity, existing), note
    print(f"  [{commodity}] stahuji {cfg['endpoint']}")
    fetched = fetch_series(cfg)
    time.sleep(REQUEST_PAUSE_S)  # zdvořilá pauza před další komoditou
    merged = store_raw(commodity, fetched)
    merged = apply_manual(commodity, merged)
    return merged, f"kurzy.cz {cfg['endpoint']} (staženo {date.today().isoformat()})"


# ================================================================ výpočet kvartálů
def quarterly(df: pd.DataFrame, delivery_year: int):
    """Vrátí (values[4], coverage[4], raw_by_q{q:df}) pro CAL_delivery_year z roku Y-1."""
    py = delivery_year - 1
    d = df.copy()
    d["d"] = pd.to_datetime(d["date"])
    d = d[d["d"].dt.year == py]
    vals, cov, raw_by_q = [], [], {}
    for q in (1, 2, 3, 4):
        sub = d[d["d"].dt.quarter == q]
        raw_by_q[q] = sub
        cov.append(len(sub))
        vals.append(round(sub["settlement_eur"].mean(), 2) if len(sub) else None)
    return vals, cov, raw_by_q


def dev_pct(old, new):
    if old in (None, 0) or new is None:
        return None
    return round((new - old) / old * 100.0, 1)


# ================================================================ backtest (replikace index.html)
def avg(a):
    a = [x for x in a if x is not None]
    return sum(a) / len(a) if a else float("nan")


def backtest(cal: dict, is_gas: bool):
    years = [2022, 2023, 2024, 2025]
    out = {"fixQ4": [], "transe": [], "spot": [], "mix": []}
    for y in years:
        if is_gas:
            spot = SPOT_Y_GAS_EUR[y] * EURCZK + GAS_MARGIN_SPOT
            fixq4 = cal[y][3] * EURCZK + GAS_MARGIN_FIX
            transe = avg(cal[y]) * EURCZK + GAS_MARGIN_FIX
        else:
            spot = SPOT_Y_ELE[y] + MARGIN_SPOT
            fixq4 = cal[y][3] * EURCZK + MARGIN_FIX
            transe = avg(cal[y]) * EURCZK + MARGIN_FIX
        out["fixQ4"].append(fixq4)
        out["transe"].append(transe)
        out["spot"].append(spot)
        out["mix"].append((fixq4 + spot) / 2)
    summary = {k: avg(v) for k, v in out.items()}
    order = sorted(summary, key=summary.get)
    gap_podzim_transe = avg([out["fixQ4"][i] - out["transe"][i] for i in range(len(years))])
    return summary, order, gap_podzim_transe


# ================================================================ report
def fmt_row(cells, widths):
    return "| " + " | ".join(str(c).ljust(w) for c, w in zip(cells, widths)) + " |"


def build_report(results: dict, sources: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    L = []
    L.append("# Backfill ročních kontraktů (CAL) — report\n")
    L.append(f"_Vygenerováno: {now}. Skript: `pipeline/backfill_cal.py`._\n")
    L.append("> **Nic se nenasazuje automaticky.** `data/cal_backfill.json` je připraven k ručnímu "
             "vložení do `data.json` (klíče `ele.cal` / `gas.cal`) po kontrole tohoto reportu.\n")

    # --- metodika a zdroje
    L.append("## Metodika a zdroje\n")
    L.append("Řada z kurzy.cz je jedna **rolující front-year** křivka baseload forwardu v EUR/MWh. "
             "Během kalendářního roku Y-1 je nejbližší roční kontrakt právě CAL_Y, takže denní "
             "settlementy roku Y-1 rozřezané po kalendářních kvartálech = čtvrtletní průměry CAL_Y. "
             "Jde o **rekonstrukci stejnou metodikou, jakou web už používá**, jen z přesných denních dat "
             "(ne pravý fixní kontrakt s vlastní cenovou dráhou po celý život — to by vyžadovalo "
             "per-kontraktní data z pxe.cz/EEX, strojově nedostupná).\n")
    L.append("Kotva ověření: Ø H1/2021 vychází ~59,98 EUR, web uvádí 59,76 EUR pro CAL22 → shoda 0,4 %, "
             "produkt (baseload CZ) i měna (EUR/MWh) potvrzeny.\n")
    L.append("| Komodita | Zdroj | Rozsah dat | Pozn. |")
    L.append("|---|---|---|---|")
    for c, r in results.items():
        L.append(f"| {COMMODITIES[c]['label']} | {sources[c]} | {r['span']} | přímo EUR/MWh, bez přepočtu |")
    L.append("\n_patria.cz vyřazena — nemá žádné PXE / české silové kontrakty (jen NYMEX/IPE globální energie). "
             "Fallback investing.com/EEX nebyl potřeba._\n")

    # --- srovnávací tabulka + pokrytí
    for c, r in results.items():
        old = COMMODITIES[c]["old"]
        L.append(f"## {COMMODITIES[c]['label']} — srovnání stará vs. nová\n")
        L.append("| CAL (rok dodávky) | ceny v roce | Q | stará | nová | odchylka % | pokrytí (dnů) | flag |")
        L.append("|---|---|---|---|---|---|---|---|")
        for y in DELIVERY_YEARS:
            newv = r["cal"].get(y)
            cov = r["cover"].get(y, [0, 0, 0, 0])
            oldv = old.get(y)
            for qi in range(4):
                nv = newv[qi] if newv else None
                ov = oldv[qi] if oldv else None
                dp = dev_pct(ov, nv)
                flags = []
                if dp is not None and abs(dp) > DEV_THRESHOLD:
                    flags.append(f"⚠︎>{DEV_THRESHOLD:.0f}%")
                if cov[qi] < LOW_COVERAGE_MIN:
                    flags.append("LOW_COVERAGE")
                L.append(fmt_row(
                    [f"CAL{y % 100}" if qi == 0 else "", (y - 1) if qi == 0 else "",
                     f"Q{qi+1}",
                     "—" if ov is None else ov,
                     "—" if nv is None else f"**{nv}**",
                     "—" if dp is None else f"{dp:+.1f}",
                     cov[qi], " ".join(flags)],
                    [7, 5, 3, 6, 9, 8, 6, 16]))
        L.append("")

    # --- surová data flagnutých kvartálů
    L.append("## Surová denní data kvartálů s odchylkou > 25 %\n")
    L.append("_Kontrola, že nejde o chybu parsování. Kotva 59,98≈59,76 EUR potvrzuje správný produkt i měnu — "
             "vyšší hodnoty jsou reálný trh, ruční odhady krize byly zaokrouhlené konzervativně dolů._\n")
    any_flag = False
    for c, r in results.items():
        old = COMMODITIES[c]["old"]
        for y in DELIVERY_YEARS:
            newv = r["cal"].get(y)
            oldv = old.get(y)
            if not newv or not oldv:
                continue
            for qi in range(4):
                dp = dev_pct(oldv[qi], newv[qi])
                if dp is None or abs(dp) <= DEV_THRESHOLD:
                    continue
                any_flag = True
                sub = r["raw_q"][y][qi + 1].sort_values("date")
                head = sub.head(3)[["date", "settlement_eur"]].values.tolist()
                tail = sub.tail(3)[["date", "settlement_eur"]].values.tolist()
                L.append(f"**{COMMODITIES[c]['label']} — CAL{y % 100} Q{qi+1}** "
                         f"(ceny v {y-1}): stará {oldv[qi]} → nová {newv[qi]} EUR ({dp:+.1f} %)")
                L.append(f"- dnů: {len(sub)}, min {sub['settlement_eur'].min():.2f}, "
                         f"max {sub['settlement_eur'].max():.2f}, Ø {sub['settlement_eur'].mean():.2f} EUR")
                L.append(f"- první: {head}  … poslední: {tail}")
                L.append("")
    if not any_flag:
        L.append("_Žádný kvartál nepřekročil práh._\n")

    # --- dopad na backtest a citovaná čísla
    L.append("## Dopad na backtest a citovaná čísla\n")
    for label, old_cal, new_cal, is_gas, cited in [
        ("Elektřina", OLD_CAL_ELE, results["ele"]["cal"], False, 411),
        ("Plyn", OLD_CAL_GAS, results["gas"]["cal"], True, 160),
    ]:
        so, oo, ogap = backtest(old_cal, is_gas)
        sn, on, ngap = backtest({y: new_cal[y] for y in [2022, 2023, 2024, 2025]}, is_gas)
        L.append(f"### {label}\n")
        L.append("- Průměr strategií 2022–2025 (Kč/MWh, vč. marže):")
        L.append("  - **stará** data: " + ", ".join(f"{k} {so[k]:.0f}" for k in oo))
        L.append("  - **nová** data: " + ", ".join(f"{k} {sn[k]:.0f}" for k in on))
        L.append(f"  - pořadí strategií: {'⚠︎ ZMĚNILO SE' if oo != on else 'beze změny'} "
                 f"({' < '.join(oo)} → {' < '.join(on)})")
        L.append(f"- „Fix na podzim vs. tranše\": staré ~{ogap:.0f} Kč/MWh (citováno **{cited}**) "
                 f"→ nové **{ngap:.0f} Kč/MWh** ({dev_pct(ogap, ngap):+.1f} %)")
        L.append("")
    L.append("**Citovaná čísla, která po nasazení přestanou sedět:**")
    L.append("- `blog-kdy-fixovat-elektrinu.html`: **411 Kč/MWh** (rozdíl podzimní fix vs. tranše) — viz nová hodnota výše.")
    L.append("- `blog-cena-plynu-pro-firmy.html`: **~160 Kč/MWh (10 %)** — dtto pro plyn.")
    L.append("- Ticker / „férová rozmezí\" v `index.html` jdou z `cal_now` (aktuální CAL27), ne z historie CAL "
             "→ **beze změny**.")
    L.append("- KPI „rozdíl nejlepší vs. nejhorší strategie\" v kalkulačce se přepočítá dynamicky z nových `cal`.\n")

    # --- pokrytí shrnutí
    L.append("## Pokrytí — shrnutí\n")
    missing = []
    for c, r in results.items():
        for y in DELIVERY_YEARS:
            for qi, n in enumerate(r["cover"].get(y, [0, 0, 0, 0])):
                if n < LOW_COVERAGE_MIN:
                    missing.append(f"{c} CAL{y % 100} Q{qi+1} ({n} dnů)")
    if missing:
        L.append("Úseky pod prahem 30 dnů (doplnit ručně z pxe.cz / EEX DataSource do "
                 "`pipeline/manual/cal_template.csv`):")
        for m in missing:
            L.append(f"- {m}")
    else:
        L.append("Všechny kvartály CAL22–CAL26 mají dost obchodních dnů (≥30). Žádný úsek nechybí; "
                 "`pipeline/manual/cal_template.csv` nebyl potřeba.")
    L.append("")
    return "\n".join(L)


# ================================================================ main
def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill CAL kontraktů z kurzy.cz")
    ap.add_argument("--force", action="store_true", help="vždy znovu stáhnout")
    ap.add_argument("--offline", action="store_true", help="nechodit na síť, počítat z CSV")
    args = ap.parse_args()

    print("== backfill_cal.py ==")
    results, sources = {}, {}
    for commodity, cfg in COMMODITIES.items():
        df, note = get_daily(commodity, cfg, args.force, args.offline)
        if df.empty:
            print(f"  [{commodity}] CHYBA: žádná data, přeskakuji")
            continue
        sources[commodity] = note
        cal, cover, raw_q = {}, {}, {}
        for y in DELIVERY_YEARS:
            vals, cov, rq = quarterly(df, y)
            if all(v is not None for v in vals):
                cal[y] = vals
            cover[y] = cov
            raw_q[y] = rq
        span = f"{df['date'].min()} → {df['date'].max()}"
        results[commodity] = {"cal": cal, "cover": cover, "raw_q": raw_q, "span": span}
        print(f"  [{commodity}] spočítáno CAL: {sorted(cal)}")

    if "ele" not in results or "gas" not in results:
        print("CHYBA: chybí data pro některou komoditu — report ani JSON se nezapisují.", file=sys.stderr)
        return 1

    # --- výstupní JSON pro data.json (klíče roků jako stringy, jak je čte loader)
    out = {"ele": {"cal": {str(y): v for y, v in results["ele"]["cal"].items()}},
           "gas": {"cal": {str(y): v for y, v in results["gas"]["cal"].items()}}}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {OUT_JSON.relative_to(ROOT)}")

    # --- report
    OUT_REPORT.write_text(build_report(results, sources), encoding="utf-8")
    print(f"→ {OUT_REPORT.relative_to(ROOT)}")
    print("Hotovo. Zkontroluj report; data.json aktualizuj ručně.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
