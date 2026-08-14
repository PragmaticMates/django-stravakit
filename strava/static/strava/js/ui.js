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
