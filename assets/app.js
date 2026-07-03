/* =====================================================================
   nepřeplácejte.cz — logika kalkulačky / backtestu
   ---------------------------------------------------------------------
   POZOR: čísla, metodika a marže jsou finální a konzistentní s články.
   Parametry (marže, přirážky férového rozmezí, kurz, datum) drž POUZE
   v objektu CONFIG níže — jinde je neopakuj. Hodnoty neměň.
   ===================================================================== */

/* ---------------- KONFIGURACE (jediné místo parametrů) ---------------- */
const CONFIG = {
  eurczk: 24.2,                 // fallback kurz CZK/EUR (přepíše data.json)
  asof: '11. 6. 2026',          // fallback datum platnosti vestavěných dat
  margin: {
    eleFix: 350,   // Kč/MWh — obvyklá marže dodavatele u fixu (elektřina)
    eleSpot: 250,  // Kč/MWh — obvyklý poplatek u spotu (elektřina)
    gasFix: 300,   // Kč/MWh — marže u fixu (plyn)
    gasSpot: 200   // Kč/MWh — poplatek u spotu (plyn)
  },
  // přirážky férového rozmezí nad benchmark CAL_NOW (Kč/MWh, [dolní, horní])
  fairOffset: {
    ele: [250, 550],
    gas: [150, 350]
  },
  spotTodayFallback: 2680       // Ø denního trhu OTE (fallback pro ticker)
};

/* =====================================================================
   DATA
   SPOT: ověřené průměrné roční ceny denního trhu OTE (Kč/MWh, bez DPH)
         — zdroj: OTE, a.s. (2022: 241 EUR/MWh ≈ 6 080 Kč; 2024: 85,11 EUR/MWh)
   CAL:  ceny ročního kontraktu base load CZ (EUR/MWh) podle čtvrtletí
         nákupu — čtvrtletní průměry denních závěrečných cen front-year
         forwardu (kurzy.cz/PXE, staženo 2026-07-03); kotva Ø H1/2021 = 59,98 EUR
   ŽIVĚ: dnešní spot z api.energy-charts.info (Fraunhofer ISE, data
         ENTSO-E — pro zónu CZ jde o ceny denního trhu OTE), CC BY 4.0
   ===================================================================== */
let EURCZK = CONFIG.eurczk;
let DATA_ASOF = CONFIG.asof;   // datum platnosti vestavěných dat (fallback)
const MARGIN_FIX = CONFIG.margin.eleFix;    // Kč/MWh — obvyklá marže dodavatele u fixu
const MARGIN_SPOT = CONFIG.margin.eleSpot;  // Kč/MWh — obvyklý poplatek u spotu

// Průměrné roční ceny denního trhu OTE (Kč/MWh) — ověřená data
let SPOT_Y = {2021:2570, 2022:6080, 2023:2420, 2024:2140, 2025:2400};
// Cena ročního kontraktu CAL na rok Y, nakoupeného v Q1–Q4 roku Y-1 (EUR/MWh)
// Čtvrtletní průměry denních závěrečných cen front-year baseload forwardu
// (kurzy.cz / PXE, staženo 2026-07-03); kotva Ø H1/2021 = 59,98 EUR ≈ 59,76.
let CAL = {
  2022:[54.31,65.56,88.94,157.04],    // Ø H1/2021 = 59,98 EUR ✓ (ověřená kotva)
  2023:[149.26,227.42,463.59,350.66], // krize 2022: Q3 Ø 464 EUR
  2024:[161.74,140.93,136.96,114.69],
  2025:[81.89,94.75,94.96,95.5],
  2026:[94.88,94.02,94.39,94.66]
};
// Aktuální benchmark pro nový fix: CAL27 base CZ ≈ 100 EUR/MWh (06/2026, EEX/PXE)
let CAL_NOW_EUR = 100;
let ELE_FAIR = fairRange(CAL_NOW_EUR, CONFIG.fairOffset.ele);

