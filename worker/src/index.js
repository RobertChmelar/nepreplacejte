/* =====================================================================
   nepřeplácejte.cz — Lead Worker (Cloudflare)
   ---------------------------------------------------------------------
   POST /api/lead        přijme kontakt + kompletní výsledek analýzy:
                         · honeypot + rate-limit + kontrola originu (CORS)
                         · uloží řádek do Google Sheets (service account)
                         · pošle notifikaci majiteli + potvrzení uživateli
                           (Resend)
                         · vygeneruje token, uloží report do KV a vrátí
                           { ok:true, report_url }
   GET  /report/{token}  privátní HTML report ve vizuálu kontrolního
                         protokolu z index.html
   ---------------------------------------------------------------------
   Tajné klíče (wrangler secret put): GOOGLE_SERVICE_ACCOUNT_EMAIL,
   GOOGLE_PRIVATE_KEY, GOOGLE_SHEET_ID, RESEND_API_KEY.
   Veřejné vars ve wrangler.toml: ALLOWED_ORIGIN, FROM_EMAIL, NOTIFY_EMAIL,
   RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, REPORT_TTL_DAYS.
   ===================================================================== */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") return cors(env, new Response(null, { status: 204 }));

    if (url.pathname === "/api/lead" && request.method === "POST") {
      return cors(env, await handleLead(request, env, ctx));
    }
    if (url.pathname.startsWith("/report/") && request.method === "GET") {
      return handleReport(url, env); // report je HTML, bez CORS hlaviček
    }
    if (url.pathname === "/" || url.pathname === "/api/health") {
      return new Response("nepreplacejte-lead: OK", { status: 200 });
    }
    return new Response("Not found", { status: 404 });
  },
};

/* ---------------------------------- CORS ---------------------------------- */
function cors(env, resp) {
  const h = new Headers(resp.headers);
  h.set("Access-Control-Allow-Origin", env.ALLOWED_ORIGIN || "*");
  h.set("Access-Control-Allow-Methods", "POST, OPTIONS");
  h.set("Access-Control-Allow-Headers", "Content-Type");
  h.set("Vary", "Origin");
  return new Response(resp.body, { status: resp.status, headers: h });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

/* ------------------------------- /api/lead -------------------------------- */
async function handleLead(request, env, ctx) {
  // kontrola originu
  const origin = request.headers.get("Origin") || "";
  if (env.ALLOWED_ORIGIN && origin && origin !== env.ALLOWED_ORIGIN) {
    return json({ ok: false, error: "origin" }, 403);
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "bad_json" }, 400);
  }

  // honeypot — když je vyplněný, tváříme se úspěšně a tiše zahodíme
  if (body.hp) return json({ ok: true });

  // rate-limit podle IP
  const ip = request.headers.get("CF-Connecting-IP") || "0.0.0.0";
  const max = parseInt(env.RATE_LIMIT_MAX || "5", 10);
  const win = parseInt(env.RATE_LIMIT_WINDOW || "3600", 10);
  if (env.LEADS) {
    const key = `rl:${ip}`;
    const cur = parseInt((await env.LEADS.get(key)) || "0", 10);
    if (cur >= max) return json({ ok: false, error: "rate_limited" }, 429);
    await env.LEADS.put(key, String(cur + 1), { expirationTtl: win });
  }

  // validace kontaktu + souhlasu
  const c = body.contact || {};
  if (!c.jmeno || !c.email || !c.telefon || !body.consent) {
    return json({ ok: false, error: "missing_fields" }, 400);
  }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(c.email)) {
    return json({ ok: false, error: "bad_email" }, 400);
  }

  const token = crypto.randomUUID().replace(/-/g, "");
  const nowIso = new Date().toISOString();
  const record = {
    token,
    created: nowIso,
    ip,
    contact: c,
    consent: !!body.consent,
    consent_ts: body.consent_ts || nowIso, // časové razítko souhlasu (GDPR)
    analysis: body.analysis || {},
  };

  // ulož report do KV (pro /report/{token})
  const ttl = parseInt(env.REPORT_TTL_DAYS || "90", 10) * 86400;
  if (env.LEADS) {
    await env.LEADS.put(`report:${token}`, JSON.stringify(record), { expirationTtl: ttl });
  }

  const origin2 = new URL(request.url).origin;
  const reportUrl = `${origin2}/report/${token}`;

  // Sheets + e-maily neblokují odpověď uživateli (běží po odeslání odpovědi)
  ctx.waitUntil(
    (async () => {
      try {
        await appendToSheet(env, record, reportUrl);
      } catch (e) {
        console.log("Sheets error:", e.message);
      }
      try {
        await sendEmails(env, record, reportUrl);
      } catch (e) {
        console.log("Resend error:", e.message);
      }
    })()
  );

  return json({ ok: true, report_url: reportUrl });
}

