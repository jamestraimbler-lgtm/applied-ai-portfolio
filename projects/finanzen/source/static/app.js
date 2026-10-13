/**
 * FinanZen CRM — app.js
 * Auto-lock timer, activiteitsregistratie, UI-helpers
 */

(function () {
  'use strict';

  /* ===== CONFIGURATIE ===== */
  const INACTIVITEIT_MS   = 15 * 60 * 1000;   // 15 minuten (gelijk aan server)
  const WAARSCHUWING_MS   = 2  * 60 * 1000;   // waarschuw bij 2 minuten resterend
  const PING_INTERVAL_MS  = 60 * 1000;         // ping server elke minuut
  const CHECK_INTERVAL_MS = 5  * 1000;         // controleer timer elke 5 seconden

  /* ===== TOESTAND ===== */
  let lastActivity = Date.now();
  let gelogdUit    = false;

  /* ===== ACTIVITEITSREGISTRATIE ===== */
  function registreerActiviteit() {
    lastActivity = Date.now();
  }

  ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll', 'click']
    .forEach(evt => document.addEventListener(evt, registreerActiviteit, { passive: true }));

  /* ===== SERVER PING ===== */
  async function pingServer() {
    try {
      const resp = await fetch('/api/ping', { method: 'POST', credentials: 'same-origin' });
      if (resp.status === 401 || resp.redirected) {
        // Server heeft sessie al verlopen
        forceerUitloggen();
      }
    } catch (_) {
      // Netwerk-fout (b.v. server gestopt): negeer stilletjes
    }
  }

  setInterval(pingServer, PING_INTERVAL_MS);

  /* ===== TIMER-DISPLAY ===== */
  const timerEl = document.getElementById('lockTimer');

  function formateerTijd(ms) {
    if (ms <= 0) return '0:00';
    const totaalSec = Math.ceil(ms / 1000);
    const min = Math.floor(totaalSec / 60);
    const sec = totaalSec % 60;
    return `${min}:${sec.toString().padStart(2, '0')}`;
  }

  function controleerTimer() {
    if (gelogdUit) return;

    const verlopen = Date.now() - lastActivity;
    const resterend = INACTIVITEIT_MS - verlopen;

    if (resterend <= 0) {
      forceerUitloggen();
      return;
    }

    if (timerEl) {
      timerEl.textContent = `🔒 Vergrendelt over ${formateerTijd(resterend)}`;

      timerEl.classList.remove('waarschuwing', 'kritiek');
      if (resterend <= 30_000) {
        timerEl.classList.add('kritiek');
      } else if (resterend <= WAARSCHUWING_MS) {
        timerEl.classList.add('waarschuwing');
      }
    }
  }

  setInterval(controleerTimer, CHECK_INTERVAL_MS);
  controleerTimer(); // direct uitvoeren

  /* ===== UITLOGGEN ===== */
  function forceerUitloggen() {
    if (gelogdUit) return;
    gelogdUit = true;

    if (timerEl) {
      timerEl.textContent = '🔒 Sessie verlopen';
      timerEl.classList.add('kritiek');
    }

    // Kleine vertraging zodat gebruiker de melding ziet
    setTimeout(() => {
      window.location.href = '/uitloggen?reden=inactief';
    }, 800);
  }

  /* ===== PARTNER-SECTIE TOGGLE (dossier_form.html) ===== */
  // Wordt hier als fallback ingeladen; dossier_form.html heeft ook een inline-versie
  const heeftPartnerCb = document.getElementById('heeftPartner');
  const partnerSectie  = document.getElementById('partner-sectie');

  if (heeftPartnerCb && partnerSectie) {
    heeftPartnerCb.addEventListener('change', function () {
      partnerSectie.style.display = this.checked ? '' : 'none';
    });
  }

  /* ===== BEVESTIGING BIJ GEVAARLIJKE ACTIES ===== */
  // Formulieren met data-bevestig="..." krijgen een confirm-dialoog
  document.querySelectorAll('form[data-bevestig]').forEach(form => {
    form.addEventListener('submit', function (e) {
      const bericht = this.dataset.bevestig || 'Weet u het zeker?';
      if (!confirm(bericht)) {
        e.preventDefault();
      }
    });
  });

  /* ===== TABEL KLIKBAAR MAKEN (rijen met data-href) ===== */
  document.querySelectorAll('tr[data-href]').forEach(rij => {
    rij.style.cursor = 'pointer';
    rij.addEventListener('click', function (e) {
      // Negeer klikken op knoppen/links/selects binnen de rij
      if (e.target.closest('a, button, select, input, form')) return;
      window.location.href = this.dataset.href;
    });
  });

  /* ===== ZOEKFILTER DOSSIERS (client-side, geen serverronde) ===== */
  const zoekInput  = document.getElementById('zoekInput');
  const filterSel  = document.getElementById('filterStatus');
  const tabelBody  = document.getElementById('dossiersTbody');

  function filterTabel() {
    if (!tabelBody) return;
    const zoekterm = (zoekInput?.value || '').toLowerCase().trim();
    const status   = filterSel?.value || '';

    tabelBody.querySelectorAll('tr').forEach(rij => {
      const tekst     = rij.textContent.toLowerCase();
      const rijStatus = rij.dataset.status || '';

      const matchZoek   = !zoekterm || tekst.includes(zoekterm);
      const matchStatus = !status   || rijStatus === status;

      rij.style.display = (matchZoek && matchStatus) ? '' : 'none';
    });
  }

  if (zoekInput)  zoekInput.addEventListener('input',  filterTabel);
  if (filterSel)  filterSel.addEventListener('change', filterTabel);

  /* ===== FLASH-BERICHTEN NA 6 SECONDEN VERBERGEN ===== */
  setTimeout(() => {
    document.querySelectorAll('.flash').forEach(el => {
      el.style.transition = 'opacity .5s';
      el.style.opacity    = '0';
      setTimeout(() => el.remove(), 500);
    });
  }, 6000);

})();