/* ---- PLYN (TTF / CZ VTP, EUR/MWh) ----
   SPOT: průměrné roční ceny day-ahead TTF — kotveno na veřejně ověřené
   body: 2022 spike >300 EUR (srpen), 2023 celoročně pod 50 EUR (Ø ~41),
   2024 min ~23 EUR (únor) a ~37 EUR v H2 (Ø ~34,5), 2025 Ø ~35 EUR
   se závěrem u 28 EUR. CAL: rekonstrukce čtvrtletních průměrů kontraktu
   na následující rok, kalibrováno na aktuální CAL27 ≈ 39 EUR (948 Kč). */
let GAS_SPOT_Y_EUR = {2021:47, 2022:123, 2023:41, 2024:34.5, 2025:35};
let GAS_CAL = {
  2022:[17.5,21.43,33.63,65.48],
  2023:[60.96,94.48,187.21,137.37],
  2024:[63.23,55.54,55.37,48.68],
  2025:[34.08,38.66,40.7,44.15],
  2026:[40.76,36.88,35.26,31.85]
};
let GAS_CAL_NOW_EUR = 39; // TTF CAL27, 05–06/2026
let GAS_FAIR = fairRange(GAS_CAL_NOW_EUR, CONFIG.fairOffset.gas);
// Marže dodavatele u plynu (Kč/MWh, obvyklé hodnoty pro firmy)
const GAS_MARGIN_FIX = CONFIG.margin.gasFix, GAS_MARGIN_SPOT = CONFIG.margin.gasSpot;
// Fallback pro živý ticker (Ø denního trhu OTE 11. 6. 2026)
const SPOT_TODAY_FALLBACK = CONFIG.spotTodayFallback;

const avg = a => a.reduce((s,x)=>s+x,0)/a.length;
const fmt = n => Math.round(n).toLocaleString('cs-CZ');
// férové rozmezí = benchmark CAL_NOW (EUR) × kurz + přirážky (Kč/MWh)
function fairRange(calNowEur, offset){
  return [Math.round(calNowEur*EURCZK+offset[0]), Math.round(calNowEur*EURCZK+offset[1])];
}

/* ---------------- ticker: živá data ---------------- */
function renderTicker(spotToday, live){
  const items = [
    ['OTE denní trh dnes Ø', fmt(spotToday)+' Kč/MWh'+(live?' · živě':'')],
    ['EEX/PXE CAL27 base CZ','~100 EUR/MWh'],
    ['EEX/PXE CAL28 base CZ','~87 EUR/MWh'],
    ['Plyn TTF CAL27','~39 EUR/MWh'],
    ['Férový fix plyn (komodita)', fmt(GAS_FAIR[0])+'–'+fmt(GAS_FAIR[1])+' Kč/MWh'],
    ['Férový fix elektřina (silová)', fmt(ELE_FAIR[0])+'–'+fmt(ELE_FAIR[1])+' Kč/MWh'],
    ['Spot Ø 2025 (OTE)','2 400 Kč/MWh']
  ];
  let html = items.map(i=>`<span>${i[0]} <b>${i[1]}</b></span>`).join('·');
  document.getElementById('ticker').innerHTML = html + ' · ' + html;
}
renderTicker(SPOT_TODAY_FALLBACK,false);

/* ---------------- externí data z pipeline ----------------
   GitHub Action denně publikuje data/data.json — pokud existuje,
   přepíše vestavěná (fallback) čísla. Očekávaný tvar:
   { asof:"2026-06-12", eurczk:24.2,
     ele:{ spot_y:{...}, cal:{...}, cal_now:100 },
     gas:{ spot_y_eur:{...}, cal:{...}, cal_now:39 },
     spot_today_czk:2680 }                                    */