/* ----------------------------- Google Sheets ------------------------------ */
async function appendToSheet(env, record, reportUrl) {
  if (!env.GOOGLE_SERVICE_ACCOUNT_EMAIL || !env.GOOGLE_PRIVATE_KEY || !env.GOOGLE_SHEET_ID) {
    console.log("Sheets: chybí secrets, přeskočeno");
    return;
  }
  const accessToken = await getGoogleAccessToken(env);
  const a = record.analysis || {};
  const inp = a.inputs || {};
  const avg = (a.backtest && a.backtest.avg) || {};
  const row = [
    record.created,
    record.contact.jmeno || "",
    record.contact.firma || "",
    record.contact.email || "",
    record.contact.telefon || "",
    inp.komodita || "",
    inp.mwh ?? "",
    inp.odberna_mista ?? "",
    inp.typ || "",
    inp.kdy || "",
    inp.cena_kc_mwh ?? "",
    a.verdict || "",
    Array.isArray(a.fair_range) ? a.fair_range.join("–") : "",
    round0(avg.fixQ4),
    round0(avg.transe),
    round0(avg.spot),
    round0(avg.mix),
    a.save_vs_worst_kc_rok ?? "",
    record.consent ? "ano" : "ne",
    record.consent_ts,
    reportUrl,
  ];
  const range = "A1"; // append hledá tabulku od A1
  const api =
    `https://sheets.googleapis.com/v4/spreadsheets/${env.GOOGLE_SHEET_ID}` +
    `/values/${encodeURIComponent(range)}:append?valueInputOption=RAW`;
  const r = await fetch(api, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ values: [row] }),
  });
  if (!r.ok) throw new Error(`Sheets append ${r.status}: ${await r.text()}`);
}

// OAuth2 access token přes JWT podepsaný privátním klíčem service accountu
async function getGoogleAccessToken(env) {
  const nowSec = Math.floor(Date.now() / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const claim = {
    iss: env.GOOGLE_SERVICE_ACCOUNT_EMAIL,
    scope: "https://www.googleapis.com/auth/spreadsheets",
    aud: "https://oauth2.googleapis.com/token",
    iat: nowSec,
    exp: nowSec + 3600,
  };
  const enc = (o) => b64url(new TextEncoder().encode(JSON.stringify(o)));
  const unsigned = `${enc(header)}.${enc(claim)}`;
  const key = await importPkcs8(env.GOOGLE_PRIVATE_KEY);
  const sig = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    key,
    new TextEncoder().encode(unsigned)
  );
  const jwt = `${unsigned}.${b64url(new Uint8Array(sig))}`;

  const r = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: jwt,
    }),
  });
  if (!r.ok) throw new Error(`token ${r.status}: ${await r.text()}`);
  return (await r.json()).access_token;
}

async function importPkcs8(pem) {
  const clean = pem
    .replace(/-----BEGIN PRIVATE KEY-----/, "")
    .replace(/-----END PRIVATE KEY-----/, "")
    .replace(/\\n/g, "")
    .replace(/\s/g, "");
  const der = Uint8Array.from(atob(clean), (c) => c.charCodeAt(0));
  return crypto.subtle.importKey(
    "pkcs8",
    der,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"]
  );
}

