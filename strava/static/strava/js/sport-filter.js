/* django-strava · shared sport filter dropdown (dashboard / activities / gallery)
 *
 * Builds one categorized icon dropdown from two json_script data islands rendered by
 * widgets/sport_filter.html: a flat "All sports" list of every sport in the data,
 * preceded by a "Top sports" category of grouped meta-sports. Group membership AND the
 * per-sport SVG glyphs come from the server (strava/sports.py + strava/sport_icons.py)
 * — each option carries its own glyph and each group its own — so the client holds no
 * icon copy and can never drift from the map/grid/table/gallery/compare surfaces.
 *
 * Exposes window.DSSport = { build, match }.
 */
window.DSSport = (function() {
  'use strict';

  var groups = [];  // cached group defs so match() works outside build()

  function match(value, sportType) {
    if (!value || value === 'all') return true;
    for (var i = 0; i < groups.length; i++) {
      if (groups[i].key === value) return groups[i].types.indexOf(sportType) !== -1;
    }
    return value === sportType;
  }

  function readJSON(id) {
    var el = id && document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  // Build the categorized dropdown panel for a trigger button and wire selection.
  function build(trigger, opts) {
    if (!trigger) return;
    opts = opts || {};
    var options = readJSON(trigger.getAttribute('data-sport-options')) || [];  // [[value,label,glyph],…]
    groups = readJSON(trigger.getAttribute('data-sport-groups')) || groups;
    var onSelect = opts.onSelect || function() {};
    var current = trigger.getAttribute('data-sport-current') || 'all';

    var available = {};
    options.forEach(function(o) { available[o[0]] = true; });

    var dd = document.createElement('div');
    dd.className = 'sports-dd';

    function setTrigger(value, label, iconHtml) {
      var iconSlot = trigger.querySelector('.sport-pill-icon');
      if (iconSlot && value !== 'all') iconSlot.innerHTML = iconHtml || '';
      var labelSlot = trigger.querySelector('.sport-current-label');
      if (labelSlot) labelSlot.textContent = value === 'all' ? 'All Sports' : label;
      trigger.setAttribute('data-sport-current', value);
    }

    function addOpt(value, label, iconHtml) {
      var el = document.createElement('div');
      el.className = 'sports-dd-opt' + (value === current ? ' sports-dd-sel' : '');
      el.innerHTML = (iconHtml || '') + '<span>' + label + '</span>';
      if (value === current && value !== 'all') setTrigger(value, label, iconHtml);
      el.addEventListener('click', function(e) {
        e.stopPropagation();
        current = value;
        dd.querySelectorAll('.sports-dd-opt').forEach(function(o) { o.classList.remove('sports-dd-sel'); });
        el.classList.add('sports-dd-sel');
        setTrigger(value, label, iconHtml);
        dd.style.display = 'none';
        onSelect(value, label);
      });
      dd.appendChild(el);
    }

    function addHead(text) {
      var h = document.createElement('div');
      h.className = 'sports-dd-group';
      h.textContent = text;
      dd.appendChild(h);
    }

    // Reset row.
    addOpt('all', 'All Sports', '');

    // "Top sports" — only groups with at least one member present in the data.
    var topGroups = groups.filter(function(g) {
      return g.types.some(function(t) { return available[t]; });
    });
    if (topGroups.length) {
      addHead('Top sports');
      topGroups.forEach(function(g) { addOpt(g.key, g.label, g.glyph || ''); });
    }

    // Flat list of every sport in the data.
    if (options.length) {
      addHead('All sports');
      options.forEach(function(o) { addOpt(o[0], o[1], o[2] || ''); });
    }

    document.body.appendChild(dd);

    trigger.addEventListener('click', function(e) {
      e.stopPropagation();
      var wasOpen = dd.style.display === 'block';
      document.querySelectorAll('.sports-dd').forEach(function(d) { d.style.display = 'none'; });
      if (!wasOpen) {
        var r = trigger.getBoundingClientRect();
        // Show first so we can measure the rendered width, then clamp the left edge
        // so the menu never spills past the viewport (buttons sit on the right side).
        dd.style.display = 'block';
        var margin = 8;
        var left = r.left + window.scrollX;
        var maxLeft = window.scrollX + document.documentElement.clientWidth - dd.offsetWidth - margin;
        if (left > maxLeft) left = maxLeft;
        if (left < window.scrollX + margin) left = window.scrollX + margin;
        dd.style.top = (r.bottom + window.scrollY + 6) + 'px';
        dd.style.left = left + 'px';
      }
    });

    return dd;
  }

  // Close any open dropdown on an outside click.
  document.addEventListener('click', function() {
    document.querySelectorAll('.sports-dd').forEach(function(d) { d.style.display = 'none'; });
  });

  return { build: build, match: match };
})();
