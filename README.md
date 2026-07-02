# nepřeplácejte.cz

Statický web + datová pipeline + lead backend pro srovnávač nákupu energií
pro firmy. Frontend běží na **GitHub Pages**, denní data doplňuje **GitHub
Action**, leady zpracovává **Cloudflare Worker** (Google Sheets + Resend).

---

## 1. Architektura

```
index.html                 hlavní stránka (kalkulačka + backtest)
  ├─ assets/styles.css      vyčleněné CSS
  └─ assets/app.js          vyčleněná logika + loader data/data.json
blog.html, blog-*.html      blog (vlastní vložené styly — záměrně samostatné)
slovnik.html                slovník (vlastní vložené styly)
zasady-ochrany-udaju.html   GDPR šablona (doplňte texty)
favicon.svg, robots.txt, sitemap.xml, CNAME, .nojekyll

data/
  data.json                 tvar, který čte app.js (asof, eurczk, ele/gas, spot_today_czk)
  cal_history.csv           rostoucí denní historie CAL kotací (pro budoucí čtvrtletní Ø)

pipeline/
  update_data.py            denní stahování dat → data.json (+ cal_history.csv)
  backfill_cal.py           jednorázová rekonstrukce čtvrtletních CAL průměrů

tests/
  energy_model.py           Python replika backtestu (jediné místo pravdy pro testy)
  test_backtest.py          ověření proti ručním výpočtům (3 926 / 1 819 …)
  check_blog_consistency.py hlídač čísel citovaných v blozích

worker/
  src/index.js              Cloudflare Worker: /api/lead + /report/{token}
  wrangler.toml             konfigurace + KV binding
  package.json

.github/workflows/
  data.yml                  cron denně 14:30 UTC → update_data.py → commit
  tests.yml                 testy na push/PR do main
```

**Tok dat:** `update_data.py` (Action) → `data/data.json` → `app.js` loader
přepíše vestavěná fallback čísla → frontend. Když pipeline ještě neběžela
nebo data chybí, web funguje na vestavěných hodnotách (shodných s články).

**Konfigurační místa (marže a metodika — hodnoty neměňte bezdůvodně):**
- frontend: `CONFIG` na začátku `assets/app.js`
- Python: `MARGIN`, `FAIR_OFFSET`, `METHODOLOGY_EURCZK` v `tests/energy_model.py`
- Worker (jen vars): `worker/wrangler.toml`

Marže: elektřina fix **+350** / spot **+250**, plyn fix **+300** / spot **+200**
Kč/MWh. Metodický kurz **24,20** CZK/EUR (na něm stojí finální čísla v článcích).

---

## 2. Lokální spuštění

Čistě statické — stačí libovolný server:

```bash
python3 -m http.server 8000     # http://localhost:8000
```

`app.js` zkusí načíst `data/data.json` a živý spot z api.energy-charts.info;
bez nich spadne na vestavěná data.

---

## 3. Datová pipeline

`pipeline/update_data.py` (jen standardní knihovna, žádné závislosti) stahuje:

| Zdroj | Co | Kam |
|---|---|---|
| api.energy-charts.info `?bzn=CZ` | dnešní Ø + průběžný roční Ø denního trhu CZ | `spot_today_czk`, `ele.spot_y[letošní]` |
| ČNB denní kurz (txt) | EUR/CZK | `eurczk` |
| kurzovní lístek pxe.cz | settlement ročních CAL (elektřina BL + plyn) | `ele/gas.cal_now` + append `cal_history.csv` |

Každý zdroj má **fallback** na poslední známou hodnotu — skript nikdy neshodí
Action. Historická `cal` a `spot_y` (2021–2025) jsou finální a zachovávají se.

> **PXE:** veřejný strojově čitelný endpoint kurzovního lístku se mění; parser
> je „best effort“. Když nic nenačte, `cal_now` zůstane na poslední hodnotě a
> zaloguje se WARNING. Historii lze doplnit ručně přes `backfill_cal.py`.