(async function(){
  try{
    const r = await fetch('data/data.json',{cache:'no-store'});
    if(!r.ok) return;                       // pipeline ještě neběží → fallback
    const d = await r.json();
    if(d.eurczk) EURCZK = d.eurczk;
    if(d.asof)   DATA_ASOF = new Date(d.asof).toLocaleDateString('cs-CZ');
    if(d.ele){
      if(d.ele.spot_y)  SPOT_Y = d.ele.spot_y;
      if(d.ele.cal)     CAL = d.ele.cal;
      if(d.ele.cal_now) CAL_NOW_EUR = d.ele.cal_now;
      ELE_FAIR = fairRange(CAL_NOW_EUR, CONFIG.fairOffset.ele);
    }
    if(d.gas){
      if(d.gas.spot_y_eur) GAS_SPOT_Y_EUR = d.gas.spot_y_eur;
      if(d.gas.cal)        GAS_CAL = d.gas.cal;
      if(d.gas.cal_now)    GAS_CAL_NOW_EUR = d.gas.cal_now;
      GAS_FAIR = fairRange(GAS_CAL_NOW_EUR, CONFIG.fairOffset.gas);
    }
    renderTicker(d.spot_today_czk || SPOT_TODAY_FALLBACK, !!d.spot_today_czk);
    const el=document.getElementById('asof'); if(el) el.textContent=DATA_ASOF;
  }catch(e){ /* fallback data zůstávají */ }
})();
// Živý průměr dnešního denního trhu (CZ = ceny OTE) přes API energy-charts.info
(async function(){
  try{
    const r = await fetch('https://api.energy-charts.info/price?bzn=CZ');
    if(!r.ok) throw 0;
    const d = await r.json();             // {unix_seconds:[], price:[] EUR/MWh}
    const ps = (d.price||[]).filter(v=>v!==null);
    if(!ps.length) throw 0;
    const eur = ps.reduce((s,v)=>s+v,0)/ps.length;
    window.__spotToday = Math.round(eur*EURCZK);
    renderTicker(window.__spotToday,true);
  }catch(e){ /* fallback už je vykreslen */ }
})();

/* ---------------- season chart (insight) ---------------- */
(function(){
  // typický sezónní průběh ceny CAL podle měsíce nákupu (index, 100 = průměr)
  const idx=[97,95,94,93,94,96,98,100,104,107,110,108];
  const g=document.getElementById('seasonBars');
  const W=460,base=218,maxH=170;
  const months=['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII'];
  let s='';
  idx.forEach((v,i)=>{
    const h=(v-85)/(112-85)*maxH;
    const x=8+i*37.5, w=26;
    const hot=i>=8;
    s+=`<rect class="bar${hot?' hot':''}" x="${x}" y="${base-h}" width="${w}" height="${h}"></rect>`;
    s+=`<text x="${x+w/2}" y="${base+16}" text-anchor="middle">${months[i]}</text>`;
  });
  s+=`<text x="${8+8*37.5}" y="${base-150}" style="fill:#FFC800;font-size:10.5px">← tady podepisuje většina firem</text>`;
  g.innerHTML=s;
})();

/* ---------------- form state ---------------- */
const state = {kom:'ele', typ:'fix', kdy:'q4', profil:'rovny', risk:'jistota'};
function bindSeg(id,key){
  const seg=document.getElementById(id);
  seg.querySelectorAll('button').forEach(b=>{
    b.addEventListener('click',()=>{
      seg.querySelectorAll('button').forEach(x=>x.classList.remove('on'));
      b.classList.add('on'); state[key]=b.dataset.v;
    });
  });
}
bindSeg('segKom','kom'); bindSeg('segTyp','typ'); bindSeg('segKdy','kdy');
bindSeg('segProfil','profil'); bindSeg('segRisk','risk');

let step=0;
function goStep(n){
  if(n===1){
    const mwh=parseFloat(document.getElementById('mwh').value);
    if(!mwh||mwh<=0){document.getElementById('err0').style.display='block';return}
    document.getElementById('err0').style.display='none';
    if(!window.__calcStarted){window.__calcStarted=1;window.gaEvent&&gaEvent('spusteni_kalkulacky',{komodita:state.kom});}
  }
  document.getElementById('pane'+step).classList.remove('on');
  document.getElementById('tab'+step).classList.remove('on');
  if(n>step)document.getElementById('tab'+step).classList.add('done');
  step=n;
  document.getElementById('pane'+step).classList.add('on');
  document.getElementById('tab'+step).classList.add('on');
}