function b64url(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/* -------------------------------- Resend ---------------------------------- */
async function sendEmails(env, record, reportUrl) {
  if (!env.RESEND_API_KEY) {
    console.log("Resend: chybí API key, přeskočeno");
    return;
  }
  const c = record.contact;
  const from = env.FROM_EMAIL || "report@nepreplacejte.cz";

  // notifikace majiteli
  if (env.NOTIFY_EMAIL) {
    await resendSend(env, {
      from,
      to: [env.NOTIFY_EMAIL],
      subject: `Nový lead: ${c.firma || c.jmeno}`,
      html:
        `<h2>Nový lead z nepřeplácejte.cz</h2>` +
        `<p><b>${esc(c.jmeno)}</b> · ${esc(c.firma || "")}<br>` +
        `${esc(c.email)} · ${esc(c.telefon)}</p>` +
        `<p>Report: <a href="${reportUrl}">${reportUrl}</a></p>` +
        `<pre>${esc(JSON.stringify(record.analysis, null, 2))}</pre>`,
    });
  }

  // potvrzení uživateli
  await resendSend(env, {
    from,
    to: [c.email],
    subject: "Váš report – kontrola nákupu energií",
    html:
      `<p>Dobrý den ${esc(c.jmeno)},</p>` +
      `<p>děkujeme za využití kontroly nákupu energií. Váš protokol najdete zde:</p>` +
      `<p><a href="${reportUrl}">${reportUrl}</a></p>` +
      `<p>Brzy se vám ozve jeden prověřený specialista.</p>` +
      `<p>— nepřeplácejte.cz</p>`,
  });
}

async function resendSend(env, payload) {
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`Resend ${r.status}: ${await r.text()}`);
}

/* ----------------------------- /report/{token} ---------------------------- */
async function handleReport(url, env) {
  const token = url.pathname.split("/").pop();
  if (!token || !env.LEADS) return reportError();
  const raw = await env.LEADS.get(`report:${token}`);
  if (!raw) return reportError();
  const record = JSON.parse(raw);
  return new Response(renderReport(record), {
    status: 200,
    headers: { "Content-Type": "text/html; charset=utf-8", "X-Robots-Tag": "noindex" },
  });
}

function reportError() {
  return new Response(
    `<!doctype html><meta charset=utf-8><body style="font-family:sans-serif;padding:40px">` +
      `<h1>Report nenalezen</h1><p>Odkaz je neplatný nebo expiroval.</p>`,
    { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } }
  );
}

/* ---- render privátního reportu ve vizuálu kontrolního protokolu ---- */
const STRAT = {
  fixQ4: "Fix podepsaný na podzim",
  transe: "Fix nakupovaný v tranších",
  spot: "Čistý spot",
  mix: "Kombinace 50 % fix + 50 % spot",
};

