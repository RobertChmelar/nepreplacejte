#!/usr/bin/env node
/* =====================================================================
   test_app_scenarios.mjs — end-to-end scénáře kalkulačky
   ---------------------------------------------------------------------
   Spouští SKUTEČNÝ produkční assets/app.js (přes node:vm s minimálním
   DOM stubem) a prožene ho realistickými firemními scénáři: různé
   odběry, obě komodity, různé strategie nákupu. Ověřuje verdikt,
   férová rozmezí, přeplatky, KPI, doporučení i watch-list — tedy to,
   co uvidí návštěvník (a co odejde v leadu).

   Očekávané hodnoty jsou spočítané ručně z vestavěných dat (kurz 24,20):
     elektřina: Ø fixQ4 4 693,23 · tranše 4 098,28 · spot 3 510 · mix 4 101,62
     plyn:      Ø fixQ4 2 088,86 · tranše 1 810,19 · spot 1 612,68 · mix 1 850,77
     rozdíl fixQ4−tranše: ele 594,96 · plyn 278,68 Kč/MWh
     férově: ele 2 670–2 970 · plyn 1 094–1 294 Kč/MWh

   Spuštění:  node tests/test_app_scenarios.mjs   (exit != 0 při chybě)
   ===================================================================== */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

/* ---------------- minimální DOM stub ---------------- */
const registry = new Map();
function makeEl(id) {
  const classes = new Set();
  return {
    id, value: "", textContent: "", innerHTML: "", className: "",
    style: {}, dataset: {},
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      toggle: (c) => (classes.has(c) ? classes.delete(c) : classes.add(c)),
      contains: (c) => classes.has(c),
    },
    querySelectorAll: () => [], addEventListener: () => {},
    setAttribute: () => {}, scrollIntoView: () => {},
  };
}
const el = (id) => { if (!registry.has(id)) registry.set(id, makeEl(id)); return registry.get(id); };

const sandbox = {
  document: { getElementById: el, querySelectorAll: () => [] },
  window: {},
  fetch: () => Promise.reject(new Error("offline (test)")),
  setTimeout: () => 0,
  console, Math, Date, JSON,
};
vm.createContext(sandbox);
vm.runInContext(readFileSync(join(ROOT, "assets", "app.js"), "utf-8"), sandbox);

/* ---------------- helpery ---------------- */
const norm = (s) => String(s ?? "").replace(/[  ]/g, " ");
function run(scenario) {
  const { kom, typ = "fix", kdy = "q4", profil = "rovny", risk = "jistota",
          mwh, cena = "", om = 1 } = scenario;
  el("mwh").value = String(mwh);
  el("cena").value = cena === null || cena === "" ? "" : String(cena);
  el("om").value = String(om);
  vm.runInContext(
    `state.kom=${JSON.stringify(kom)};state.typ=${JSON.stringify(typ)};` +
    `state.kdy=${JSON.stringify(kdy)};state.profil=${JSON.stringify(profil)};` +
    `state.risk=${JSON.stringify(risk)};runAnalysis();`, sandbox);
  return {
    stamp: norm(el("stamp").textContent),
    verdict: norm(el("verdictTxt").innerHTML),
    kpis: norm(el("kpis").innerHTML),
    table: norm(el("stratTbl").innerHTML),
    reco: norm(el("reco").innerHTML),
    watch: norm(el("watchList").innerHTML),
    intro: norm(el("btIntro").textContent),
  };
}

let failures = [];
function expect(label, cond) { if (!cond) failures.push(label); }
function contains(hay, needle) { return hay.includes(needle); }

/* =====================================================================
   SCÉNÁŘE
   ===================================================================== */

/* 1) Malá výrobní firma — ele 50 MWh, drahý fix z podzimu (3 500 Kč) */
{
  const r = run({ kom: "ele", typ: "fix", kdy: "q4", risk: "jistota", mwh: 50, cena: 3500 });
  expect("S1 razítko PŘEPLÁCÍTE", r.stamp === "PŘEPLÁCÍTE");
  expect("S1 férové rozmezí 2 670–2 970", contains(r.verdict, "2 670–2 970"));
  expect("S1 přeplatek 26 500 Kč/rok ((3500−2970)×50)", contains(r.verdict, "26 500 Kč ročně"));
  expect("S1 timing +595 Kč/MWh", contains(r.verdict, "595 Kč/MWh dražší"));
  expect("S1 timing ~29 748 Kč/rok (595×50)", contains(r.verdict, "29 748 Kč/rok"));
  expect("S1 KPI 59 162 Kč/rok (nejlepší vs. nejhorší ×50)", contains(r.kpis, "59 162"));
  expect("S1 reco větev jistota", contains(r.reco, "jistý rozpočet"));
  expect("S1 reco tranše o 595 levněji", contains(r.reco, "595 Kč/MWh levněji"));
  expect("S1 watch prolongace", contains(r.watch, "Automatická prolongace"));
  expect("S1 watch bez multi-OM (om=1)", !contains(r.watch, "Více odběrných míst"));
}