**Spuštění ručně:**
```bash
python3 pipeline/update_data.py        # přepíše data/data.json
```

**Automaticky:** `.github/workflows/data.yml`, cron `30 14 * * *` (14:30 UTC).
Commitne změněné `data/data.json` + `data/cal_history.csv` do `main`.
Vyžaduje v repu povolené *Workflow permissions → Read and write*
(Settings → Actions → General).

### backfill_cal.py (jednorázově)

Rekonstruuje čtvrtletní CAL průměry roku Y-1 pro dodávkové roky 2022–2026 a
porovná je s hodnotami v kódu. Při odchylce > 15 % u kterékoli hodnoty se
zastaví (exit 2).

```bash
python3 pipeline/backfill_cal.py                 # zkusí archivy; když nic → vytvoří CSV šablonu
# vyplňte pipeline/cal_backfill_template.csv a pak:
python3 pipeline/backfill_cal.py --from-csv pipeline/cal_backfill_template.csv
```

---

## 4. Testy

```bash
python3 tests/test_backtest.py            # backtest vs. ruční výpočty
python3 tests/check_blog_consistency.py   # čísla v blozích vs. výpočet
```

Oba běží i v Actions (`tests.yml` na push/PR). `check_blog_consistency` je
navíc volán po denní aktualizaci dat (v `data.yml` jako neblokující upozornění).
Kontrolní body: elektřina Ø fixQ4 = **3 926**, plyn = **1 819**; rozdíly
fix-podzim vs. tranše **411** (ele) a **160** (plyn) Kč/MWh.

---

## 5. Worker pro leady (Cloudflare)

`worker/src/index.js`:
- `POST /api/lead` — CORS na doménu, honeypot, rate-limit (IP, KV), validace,
  uloží řádek do Google Sheets, pošle notifikaci + potvrzení (Resend),
  vygeneruje token, uloží report do KV, vrátí `{ ok, report_url }`.
- `GET /report/{token}` — privátní HTML report ve vizuálu protokolu (noindex).

### 5.1 Vytvoření KV a nasazení

```bash
cd worker
npm install
npx wrangler login

# KV namespace pro reporty + rate-limit
npx wrangler kv namespace create LEADS
npx wrangler kv namespace create LEADS --preview
# → vrácené id / preview_id vložte do worker/wrangler.toml (kv_namespaces)

npx wrangler deploy
```

### 5.2 Secrets — co a jak vytvořit

Nastavte přes `wrangler secret put` (běží ve složce `worker/`):

