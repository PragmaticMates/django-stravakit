/* django-stravakit · site-wide UI — nav + user menu, photo lightbox, page-load timing */
function toggleNav(e) {
  e.stopPropagation();
  const nav = document.getElementById('site-nav');
  const btn = document.getElementById('nav-toggle');
  const open = nav.classList.toggle('open');
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
}
document.addEventListener('click', function(e) {
  const nav = document.getElementById('site-nav');
  const btn = document.getElementById('nav-toggle');
  const items = document.getElementById('nav-items');
  if (!nav || !nav.classList.contains('open')) return;
  if (btn.contains(e.target) || items.contains(e.target)) return;
  nav.classList.remove('open');
  btn.setAttribute('aria-expanded', 'false');
});
// A filter follows the visitor from page to page. Every page keeps its filter in the
// address bar (the dashboard rewrites it in place, the lists push it), so at the moment
// a nav link is used the current URL *is* the filter state. Each link declares in
// `data-carry` which parameters its page understands, and its href is rebuilt from the
// current URL just before it is followed — on pointerdown and focus, which both precede
// a click, a middle-click and an Enter. Parameters the target does not list are dropped,
// so an activity search never becomes a gear search.
function carryFilters(link) {
  const keys = (link.getAttribute('data-carry') || '').split(/\s+/).filter(Boolean);
  const current = new URLSearchParams(window.location.search);
  const url = new URL(link.getAttribute('href'), window.location.href);
  keys.forEach(function(key) {
    const value = current.get(key);
    if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
  });
  link.setAttribute('href', url.pathname + url.search);
}
['pointerdown', 'focusin'].forEach(function(type) {
  document.addEventListener(type, function(e) {
    const link = e.target.closest && e.target.closest('a[data-carry]');
    if (link) carryFilters(link);
  });
});
function toggleUserMenu(e) {
  e.stopPropagation();
  const trigger = document.getElementById('user-menu-trigger');
  const isOpen = trigger.getAttribute('aria-expanded') === 'true';
  trigger.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
}
document.addEventListener('click', function(e) {
  const trigger = document.getElementById('user-menu-trigger');
  if (trigger && !trigger.contains(e.target)) trigger.setAttribute('aria-expanded', 'false');
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('user-menu-trigger').setAttribute('aria-expanded', 'false');
});

// Clicking an activity card's photo thumbnail opens it full-size in a lightbox.
// Delegated from the document so it also covers htmx-swapped cards.
(function() {
  let box;
  function close() { if (box) { box.classList.remove('open'); document.body.classList.remove('modal-open'); } }
  document.addEventListener('click', function(e) {
    const photo = e.target.closest('.fc-photo');
    if (!photo || !photo.src) return;
    e.stopPropagation();
    if (!box) {
      box = document.createElement('div');
      box.className = 'fc-lightbox';
      box.innerHTML = '<img alt="">';
      box.addEventListener('click', close);
      document.body.appendChild(box);
    }
    box.querySelector('img').src = photo.src;
    box.classList.add('open');
    document.body.classList.add('modal-open');
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') close();
  });
})();

// Log how long the page took to load, broken down by phase so we can see where the
// time goes (server response vs. download vs. DOM parse/scripts vs. load event).
// Deferred so loadEventEnd is populated — it's still 0 while the load event fires.
window.addEventListener('load', function() {
  setTimeout(function() {
    const nav = performance.getEntriesByType('navigation')[0];
    if (!nav) { console.log('Page load time:', Math.round(performance.now()) + ' ms'); return; }
    const r = function(a, b) { return Math.round(nav[b] - nav[a]); };
    console.log('Page load time:', Math.round(nav.loadEventEnd - nav.startTime) + ' ms', {
      'server (TTFB)':      r('requestStart', 'responseStart') + ' ms',
      'download (response)': r('responseStart', 'responseEnd') + ' ms',
      'DOM parse + sync JS': r('responseEnd', 'domContentLoadedEventStart') + ' ms',
      'DOMContentLoaded JS': r('domContentLoadedEventStart', 'domContentLoadedEventEnd') + ' ms',
      'after DCL → load':   r('domContentLoadedEventEnd', 'loadEventStart') + ' ms',
      'load handlers':      r('loadEventStart', 'loadEventEnd') + ' ms',
      'transferSize':       (nav.transferSize || 0) + ' bytes',
    });
  }, 0);
});