/* 2) Střední e-shop/sklad — ele 200 MWh, spot za dobrou cenu, nakupuje průběžně */
{
  const r = run({ kom: "ele", typ: "spot", kdy: "rok", risk: "uspora", mwh: 200, cena: 2800 });
  expect("S2 razítko V POŘÁDKU", r.stamp === "V POŘÁDKU");
  expect("S2 cena ve férovém rozmezí", contains(r.verdict, "ve férovém rozmezí"));
  expect("S2 KPI 236 647 Kč/rok", contains(r.kpis, "236 647"));
  expect("S2 watch spotový poplatek (typ=spot)", contains(r.watch, "U spotu kontrolujte"));
  expect("S2 reco větev úspora/spot", contains(r.reco, "spot"));
}

/* 3) Velký odběratel — ele 2 000 MWh, bez zadané ceny, vyvážený profil */
{
  const r = run({ kom: "ele", typ: "nevim", kdy: "rok", risk: "mix", mwh: 2000, cena: null });
  expect("S3 razítko V POŘÁDKU", r.stamp === "V POŘÁDKU");
  expect("S3 verdikt bez ceny", contains(r.verdict, "Bez zadané ceny"));
  expect("S3 KPI 2 366 469 Kč/rok (×2000)", contains(r.kpis, "2 366 469"));
  expect("S3 nejlevnější = čistý spot", contains(r.table, 'class="best"') &&
         contains(r.table.split('class="best"')[1].slice(0, 120), "Čistý spot"));
  expect("S3 Ø spot 3 510 v tabulce", contains(r.table, "3 510"));
  expect("S3 Ø fixQ4 4 693 v tabulce", contains(r.table, "4 693"));
  expect("S3 roční náklad spotu 7 020 000 Kč", contains(r.table, "7 020 000"));
  expect("S3 reco větev kombinace", contains(r.reco, "kombinace fixu a spotu"));
}

/* 4) Pekárna — plyn 400 MWh, drahý fix (1 500 Kč), sezónní odběr */
{
  const r = run({ kom: "plyn", typ: "fix", kdy: "q4", profil: "sezona", mwh: 400, cena: 1500 });
  expect("S4 razítko PŘEPLÁCÍTE", r.stamp === "PŘEPLÁCÍTE");
  expect("S4 férové rozmezí 1 094–1 294", contains(r.verdict, "1 094–1 294"));
  expect("S4 přeplatek 82 400 Kč/rok ((1500−1294)×400)", contains(r.verdict, "82 400 Kč ročně"));
  expect("S4 timing +279 Kč/MWh", contains(r.verdict, "279 Kč/MWh dražší"));
  expect("S4 timing ~111 471 Kč/rok (279×400)", contains(r.verdict, "111 471 Kč/rok"));
  expect("S4 intro mluví o plynu", contains(r.intro, "plynu"));
  expect("S4 reco flexibilita objemu (sezona)", contains(r.reco, "flexibilitou objemu"));
  expect("S4 KPI 190 476 Kč/rok", contains(r.kpis, "190 476"));
}

/* 5) Menší plynový odběr — 80 MWh, cena férová, ale podpis na podzim */
{
  const r = run({ kom: "plyn", typ: "fix", kdy: "q4", mwh: 80, cena: 1200 });
  expect("S5 cena ve férovém rozmezí", contains(r.verdict, "ve férovém rozmezí"));
  expect("S5 přesto PŘEPLÁCÍTE (podzimní podpis)", r.stamp === "PŘEPLÁCÍTE");
  expect("S5 timing ~22 294 Kč/rok (279×80)", contains(r.verdict, "22 294 Kč/rok"));
}

/* 6) Vyjednaná cena pod trhem — ele 120 MWh, 2 400 Kč, 3 odběrná místa */
{
  const r = run({ kom: "ele", typ: "fix", kdy: "rok", mwh: 120, cena: 2400, om: 3 });
  expect("S6 razítko V POŘÁDKU", r.stamp === "V POŘÁDKU");
  expect("S6 cena pod tržním rozmezím", contains(r.verdict, "pod běžným tržním rozmezím"));
  expect("S6 watch multi-OM (om=3)", contains(r.watch, "Více odběrných míst"));
}

/* ---------------- výsledek ---------------- */
if (failures.length) {
  console.error("FAIL — " + failures.length + " scénářových kontrol:");
  failures.forEach((f) => console.error("  ✗ " + f));
  process.exit(1);
}
console.log("OK — 6 scénářů (ele 50/200/2000 MWh, plyn 80/400 MWh; fix/spot/tranše/kombinace), 34 kontrol prošlo.");