| Secret | Odkud |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_EMAIL` | Google Cloud → IAM → Service Accounts → e-mail účtu |
| `GOOGLE_PRIVATE_KEY` | z JSON klíče service accountu (pole `private_key`, vč. `\n`) |
| `GOOGLE_SHEET_ID` | ID z URL Google Sheetu (`/d/<ID>/edit`) |
| `RESEND_API_KEY` | Resend → API Keys |

```bash
npx wrangler secret put GOOGLE_SERVICE_ACCOUNT_EMAIL
npx wrangler secret put GOOGLE_PRIVATE_KEY
npx wrangler secret put GOOGLE_SHEET_ID
npx wrangler secret put RESEND_API_KEY
```

Necitlivé hodnoty (`ALLOWED_ORIGIN`, `FROM_EMAIL`, `NOTIFY_EMAIL`, limity, TTL)
jsou ve `wrangler.toml` v sekci `[vars]` — upravte podle sebe.

**Postup pro Google Sheets:**
1. Google Cloud Console → nový projekt → povolit **Google Sheets API**.
2. Vytvořit **Service Account** → klíč typu JSON (stáhne se soubor).
3. Vytvořit Google Sheet a **nasdílet ho e-mailu service accountu** (Editor).
4. Do prvního řádku dejte hlavičky (volitelné) v pořadí: datum, jméno, firma,
   e-mail, telefon, komodita, MWh, OM, typ, kdy, cena, verdikt, férové,
   fixQ4, tranše, spot, mix, úspora, souhlas, souhlas_ts, report_url.

**Resend:** ověřte odesílací doménu (SPF/DKIM) a nastavte `FROM_EMAIL` na
adresu v ověřené doméně (např. `report@nepreplacejte.cz`).

### 5.3 Propojení frontendu s workerem

V `index.html` (nad `assets/app.js`) je:
```html
<script>window.LEAD_ENDPOINT = "" || "/api/lead";</script>
```
Doplňte URL workeru, např.
`"https://nepreplacejte-lead.<účet>.workers.dev/api/lead"`, nebo nechte
`/api/lead` a worker nasměrujte na stejnou doménu přes Cloudflare route.
`ALLOWED_ORIGIN` ve `wrangler.toml` musí odpovídat doméně webu.

---

## 6. Nasazení na GitHub Pages + DNS

1. Push do repa (branch `main`).
2. **Settings → Pages** → Source: *Deploy from a branch* → Branch `main` / `/root`.
3. Soubor `CNAME` už obsahuje `nepreplacejte.cz`; v Pages se objeví jako Custom domain.
4. Zapněte **Enforce HTTPS** (až po propagaci DNS).

**DNS záznamy u registrátora:**

Apex `nepreplacejte.cz` — čtyři **A** záznamy na GitHub Pages:
```
A   @   185.199.108.153
A   @   185.199.109.153
A   @   185.199.110.153
A   @   185.199.111.153
```
(volitelně IPv6 AAAA: 2606:50c0:8000::153, ::8001::153, ::8002::153, ::8003::153)

`www` — **CNAME** na GitHub Pages hostname:
```
CNAME   www   <vaše-github-jméno>.github.io.
```

Po propagaci ověří GitHub doménu a vydá TLS certifikát (Enforce HTTPS).

---

## 7. Checklist prvního spuštění

- [ ] `git init` (pokud ještě není) a první commit všech souborů.
- [ ] Push do GitHub repa `nepreplacejte` (branch `main`).
- [ ] Settings → Pages: branch `main`, root; ověřit Custom domain z `CNAME`.
- [ ] Nastavit DNS (A × 4 na apex, CNAME `www`); počkat na propagaci; Enforce HTTPS.
- [ ] Settings → Actions → General → **Read and write permissions** (kvůli commitu dat).
- [ ] Spustit `tests/*` lokálně — musí projít (3 926 / 1 819).
- [ ] Ručně spustit workflow **Aktualizace tržních dat** (Actions → Run workflow)
      a ověřit commit `data/data.json`.
- [ ] Worker: `wrangler kv namespace create LEADS` → doplnit id do `wrangler.toml`.
- [ ] Worker: nastavit 4 secrets; `wrangler deploy`.
- [ ] Doplnit `window.LEAD_ENDPOINT` v `index.html` na URL workeru.
- [ ] Vytvořit Google Sheet, nasdílet service accountu, ověřit Resend doménu.
- [ ] Otestovat odeslání formuláře → řádek v Sheetu + 2 e-maily + `/report/{token}`.
- [ ] Vyplnit `zasady-ochrany-udaju.html` (údaje správce, lhůty) — dát zkontrolovat.
- [ ] (Jednorázově) `backfill_cal.py` pro ověření CAL rekonstrukce.

---

## Poznámky

- Vizuál, texty, metodika a čísla v článcích jsou finální — pipeline je nemění.
- `data/cal_history.csv` roste; z něj se budou počítat budoucí čtvrtletní CAL Ø.
- Live spot v horní liště se načítá přímo v prohlížeči z api.energy-charts.info
  (CC BY 4.0); pipeline slouží pro perzistentní denní snapshot.
