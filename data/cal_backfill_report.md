# Backfill ročních kontraktů (CAL) — report

_Vygenerováno: 2026-07-03 00:12. Skript: `pipeline/backfill_cal.py`._

> **Nic se nenasazuje automaticky.** `data/cal_backfill.json` je připraven k ručnímu vložení do `data.json` (klíče `ele.cal` / `gas.cal`) po kontrole tohoto reportu.

## Metodika a zdroje

Řada z kurzy.cz je jedna **rolující front-year** křivka baseload forwardu v EUR/MWh. Během kalendářního roku Y-1 je nejbližší roční kontrakt právě CAL_Y, takže denní settlementy roku Y-1 rozřezané po kalendářních kvartálech = čtvrtletní průměry CAL_Y. Jde o **rekonstrukci stejnou metodikou, jakou web už používá**, jen z přesných denních dat (ne pravý fixní kontrakt s vlastní cenovou dráhou po celý život — to by vyžadovalo per-kontraktní data z pxe.cz/EEX, strojově nedostupná).

Kotva ověření: Ø H1/2021 vychází ~59,98 EUR, web uvádí 59,76 EUR pro CAL22 → shoda 0,4 %, produkt (baseload CZ) i měna (EUR/MWh) potvrzeny.

| Komodita | Zdroj | Rozsah dat | Pozn. |
|---|---|---|---|
| Elektřina base load CZ (front-year forward, PXE) | kurzy.cz https://idb.kurzy.cz/ch-22273-eur-1MWh/history?callback=cb (staženo 2026-07-03) | 2007-08-23 → 2026-06-30 | přímo EUR/MWh, bez přepočtu |
| Zemní plyn (PXE, front-year forward) | kurzy.cz https://idb.kurzy.cz/ch-22271-eur-1MWh/history?callback=cb (staženo 2026-07-03) | 2013-12-08 → 2026-06-30 | přímo EUR/MWh, bez přepočtu |

_patria.cz vyřazena — nemá žádné PXE / české silové kontrakty (jen NYMEX/IPE globální energie). Fallback investing.com/EEX nebyl potřeba._

## Elektřina base load CZ (front-year forward, PXE) — srovnání stará vs. nová

| CAL (rok dodávky) | ceny v roce | Q | stará | nová | odchylka % | pokrytí (dnů) | flag |
|---|---|---|---|---|---|---|---|
| CAL22   | 2021  | Q1  | 55     | **54.31** | -1.3     | 62     |                  |
|         |       | Q2  | 62     | **65.56** | +5.7     | 63     |                  |
|         |       | Q3  | 83     | **88.94** | +7.2     | 66     |                  |
|         |       | Q4  | 128    | **157.04** | +22.7    | 64     |                  |
| CAL23   | 2022  | Q1  | 125    | **149.26** | +19.4    | 65     |                  |
|         |       | Q2  | 185    | **227.42** | +22.9    | 63     |                  |
|         |       | Q3  | 360    | **463.59** | +28.8    | 65     | ⚠︎>25%           |
|         |       | Q4  | 255    | **350.66** | +37.5    | 64     | ⚠︎>25%           |
| CAL24   | 2023  | Q1  | 142    | **161.74** | +13.9    | 65     |                  |
|         |       | Q2  | 118    | **140.93** | +19.4    | 62     |                  |
|         |       | Q3  | 122    | **136.96** | +12.3    | 63     |                  |
|         |       | Q4  | 112    | **114.69** | +2.4     | 63     |                  |
| CAL25   | 2024  | Q1  | 76     | **81.89** | +7.8     | 63     |                  |
|         |       | Q2  | 81     | **94.75** | +17.0    | 64     |                  |
|         |       | Q3  | 92     | **94.96** | +3.2     | 66     |                  |
|         |       | Q4  | 96     | **95.5**  | -0.5     | 60     |                  |
| CAL26   | 2025  | Q1  | 95     | **94.88** | -0.1     | 64     |                  |
|         |       | Q2  | 88     | **94.02** | +6.8     | 62     |                  |
|         |       | Q3  | 84     | **94.39** | +12.4    | 66     |                  |
|         |       | Q4  | 88     | **94.66** | +7.6     | 60     |                  |

## Zemní plyn (PXE, front-year forward) — srovnání stará vs. nová