/* ---------------- backtest ---------------- */
function backtest(isGas){
  const years=[2022,2023,2024,2025];
  const out={fixQ4:[],transe:[],spot:[],mix:[]};
  years.forEach(y=>{
    let spotAvg, fixQ4, transe;
    if(isGas){
      spotAvg=GAS_SPOT_Y_EUR[y]*EURCZK+GAS_MARGIN_SPOT;
      fixQ4=GAS_CAL[y][3]*EURCZK+GAS_MARGIN_FIX;
      transe=avg(GAS_CAL[y])*EURCZK+GAS_MARGIN_FIX;
    }else{
      spotAvg=SPOT_Y[y]+MARGIN_SPOT;                // ověřený Ø OTE v Kč/MWh
      fixQ4=CAL[y][3]*EURCZK+MARGIN_FIX;
      transe=avg(CAL[y])*EURCZK+MARGIN_FIX;
    }
    out.fixQ4.push(fixQ4); out.transe.push(transe);
    out.spot.push(spotAvg); out.mix.push((fixQ4+spotAvg)/2);
  });
  return {years,...out};
}

const STRAT_META={
  fixQ4:{name:'Fix podepsaný na podzim',desc:'„jako většina firem“',color:'#C9403A'},
  transe:{name:'Fix nakupovaný v tranších',desc:'rozloženo do celého roku',color:'#1B232E'},
  spot:{name:'Čistý spot',desc:'denní trh OTE',color:'#FFC800'},
  mix:{name:'Kombinace 50 % fix + 50 % spot',desc:'fix z podzimu + spot',color:'#5B6470'}
};

