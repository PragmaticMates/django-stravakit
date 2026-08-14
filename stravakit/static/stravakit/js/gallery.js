/* django-stravakit · gallery page — view toggle, sport tabs, activity modal */
// ——— View toggle (presentational, client-side) ———
let currentView = 'grid';
function applyView() {
  const g = document.getElementById('gallery-grid');
  if (!g) return;
  if (currentView === 'grid') g.removeAttribute('data-view');
  else g.setAttribute('data-view', currentView);
}
function setView(view, btn) {
  currentView = view;
  document.querySelectorAll('#view-toggle button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyView();
}

// ——— Sport dropdown drives the filter form ———
(function() {
  const btn = document.getElementById('gallery-sport-btn');
  if (btn && window.DSSport) {
    DSSport.build(btn, { onSelect: function(value) {
      document.getElementById('g-sport').value = value;
      document.getElementById('gallery-filters').requestSubmit();
    }});
  }
})();

// Re-apply the chosen layout after htmx swaps in a fresh grid.
document.body.addEventListener('htmx:afterSwap', function(e) {
  if (e.target.id === 'gallery-results') applyView();
});

// ——— Activity modal: clicking a gallery item opens that activity's card ———
// The card HTML (with its route trace) is fetched on demand from ActivityCardView,
// the same endpoint the activities, dashboard and compare pages use.
(function() {
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
      .then(function(r) { return r.ok ? r.text() : ''; })
      .then(function(html) {
        if (!html) return;
        host.innerHTML = html;
        modal.hidden = false;
        document.body.classList.add('modal-open');
        var card = host.querySelector('.float-card');
        if (!card) return;
        card.style.display = '';
        var route = card.querySelector('.fc-route[data-polyline]');
        if (route && window.DSCharts) window.DSCharts.renderRouteSvg(route);
        var closeBtn = card.querySelector('.fc-close');
        if (closeBtn) closeBtn.addEventListener('click', close);
      });
  }

  modal.querySelector('.act-modal-backdrop').addEventListener('click', close);
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && !modal.hidden) close();
  });

  // Delegate from the document so items swapped in by the filter form work too.
  document.addEventListener('click', function(e) {
    var item = e.target.closest('.gallery-item');
    if (item && item.dataset.activity) open(item.dataset.activity);
  });
  document.addEventListener('keydown', function(e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var item = e.target.closest('.gallery-item');
    if (item && item.dataset.activity) { e.preventDefault(); open(item.dataset.activity); }
  });
})();
