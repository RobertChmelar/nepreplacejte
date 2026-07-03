/* =====================================================================
   consent.js — cookie lišta + Google Analytics 4 (G-3DCWDKGPVZ)
   ---------------------------------------------------------------------
   Právně čistý režim: BEZ souhlasu se nenačítá vůbec nic (žádný gtag,
   žádné cookies). Po souhlasu se GA4 načte a doměří i eventy, které
   mezitím vznikly (fronta __gaQ). Volba se pamatuje v localStorage.
   Soubor je soběstačný (vlastní CSS) — používají ho všechny stránky.
   ===================================================================== */
(function () {
  var KEY = 'npl_consent', GA_ID = 'G-3DCWDKGPVZ';

  function loadGA() {
    if (window.__gaLoaded) return;
    window.__gaLoaded = 1;
    var s = document.createElement('script');
    s.async = 1;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA_ID;
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', GA_ID, { anonymize_ip: true });
    (window.__gaQ || []).forEach(function (a) { window.gtag.apply(null, a); });
    window.__gaQ = [];
  }

  /* globální helper — bezpečný i bez souhlasu (event se zahodí/frontuje) */
  window.gaEvent = function (name, params) {
    if (window.gtag) { window.gtag('event', name, params || {}); }
    else { (window.__gaQ = window.__gaQ || []).push(['event', name, params || {}]); }
  };

  var choice = null;
  try { choice = localStorage.getItem(KEY); } catch (e) {}
  if (choice === 'yes') { loadGA(); return; }
  if (choice === 'no') { return; }

  /* ---- lišta ve stylu webu ---- */
  var st = document.createElement('style');
  st.textContent =
    '.npl-consent{position:fixed;left:0;right:0;bottom:0;z-index:9999;background:#1B232E;color:#E8EAE6;' +
    'font-family:Archivo,system-ui,sans-serif;font-size:13.5px;line-height:1.5;padding:14px 20px;' +
    'border-top:3px solid #FFC800;display:flex;gap:14px;align-items:center;justify-content:center;flex-wrap:wrap}' +
    '.npl-consent a{color:#FFC800}' +
    '.npl-consent button{font-family:inherit;font-weight:700;font-size:13.5px;padding:9px 18px;cursor:pointer}' +
    '.npl-consent .npl-yes{background:#FFC800;color:#1B232E;border:2px solid #FFC800}' +
    '.npl-consent .npl-yes:hover{background:#fff;border-color:#fff}' +
    '.npl-consent .npl-no{background:transparent;color:#E8EAE6;border:1.5px solid #5B6470}' +
    '.npl-consent .npl-no:hover{border-color:#E8EAE6}';
  document.head.appendChild(st);

  var bar = document.createElement('div');
  bar.className = 'npl-consent';
  bar.setAttribute('role', 'dialog');
  bar.setAttribute('aria-label', 'Souhlas s cookies');
  bar.innerHTML =
    '<span>Používáme analytické cookies (Google Analytics), abychom věděli, co na webu funguje. ' +
    'Nic jiného neměříme. <a href="zasady-ochrany-udaju.html">Zásady ochrany údajů</a></span>' +
    '<button class="npl-yes" type="button">Povolit analytiku</button>' +
    '<button class="npl-no" type="button">Jen nezbytné</button>';

  function close(val) {
    try { localStorage.setItem(KEY, val); } catch (e) {}
    bar.remove();
    if (val === 'yes') loadGA();
  }
  bar.querySelector('.npl-yes').addEventListener('click', function () { close('yes'); });
  bar.querySelector('.npl-no').addEventListener('click', function () { close('no'); });
  document.body.appendChild(bar);
})();