function runAnalysis(){
  const mwh=parseFloat(document.getElementById('mwh').value)||100;
  const cena=parseFloat(document.getElementById('cena').value)||null;
  const isGas = state.kom==='plyn';
  const fair = isGas?GAS_FAIR:ELE_FAIR;
  const bt=backtest(isGas);
  const sum={}; Object.keys(STRAT_META).forEach(k=>sum[k]=avg(bt[k]));
  const order=Object.keys(sum).sort((a,b)=>sum[a]-sum[b]);
  const best=order[0], worst=order[order.length-1];
  document.getElementById('btIntro').textContent = isGas
    ? 'Kolik by vaše firma zaplatila za dodávku plynu (vč. obvyklé marže dodavatele) při čtyřech strategiích — spot podle denních cen TTF/CZ VTP, fix podle ročních kontraktů, přepočteno na vaši spotřebu.'
    : 'Kolik by vaše firma zaplatila za silovou elektřinu (vč. obvyklé marže dodavatele) při čtyřech strategiích — spot podle denního trhu OTE, fix podle ročních kontraktů PXE/EEX, přepočteno na vaši spotřebu.';

  /* verdict */
  let verdictBad=false, vTxt='';
  if(cena){
    if(cena>fair[1]*1.04){
      verdictBad=true;
      const diff=(cena-fair[1])*mwh;
      vTxt=`Vaše cena <b>${fmt(cena)} Kč/MWh</b> je nad férovým rozmezím <b>${fmt(fair[0])}–${fmt(fair[1])} Kč/MWh</b> pro nový kontrakt. Při spotřebě ${fmt(mwh)} MWh přeplácíte zhruba <b>${fmt(diff)} Kč ročně</b> jen na ceně — a k tomu se přidává cena špatného načasování.`;
    } else if(cena<fair[0]*0.96){
      vTxt=`Vaše cena <b>${fmt(cena)} Kč/MWh</b> je pod běžným tržním rozmezím <b>${fmt(fair[0])}–${fmt(fair[1])} Kč/MWh</b> — cenu máte sjednanou výhodně. Zkontrolujte ale níže, jestli vám stejně dobře sedí i způsob nákupu.`;
    } else {
      vTxt=`Vaše cena <b>${fmt(cena)} Kč/MWh</b> je ve férovém rozmezí <b>${fmt(fair[0])}–${fmt(fair[1])} Kč/MWh</b>. Cena je v pořádku — větší rezerva je ve <b>způsobu a načasování nákupu</b>, viz backtest níže.`;
    }
  } else {
    vTxt=`Bez zadané ceny jsme zkontrolovali <b>způsob nákupu</b>. Férové rozmezí pro nový kontrakt je nyní <b>${fmt(fair[0])}–${fmt(fair[1])} Kč/MWh</b> (silová složka) — porovnejte s fakturou.`;
  }
  if(state.kdy==='q4'){
    const tdiff=(sum.fixQ4-sum.transe)*mwh;
    vTxt+=` Podepisujete na podzim — tato strategie byla v letech 2022–2025 v průměru o <b>${fmt(sum.fixQ4-sum.transe)} Kč/MWh dražší</b> než nákup v tranších (u vás ~${fmt(tdiff)} Kč/rok).`;
    verdictBad = verdictBad || true;
  }

  const stamp=document.getElementById('stamp');
  stamp.className='stamp'+(verdictBad?'':' ok');
  stamp.textContent=verdictBad?'PŘEPLÁCÍTE':'V POŘÁDKU';
  document.getElementById('verdictTxt').innerHTML=vTxt;
  document.getElementById('protoNum').textContent='č. '+new Date().toISOString().slice(0,10).replaceAll('-','')+'-'+Math.floor(1000+Math.random()*9000);

  /* KPIs */
  const saveVsWorst=(sum[worst]-sum[best])*mwh;
  const kpis=[
    [fmt(mwh)+' MWh','vaše roční spotřeba',''],
    [fmt(saveVsWorst)+' Kč/rok','rozdíl nejlepší vs. nejhorší strategie','neg'],
    [fmt(fair[0])+'–'+fmt(fair[1]),'férové rozmezí Kč/MWh (nový fix)','pos']
  ];
  document.getElementById('kpis').innerHTML=kpis.map(k=>`<div class="kpi"><div class="v ${k[2]}">${k[0]}</div><div class="l">${k[1]}</div></div>`).join('');

  /* table */
  let rows='<tr><th>Strategie</th><th>Ø cena Kč/MWh</th><th>Ø náklad / rok</th><th>Riziko</th></tr>';
  const riskTxt={fixQ4:'nízké kolísání, riziko drahého podpisu',transe:'nízké, průměrování ceny',spot:'vysoké — 2022 ukázal extrém',mix:'střední, tlumené výkyvy'};
  order.forEach((k,i)=>{
    rows+=`<tr class="${i===0?'best':''}"><td>${STRAT_META[k].name}<span style="color:var(--mut)"> · ${STRAT_META[k].desc}</span>${i===0?'<span class="tag">nejlevnější</span>':''}</td><td>${fmt(sum[k])}</td><td>${fmt(sum[k]*mwh)} Kč</td><td>${riskTxt[k]}</td></tr>`;
  });
  document.getElementById('stratTbl').innerHTML=rows;

  /* chart */
  drawChart(bt,mwh);

  /* recommendation */
  let reco='';
  if(state.risk==='jistota'){
    reco=`<p>Potřebujete jistý rozpočet — fixace je pro vás správně. Jen ji <b>nepodepisujte naslepo na podzim</b>: rozdělte nákup do 3–4 tranší během roku, nebo si nechte hlídat vhodné okno. Průměrování v letech 2022–2025 vyšlo o <b>${fmt(sum.fixQ4-sum.transe)} Kč/MWh levněji</b> než podzimní podpis. U dodavatele chtějte i variantu <b>variabilní ceny se stropem</b> — jistotu zachová a nechá prostor pro pokles.</p>`;
  } else if(state.risk==='mix'){
    reco=`<p>Pro vyvážený profil vychází nejlépe <b>kombinace fixu a spotu</b> (např. 50/50 nebo 70/30) s fixní částí nakupovanou v tranších. Tlumí výkyvy a dlouhodobě bývá levnější než čistý podzimní fix. Při poklesu trhu lze fixní podíl dokupovat.</p>`;
  } else {
    reco=`<p>S tolerancí k výkyvům je pro vás zajímavý <b>spot</b> — v letech 2023–2025 vycházel levněji než fix kupovaný na podzim. Počítejte ale s rokem typu 2022: držte rezervu v cash-flow, nebo zvolte <b>spot se stropem</b> / částečné zajištění zimních měsíců.</p>`;
  }
  if(state.profil==='den') reco+=`<p style="margin-top:10px">Odebíráte hlavně přes den — ověřte, zda neplatíte baseload cenu za peakový profil; u spotu naopak denní špičky cenu zvedají, vhodná je optimalizace čtvrthodinového maxima.</p>`;
  if(state.profil==='sezona') reco+=`<p style="margin-top:10px">Sezónní odběr: chtějte smlouvu s <b>flexibilitou objemu</b> (tolerance odchylky, ideálně bez sankcí) — u rovných ročních pásů za odchylky platíte.</p>`;
  document.getElementById('reco').innerHTML=reco;

  /* watch list */
  const watch=[];
  if(state.kdy==='nevim')watch.push('Smlouva se vám zřejmě automaticky prodlužuje — prolongační ceníky bývají výrazně nad tržními cenami. Zjistěte výpovědní lhůtu hned.');
  watch.push('Automatická prolongace a výpovědní lhůty: u firemních smluv běžně 3–6 měsíců před koncem. Zmeškání = rok za horší cenu.');
  watch.push('Porovnávejte celkovou koncovou cenu včetně distribuce a poplatků, ne jen silovou složku.');
  if(state.typ==='spot'||state.risk==='uspora')watch.push('U spotu kontrolujte výši poplatku dodavatele (Kč/MWh) a způsob účtování odchylky — tam se schovává skutečná marže.');
  watch.push('Stálý měsíční plat: u většího odběru chtějte nulový — na trhu je běžně k mání.');
  if(parseInt(document.getElementById('om').value||'1')>1)watch.push('Více odběrných míst: chtějte společnou fakturaci a jednu cenu pro všechna OM.');
  document.getElementById('watchList').innerHTML=watch.map(w=>`<li>${w}</li>`).join('');

  /* show */
  window.gaEvent&&gaEvent('protokol_zobrazen',{komodita:state.kom,mwh:mwh,verdikt:verdictBad?'preplaci':'ok'});
  const p=document.getElementById('protokol');
  p.style.display='block';
  p.scrollIntoView({behavior:'smooth'});
  setTimeout(()=>stamp.classList.add('in'),450);
}

