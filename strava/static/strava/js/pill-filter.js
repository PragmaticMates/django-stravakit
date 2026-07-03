/* django-strava · shared pill filter dropdown (year / gear on the map + activities bars)
 *
 * Builds a flat-or-sectioned dropdown from a json_script options island referenced by the
 * trigger's data-pill-options. Options are [value, label] or [value, label, group]; pass
 * `sections` ([{ key, label }]) to group them under headings by that third field (e.g. the
 * gear pill's Bikes/Shoes). The reset label and current selection come from the DOM
 * (data-pill-all / data-pill-current) so widgets/filter_pill.html stays declarative and
 * this holds no copy. Reuses the .sports-dd styling shared with the sport dropdown.
 *
 * Exposes window.DSPill = { build }. The caller supplies onSelect(value, label) to wire
 * the selection into its own filter state (client-side map filtering, or a form submit).
 */
window.DSPill = (function() {
  'use strict';

  function readJSON(id) {
    var el = id && document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  // Open a dropdown under its trigger, clamped so it never spills past the viewport (the
  // map pills sit hard against the right edge on mobile).
  function place(dd, btn) {
    var r = btn.getBoundingClientRect();
    dd.style.display = 'block';
    var margin = 8;
    var left = r.left + window.scrollX;
    var maxLeft = window.scrollX + document.documentElement.clientWidth - dd.offsetWidth - margin;
    if (left > maxLeft) left = maxLeft;
    if (left < window.scrollX + margin) left = window.scrollX + margin;
    dd.style.top = (r.bottom + window.scrollY + 6) + 'px';
    dd.style.left = left + 'px';
  }

  function build(btn, opts) {
    if (!btn) return null;
    opts = opts || {};
    var options = readJSON(btn.getAttribute('data-pill-options')) || [];  // [[value,label(,group)],…]
    if (!options.length) { btn.style.display = 'none'; return null; }
    var allLabel = btn.getAttribute('data-pill-all') || 'All';
    var current = btn.getAttribute('data-pill-current') || 'all';
    var sections = opts.sections || null;
    var onSelect = opts.onSelect || function() {};
    var label = btn.querySelector('.pill-label');

    var dd = document.createElement('div');
    dd.className = 'sports-dd';
    dd.style.display = 'none';

    function addHead(text) {
      var h = document.createElement('div');
      h.className = 'sports-dd-group';
      h.textContent = text;
      dd.appendChild(h);
    }
    function addOpt(value, text, isReset) {
      var el = document.createElement('div');
      el.className = 'sports-dd-opt' + (String(value) === String(current) ? ' sports-dd-sel' : '');
      el.innerHTML = '<span>' + text + '</span>';
      el.addEventListener('click', function(e) {
        e.stopPropagation();
        current = value;
        dd.querySelectorAll('.sports-dd-opt').forEach(function(o) { o.classList.remove('sports-dd-sel'); });
        el.classList.add('sports-dd-sel');
        if (label) label.textContent = isReset ? allLabel : text;
        dd.style.display = 'none';
        onSelect(value, text);
      });
      dd.appendChild(el);
    }

    addOpt('all', allLabel, true);
    if (sections && sections.length) {
      var known = {};
      sections.forEach(function(sec) {
        known[sec.key] = true;
        var inSec = options.filter(function(o) { return o[2] === sec.key; });
        if (!inSec.length) return;
        addHead(sec.label);
        inSec.forEach(function(o) { addOpt(o[0], o[1], false); });
      });
      options.filter(function(o) { return !known[o[2]]; }).forEach(function(o) { addOpt(o[0], o[1], false); });
    } else {
      options.forEach(function(o) { addOpt(o[0], o[1], false); });
    }

    // Reflect the current selection in the trigger label on load.
    if (label && current !== 'all') {
      options.forEach(function(o) { if (String(o[0]) === String(current)) label.textContent = o[1]; });
    }

    document.body.appendChild(dd);
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      var wasOpen = dd.style.display === 'block';
      document.querySelectorAll('.sports-dd').forEach(function(d) { d.style.display = 'none'; });
      if (!wasOpen) place(dd, btn);
    });
    return dd;
  }

  // Close any open dropdown on an outside click (covers sport + pill dropdowns alike).
  document.addEventListener('click', function() {
    document.querySelectorAll('.sports-dd').forEach(function(d) { d.style.display = 'none'; });
  });

  return { build: build };
})();