| CAL (rok dodávky) | ceny v roce | Q | stará | nová | odchylka % | pokrytí (dnů) | flag |
|---|---|---|---|---|---|---|---|
| CAL22   | 2021  | Q1  | 17     | **17.5**  | +2.9     | 62     |                  |
|         |       | Q2  | 21     | **21.43** | +2.0     | 63     |                  |
|         |       | Q3  | 33     | **33.63** | +1.9     | 66     |                  |
|         |       | Q4  | 55     | **65.48** | +19.1    | 63     |                  |
| CAL23   | 2022  | Q1  | 55     | **60.96** | +10.8    | 64     |                  |
|         |       | Q2  | 85     | **94.48** | +11.2    | 63     |                  |
|         |       | Q3  | 180    | **187.21** | +4.0     | 65     |                  |
|         |       | Q4  | 110    | **137.37** | +24.9    | 64     |                  |
| CAL24   | 2023  | Q1  | 55     | **63.23** | +15.0    | 65     |                  |
|         |       | Q2  | 48     | **55.54** | +15.7    | 61     |                  |
|         |       | Q3  | 52     | **55.37** | +6.5     | 64     |                  |
|         |       | Q4  | 46     | **48.68** | +5.8     | 63     |                  |
| CAL25   | 2024  | Q1  | 30     | **34.08** | +13.6    | 63     |                  |
|         |       | Q2  | 34     | **38.66** | +13.7    | 63     |                  |
|         |       | Q3  | 37     | **40.7**  | +10.0    | 66     |                  |
|         |       | Q4  | 40     | **44.15** | +10.4    | 63     |                  |
| CAL26   | 2025  | Q1  | —      | **40.76** | —        | 64     |                  |
|         |       | Q2  | —      | **36.88** | —        | 62     |                  |
|         |       | Q3  | —      | **35.26** | —        | 66     |                  |
|         |       | Q4  | —      | **31.85** | —        | 62     |                  |

## Surová denní data kvartálů s odchylkou > 25 %

_Kontrola, že nejde o chybu parsování. Kotva 59,98≈59,76 EUR potvrzuje správný produkt i měnu — vyšší hodnoty jsou reálný trh, ruční odhady krize byly zaokrouhlené konzervativně dolů._

**Elektřina base load CZ (front-year forward, PXE) — CAL23 Q3** (ceny v 2022): stará 360 → nová 463.59 EUR (+28.8 %)
- dnů: 65, min 323.30, max 984.00, Ø 463.59 EUR
- první: [['2022-07-03', 324.2], ['2022-07-04', 323.3], ['2022-07-05', 332.46]]  … poslední: [['2022-09-27', 490.38], ['2022-09-28', 451.8], ['2022-09-29', 442.44]]

**Elektřina base load CZ (front-year forward, PXE) — CAL23 Q4** (ceny v 2022): stará 255 → nová 350.66 EUR (+37.5 %)
- dnů: 64, min 217.00, max 428.64, Ø 350.66 EUR
- první: [['2022-10-02', 426.79], ['2022-10-03', 411.1], ['2022-10-04', 418.87]]  … poslední: [['2022-12-27', 241.98], ['2022-12-28', 230.0], ['2022-12-29', 217.0]]

## Dopad na backtest a citovaná čísla

### Elektřina

- Průměr strategií 2022–2025 (Kč/MWh, vč. marže):
  - **stará** data: spot 3510, transe 3514, mix 3718, fixQ4 3926
  - **nová** data: spot 3510, transe 4098, mix 4102, fixQ4 4693
  - pořadí strategií: beze změny (spot < transe < mix < fixQ4 → spot < transe < mix < fixQ4)
- „Fix na podzim vs. tranše": staré ~411 Kč/MWh (citováno **411**) → nové **595 Kč/MWh** (+44.6 %)

### Plyn

- Průměr strategií 2022–2025 (Kč/MWh, vč. marže):
  - **stará** data: spot 1613, transe 1658, mix 1716, fixQ4 1819
  - **nová** data: spot 1613, transe 1810, mix 1851, fixQ4 2089
  - pořadí strategií: beze změny (spot < transe < mix < fixQ4 → spot < transe < mix < fixQ4)
- „Fix na podzim vs. tranše": staré ~160 Kč/MWh (citováno **160**) → nové **279 Kč/MWh** (+73.8 %)

**Citovaná čísla, která po nasazení přestanou sedět:**
- `blog-kdy-fixovat-elektrinu.html`: **411 Kč/MWh** (rozdíl podzimní fix vs. tranše) — viz nová hodnota výše.
- `blog-cena-plynu-pro-firmy.html`: **~160 Kč/MWh (10 %)** — dtto pro plyn.
- Ticker / „férová rozmezí" v `index.html` jdou z `cal_now` (aktuální CAL27), ne z historie CAL → **beze změny**.
- KPI „rozdíl nejlepší vs. nejhorší strategie" v kalkulačce se přepočítá dynamicky z nových `cal`.

## Pokrytí — shrnutí

Všechny kvartály CAL22–CAL26 mají dost obchodních dnů (≥30). Žádný úsek nechybí; `pipeline/manual/cal_template.csv` nebyl potřeba.