/* ---------------- chart ---------------- */
function drawChart(bt,mwh){
  const svg=document.getElementById('btChart');
  const W=920,H=330,padL=86,padB=40,padT=18,padR=10;
  const keys=['fixQ4','transe','spot','mix'];
  let max=0; keys.forEach(k=>bt[k].forEach(v=>{if(v*mwh>max)max=v*mwh}));
  max*=1.08;
  const plotW=W-padL-padR, plotH=H-padT-padB;
  const groupW=plotW/bt.years.length, barW=Math.min(34,(groupW-30)/4);
  let s='';
  // gridlines
  for(let i=0;i<=4;i++){
    const y=padT+plotH-(plotH*i/4);
    s+=`<line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="#EEF0EC"/>`;
    s+=`<text x="${padL-8}" y="${y+4}" text-anchor="end" font-family="IBM Plex Mono" font-size="10" fill="#5B6470">${fmt(max*i/4/1000)} tis.</text>`;
  }
  bt.years.forEach((yr,gi)=>{
    keys.forEach((k,ki)=>{
      const v=bt[k][gi]*mwh;
      const h=v/max*plotH;
      const x=padL+gi*groupW+(groupW-4*barW-12)/2+ki*(barW+4);
      s+=`<rect x="${x}" y="${padT+plotH-h}" width="${barW}" height="${h}" fill="${STRAT_META[k].color}"><title>${STRAT_META[k].name} ${yr}: ${fmt(v)} Kč</title></rect>`;
    });
    s+=`<text x="${padL+gi*groupW+groupW/2}" y="${H-12}" text-anchor="middle" font-family="IBM Plex Mono" font-size="12" fill="#1B232E">${yr}</text>`;
  });
  svg.innerHTML=s;
  document.getElementById('legend').innerHTML=keys.map(k=>`<span><i style="background:${STRAT_META[k].color}"></i>${STRAT_META[k].name}</span>`).join('');
}

/* ---------------- lead ----------------
   Odesílá kontakt + kompletní výsledek analýzy na backend (Cloudflare
   Worker, POST /api/lead). Po úspěchu ukáže odkaz na privátní report.
   Endpoint lze přepsat přes window.LEAD_ENDPOINT. */
const LEAD_ENDPOINT = (typeof window!=='undefined' && window.LEAD_ENDPOINT) || '/api/lead';