function renderReport(record) {
  const a = record.analysis || {};
  const inp = a.inputs || {};
  const bt = a.backtest || {};
  const avg = bt.avg || {};
  const order = bt.order || ["fixQ4", "transe", "spot", "mix"];
  const mwh = inp.mwh || 0;
  const fair = a.fair_range || [0, 0];
  const bad = a.verdict === "over" || a.verdict === "timing";
  const stampTxt = bad ? "PŘEPLÁCÍTE" : "V POŘÁDKU";
  const stampColor = bad ? "#C9403A" : "#1B8A5A";
  const komodita = inp.komodita === "plyn" ? "Zemní plyn" : "Elektřina";

  const rows = order
    .map((k, i) => {
      const price = avg[k] || 0;
      const best = i === 0 ? ' style="background:#FFF7DC"' : "";
      const tag = i === 0 ? ' <span style="background:#FFC800;font-size:10px;padding:2px 7px">nejlevnější</span>' : "";
      return (
        `<tr${best}><td style="padding:11px 10px 11px 0;border-bottom:1px solid #EEF0EC">${STRAT[k]}${tag}</td>` +
        `<td style="text-align:right;padding:11px 0;border-bottom:1px solid #EEF0EC">${fmt(price)}</td>` +
        `<td style="text-align:right;padding:11px 0;border-bottom:1px solid #EEF0EC">${fmt(price * mwh)} Kč</td></tr>`
      );
    })
    .join("");

  const kpis = [
    [fmt(mwh) + " MWh", "roční spotřeba"],
    [fmt(a.save_vs_worst_kc_rok || 0) + " Kč/rok", "rozdíl nejlepší vs. nejhorší"],
    [fmt(fair[0]) + "–" + fmt(fair[1]), "férové rozmezí Kč/MWh"],
  ]
    .map(
      (k) =>
        `<div style="padding:18px 20px;border-right:1.5px solid #1B232E;flex:1">` +
        `<div style="font-family:monospace;font-weight:600;font-size:22px">${k[0]}</div>` +
        `<div style="font-family:monospace;font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:#5B6470;margin-top:4px">${k[1]}</div></div>`
    )
    .join("");

  return `<!doctype html><html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<title>Kontrolní protokol — nepřeplácejte.cz</title>
<style>
  body{font-family:Archivo,system-ui,sans-serif;background:#F2F3F0;color:#1B232E;margin:0;padding:30px 16px;line-height:1.55}
  .proto{max-width:820px;margin:0 auto;background:#fff;border:1.5px solid #1B232E;box-shadow:9px 9px 0 #1B232E}
  .head{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;padding:24px 30px 16px;border-bottom:1.5px solid #1B232E}
  .head .t{font-weight:800;font-size:22px}
  .head .n{font-family:monospace;font-size:12px;color:#5B6470}
  .body{padding:26px 30px 34px}
  .stamp{display:inline-block;border:4px solid ${stampColor};color:${stampColor};font-weight:800;font-size:24px;letter-spacing:.08em;padding:6px 18px;transform:rotate(-4deg)}
  .kpis{display:flex;border:1.5px solid #1B232E;margin:24px 0}
  table{width:100%;border-collapse:collapse;font-family:monospace;font-size:13.5px;margin-top:8px}
  th{text-align:left;font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:#5B6470;border-bottom:1.5px solid #1B232E;padding:8px 10px 8px 0}
  th:nth-child(2),th:nth-child(3){text-align:right}
  h4{margin:28px 0 12px;text-transform:uppercase;letter-spacing:.04em;font-size:15px}
  .note{font-family:monospace;font-size:11px;color:#5B6470;margin-top:22px}
  .meta{font-family:monospace;font-size:12px;color:#5B6470}
</style></head><body>
<div class="proto">
  <div class="head"><div class="t">KONTROLNÍ PROTOKOL</div><div class="n">${esc(a.protokol_num || "")}</div></div>
  <div class="body">
    <div class="stamp">${stampTxt}</div>
    <p class="meta" style="margin-top:16px">Komodita: <b>${komodita}</b> · spotřeba <b>${fmt(mwh)} MWh</b>${
    inp.cena_kc_mwh ? ` · vaše cena <b>${fmt(inp.cena_kc_mwh)} Kč/MWh</b>` : ""
  } · data k ${esc(a.asof || "")}</p>
    <div class="kpis">${kpis}</div>
    <h4>Backtest nákupních strategií · dodávky 2022–2025</h4>
    <table><tr><th>Strategie</th><th>Ø cena Kč/MWh</th><th>Ø náklad / rok</th></tr>${rows}</table>
    <h4>Kontakt</h4>
    <p class="meta">${esc(record.contact.jmeno)} · ${esc(record.contact.firma || "")}<br>${esc(
    record.contact.email
  )} · ${esc(record.contact.telefon)}</p>
    <p class="note">Report je orientační, vychází z historických dat trhu (OTE · PXE/EEX) a obvyklých marží dodavatele. Minulá výkonnost nezaručuje budoucí výsledky. Vygenerováno ${esc(
      record.created
    )}.</p>
  </div>
</div>
</body></html>`;
}

/* -------------------------------- utils ----------------------------------- */
function fmt(n) {
  return Math.round(Number(n) || 0)
    .toLocaleString("cs-CZ")
    .replace(/ /g, " ");
}
function round0(n) {
  return n == null ? "" : Math.round(Number(n));
}
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
