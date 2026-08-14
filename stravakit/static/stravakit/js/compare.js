// Compare page: bar fills are computed server-side and carried on each
// `.cmp-bar > i[data-w]` as a percentage. Apply them here (rather than as inline
// template styles) and re-apply after the sport filter swaps the matrix via htmx.
// The matrix also opens scrolled to the right so the current year is in view.
(function () {
  function paintBars(root) {
    (root || document).querySelectorAll('.cmp-bar > i[data-w]').forEach(function (bar) {
      bar.style.width = bar.getAttribute('data-w') + '%';
    });
  }

  function scrollToCurrent(root) {
    (root || document).querySelectorAll('.cmp-scroll').forEach(function (scroller) {
      scroller.scrollLeft = scroller.scrollWidth;
    });
  }

  // The full-width state lives on .cmp-page (outside the swapped #cmp-body), so it
  // persists across filter changes; keep the freshly-rendered button in sync with it.
  function syncExpand(root) {
    var page = document.querySelector('.cmp-page');
    var wide = page && page.classList.contains('is-wide');
    (root || document).querySelectorAll('.cmp-expand').forEach(function (btn) {
      btn.setAttribute('aria-pressed', wide ? 'true' : 'false');
    });
  }

  function refresh(root) {
    paintBars(root);
    syncExpand(root);
    scrollToCurrent(root);
  }

  document.addEventListener('DOMContentLoaded', function () { refresh(); });
  document.body.addEventListener('htmx:afterSwap', function (event) {
    if (event.target && event.target.id === 'cmp-body') {
      refresh(event.target);
    }
  });

  // Toggle full-width. Delegated from the document so it survives htmx swaps.
  document.addEventListener('click', function (event) {
    if (!event.target.closest('.cmp-expand')) return;
    var page = document.querySelector('.cmp-page');
    if (!page) return;
    page.classList.toggle('is-wide');
    syncExpand();
    scrollToCurrent();
  });

  // ---- Activity modal: a centered overlay showing one activity's card ----
  // Opened by clicking an effort-row title. The card HTML (with its route trace) is
  // fetched on demand from ActivityCardView, the same endpoint the dashboard uses.
  (function () {
    var modal = document.getElementById('activity-modal');
    if (!modal) return;
    var host = modal.querySelector('.act-modal-host');

    function cardUrl(id) { return modal.dataset.cardUrl.replace('/0/card/', '/' + id + '/card/'); }

    function close() {
      modal.hidden = true;
      host.innerHTML = '';
      document.body.classList.remove('modal-open');
    }

    function open(id) {
      fetch(cardUrl(id), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.ok ? r.text() : ''; })
        .then(function (html) {
          if (!html) return;
          host.innerHTML = html;
          modal.hidden = false;
          document.body.classList.add('modal-open');
          var card = host.querySelector('.float-card');
          if (!card) return;
          card.style.display = '';
          // Draw the route trace once the card is visible (needs a laid-out .fc-route).
          var route = card.querySelector('.fc-route[data-polyline]');
          if (route && window.DSCharts) window.DSCharts.renderRouteSvg(route);
          var closeBtn = card.querySelector('.fc-close');
          if (closeBtn) closeBtn.addEventListener('click', close);
        });
    }

    modal.querySelector('.act-modal-backdrop').addEventListener('click', close);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.hidden) close();
    });

    // Delegate from the document so titles swapped in by the sport filter work too.
    document.addEventListener('click', function (e) {
      var el = e.target.closest('.aoty-link');
      if (el && el.dataset.activity) open(el.dataset.activity);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var el = e.target.closest('.aoty-link');
      if (el && el.dataset.activity) { e.preventDefault(); open(el.dataset.activity); }
    });
  })();
})();