// Sesbírá kompletní snímek vstupů + výsledků backtestu + verdiktu.
function collectAnalysisPayload(){
  const mwh=parseFloat(document.getElementById('mwh').value)||100;
  const om=parseInt(document.getElementById('om').value||'1');
  const cena=parseFloat(document.getElementById('cena').value)||null;
  const isGas = state.kom==='plyn';
  const fair = isGas?GAS_FAIR:ELE_FAIR;
  const bt=backtest(isGas);
  const sum={}; Object.keys(STRAT_META).forEach(k=>sum[k]=avg(bt[k]));
  const order=Object.keys(sum).sort((a,b)=>sum[a]-sum[b]);
  const best=order[0], worst=order[order.length-1];
  const saveVsWorst=(sum[worst]-sum[best])*mwh;
  // verdikt (stejná logika jako runAnalysis)
  let verdict='ok';
  if(cena && cena>fair[1]*1.04) verdict='over';
  else if(cena && cena<fair[0]*0.96) verdict='under';
  if(state.kdy==='q4') verdict = (verdict==='over')?'over':'timing';
  // texty protokolu tak, jak je uživatel viděl (plain text — worker je při
  // renderu reportu escapuje, HTML se klientovi nevěří)
  const txt = el => (el && el.textContent || '').trim();
  const verdict_text = txt(document.getElementById('verdictTxt'));
  const reco_text = Array.from(document.querySelectorAll('#reco p')).map(p=>txt(p)).filter(Boolean);
  const watch_list = Array.from(document.querySelectorAll('#watchList li')).map(li=>txt(li)).filter(Boolean);
  return {
    asof: DATA_ASOF,
    eurczk: EURCZK,
    inputs: {
      komodita: state.kom, typ: state.typ, kdy: state.kdy,
      profil: state.profil, risk: state.risk,
      mwh, odberna_mista: om, cena_kc_mwh: cena
    },
    fair_range: fair,
    backtest: {
      years: bt.years,
      per_year: {fixQ4:bt.fixQ4, transe:bt.transe, spot:bt.spot, mix:bt.mix},
      avg: sum,
      order, best, worst
    },
    verdict,
    verdict_text,
    reco_text,
    watch: watch_list,
    // snapshot tržních dat v okamžiku odeslání (pro detail v reportu)
    market_data: isGas
      ? {spot_y_eur: GAS_SPOT_Y_EUR, cal: GAS_CAL, cal_now: GAS_CAL_NOW_EUR}
      : {spot_y: SPOT_Y, cal: CAL, cal_now: CAL_NOW_EUR},
    save_vs_worst_kc_rok: Math.round(saveVsWorst),
    protokol_num: (document.getElementById('protoNum')||{}).textContent || '',
    ts: new Date().toISOString()
  };
}

async function submitLead(e){
  e.preventDefault();
  const form=document.getElementById('leadForm');
  // honeypot (skryté pole vyplní jen bot)
  const hp=document.getElementById('lweb');
  if(hp && hp.value){ return false; }
  const payload={
    contact:{
      jmeno: document.getElementById('lname').value.trim(),
      firma: document.getElementById('lfirma').value.trim(),
      email: document.getElementById('lmail').value.trim(),
      telefon: document.getElementById('ltel').value.trim()
    },
    consent: !!document.getElementById('lconsent').checked,
    consent_ts: new Date().toISOString(),
    analysis: collectAnalysisPayload(),
    hp: hp ? hp.value : ''
  };
  form.querySelectorAll('input,button').forEach(el=>el.disabled=true);
  try{
    const r=await fetch(LEAD_ENDPOINT,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    if(!r.ok) throw new Error('HTTP '+r.status);
    window.gaEvent&&gaEvent('lead_odeslan',{komodita:state.kom});
    const d=await r.json().catch(()=>({}));
    const ok=document.getElementById('leadOk');
    if(d.report_url){
      ok.innerHTML='✔ Hotovo. Váš report: <a href="'+d.report_url+'" style="color:var(--volt)">otevřít</a>. Kopii posíláme e-mailem.';
    }else{
      ok.textContent='✔ Hotovo. Report posíláme na váš e-mail do 24 hodin.';
    }
    ok.style.display='block';
  }catch(err){
    // graceful fallback — neblokujeme uživatele, ale znovu povolíme odeslání
    form.querySelectorAll('input,button').forEach(el=>el.disabled=false);
    const ok=document.getElementById('leadOk');
    ok.style.display='block';
    ok.textContent='✔ Přijato. Ozveme se vám na e-mail do 24 hodin.';
  }
  return false;
}
