/* django-stravakit · dashboard activity map (Leaflet) */
// Interactive activity map (Leaflet) — markers built from each activity's start_latlng.
(function() {
  const el = document.getElementById('activity-map');
  if (!el || typeof L === 'undefined') return;
  const dataEl = document.getElementById('map-markers');
  const markers = dataEl ? JSON.parse(dataEl.textContent) : [];

  // Per-sport glyphs, reused from the sport filter's options island (each entry is
  // [sport_type, label, svg] from strava/sport_icons.py) so the map draws the same icon
  // as the filter/grid/table/gallery without shipping a copy per marker. The colour still
  // keys off the broad `map_sport_type` bucket via the act-marker-<map_sport_type> class.
  const GLYPH_BY_SPORT = (function() {
    const el = document.getElementById('map-sport-options');
    const map = {};
    if (el) { try { JSON.parse(el.textContent).forEach(function(o) { map[o[0]] = o[2]; }); } catch (e) {} }
    return map;
  })();
  function pinIcon(m) {
    return L.divIcon({
      className: '',
      iconSize: [34, 34],
      iconAnchor: [17, 17],
      popupAnchor: [0, -18],
      html: '<span class="map-pin act-marker-' + m.map_sport_type + '">' + (GLYPH_BY_SPORT[m.sport_type] || '') + '</span>',
    });
  }

  // Route stroke color per sport, matching the marker palette.
  const COLORS = { run: '#FC5200', trail: '#7C4DB8', ride: '#007FB6', hike: '#3A8050', walk: '#3A8050', swim: '#007FB6', other: '#8a8a8a' };

  // Decode a Google-encoded polyline into [lat, lng] pairs for Leaflet.
  function decodePolyline(str) {
    let idx = 0, lat = 0, lng = 0;
    const coords = [];
    while (idx < str.length) {
      let b, shift = 0, result = 0;
      do { b = str.charCodeAt(idx++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      lat += (result & 1) ? ~(result >> 1) : (result >> 1);
      shift = result = 0;
      do { b = str.charCodeAt(idx++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      lng += (result & 1) ? ~(result >> 1) : (result >> 1);
      coords.push([lat / 1e5, lng / 1e5]);
    }
    return coords;
  }

  // Keep markers/routes clear of the overlapping UI: top filter pills + zoom
  // control, and the bottom strip where the Season totals card overlaps the map.
  const FIT = { paddingTopLeft: [50, 80], paddingBottomRight: [50, 140] };

  const map = L.map(el, { zoomControl: false, scrollWheelZoom: false });
  // Tile URL (with the CARTO key) comes from base.html's <meta>, shared with charts.js.
  const basemap = document.querySelector('meta[name="stravakit-basemap"]');
  L.tileLayer(basemap ? basemap.content : 'https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd', maxZoom: 19,
  }).addTo(map);

  // Remember the overview before showing a route, and note any manual map move so
  // closing the card can restore the previous position/zoom (unless the user moved).
  let routeLayer = null;
  let hoverLayer = null;
  let selectedMarker = null;   // lone pin shown while a card is open (others hidden)
  let allRoutesLayer = null;   // overlay of every visible activity's route, toggled on
  let showAllRoutes = true;    // on by default (routes overlay draws once zoomed past ROUTE_ZOOM_MIN)
  let savedView = null;
  let userMoved = false;
  function markUserMoved() { userMoved = true; }
  map.on('dragstart', markUserMoved);
  map.on('dblclick', markUserMoved);
  map.on('boxzoomstart', markUserMoved);

  // Decode a marker's route once and cache it for reuse on hover and click.
  function activityCoords(m) {
    if (m._coords === undefined) m._coords = m.polyline ? decodePolyline(m.polyline) : [];
    return m._coords;
  }

  // Frame the currently visible activities (all of them, or the active filter's
  // matches). When the routes overlay is on, frame the full extent of every
  // visible route so all routes stay completely visible — the marker start
  // points alone (visibleCoords) would clip routes that run off the framed area.
  function frameVisible() {
    let bounds = null;
    if (showAllRoutes && visibleMarkers.length) {
      bounds = L.latLngBounds([]);
      visibleMarkers.forEach(function(m) {
        const coords = activityCoords(m);
        bounds.extend(coords.length ? coords : [[m.lat, m.lng]]);
      });
    } else if (visibleCoords.length) {
      bounds = L.latLngBounds(visibleCoords);
    }
    if (bounds && bounds.isValid()) map.fitBounds(bounds, Object.assign({ maxZoom: 14 }, FIT));
  }

  // Only draw routes once zoomed in this close — at low zoom a busy map would try to
  // render thousands of polylines at once, which is slow and unreadable.
  const ROUTE_ZOOM_MIN = 6;

  // Draw (or clear) a thin route overlay. To keep it fast it draws only the routes
  // of activities currently in view, and only when zoomed in past ROUTE_ZOOM_MIN.
  // Follows the active filter and stays beneath the hover/selected route.
  function renderAllRoutes() {
    if (allRoutesLayer) { map.removeLayer(allRoutesLayer); allRoutesLayer = null; }
    if (!showAllRoutes || selectedMarker || map.getZoom() < ROUTE_ZOOM_MIN) return;
    const bounds = map.getBounds();
    const lines = [];
    visibleMarkers.forEach(function(m) {
      const coords = activityCoords(m);
      if (!coords.length) return;
      // Viewport cull: keep any route whose extent overlaps the current view,
      // not only those whose start point is in view — otherwise panning the
      // start point off-screen would drop a route still crossing the viewport.
      if (!bounds.intersects(L.latLngBounds(coords))) return;
      const color = COLORS[m.map_sport_type] || COLORS.other;
      // Visible thin route (non-interactive: the wide invisible hit line below owns
      // the pointer, so a 2.5px route stays easy to hover without looking thicker).
      lines.push(L.polyline(coords, { color: color, weight: 2.5, opacity: 0.65, interactive: false }));
      // Transparent wide hit target. Clicking selects the activity; hovering shows the
      // same preview + dimming as hovering the marker. Tagged so setRoutesDimmed leaves
      // it invisible (opacity 0) instead of fading it into view.
      const hit = L.polyline(coords, { color: color, weight: 16, opacity: 0 })
        .on('click', function() { selectActivity(m); })
        .on('mouseover', function() { showHoverRoute(m, m._marker); })
        .on('mouseout', function() { clearHoverRoute(); });
      hit.options._hit = true;
      lines.push(hit);
    });
    allRoutesLayer = L.layerGroup(lines).addTo(map);
  }

  // Fade the all-routes overlay so a single hovered route stands out among the rest.
  function setRoutesDimmed(dimmed) {
    if (!allRoutesLayer) return;
    allRoutesLayer.eachLayer(function(line) {
      if (line.options._hit) return;  // keep the invisible hit lines invisible
      line.setStyle({ opacity: dimmed ? 0.06 : 0.65 });
    });
  }

  // Fade every other marker/cluster while one marker is hovered, keeping it highlighted.
  const markerPane = map.getPane('markerPane');
  let hoveredIcon = null;
  function setMarkersDimmed(dimmed, marker) {
    if (markerPane) markerPane.classList.toggle('dim-others', dimmed);
    if (hoveredIcon) { hoveredIcon.classList.remove('marker-hovered'); hoveredIcon = null; }
    if (dimmed && marker && marker._icon) {
      hoveredIcon = marker._icon;
      hoveredIcon.classList.add('marker-hovered');
    }
  }

  // Preview the route on hover (dashed, no card, no map move); cleared on mouse-out.
  // The other routes and markers are dimmed so the hovered one is highlighted among them.
  function showHoverRoute(m, marker) {
    clearHoverRoute();
    const coords = activityCoords(m);
    if (!coords.length) return;
    setRoutesDimmed(true);
    setMarkersDimmed(true, marker);
    // Non-interactive so the preview drawn over a hovered route doesn't steal the
    // pointer from the base line beneath it (which would loop mouseover/mouseout).
    hoverLayer = L.layerGroup([
      L.polyline(coords, { color: COLORS[m.map_sport_type] || COLORS.other, weight: 10, opacity: 0.9, interactive: false }),
      L.polyline(coords, { color: '#fff', weight: 2.5, opacity: 0.9, interactive: false }),
    ]).addTo(map);
  }
  function clearHoverRoute() {
    if (hoverLayer) { map.removeLayer(hoverLayer); hoverLayer = null; }
    setRoutesDimmed(false);
    setMarkersDimmed(false);
  }

  const cardHost = document.getElementById('map-card-host');
  // Build the card endpoint URL for an activity id from the placeholder URL on the host.
  function cardUrl(id) { return cardHost.dataset.cardUrl.replace('/0/card/', '/' + id + '/card/'); }

  // Lay the route and the card out as one horizontally-centered pair sitting in the middle
  // of the map: [margin][route][gap][card][margin], with the two outer margins equal. The
  // route is a thin trace, so we frame it once to measure its actual rendered width, then
  // re-frame it into a column of exactly that width and pin the card a gap to its right —
  // that way the left-edge-to-route gap matches the card-to-right-edge gap, instead of the
  // route floating inside an oversized panel. Narrow viewports fall back to a centred card.
  function frameRouteBesideCard(coords, card) {
    const size = map.getSize();
    const cardW = (card && card.offsetWidth) || 360;
    const gap = 90;
    const fit = Object.assign({ maxZoom: 16, animate: false }, FIT);
    // Narrow screens: no room beside the route, so the card docks as a bottom sheet
    // (see strava.css). Frame the route into the strip above it by reserving the card's
    // height at the bottom of the fit, keeping the route visible rather than covered.
    if (size.x <= 900) {
      card.style.left = '';
      const reserve = (card.offsetHeight || 0) + 40;  // card height + dock gap
      map.fitBounds(coords, Object.assign({}, fit, {
        paddingTopLeft: [40, FIT.paddingTopLeft[1]],
        paddingBottomRight: [40, Math.max(reserve, FIT.paddingBottomRight[1])],
      }));
      return;
    }

    // Pass 1 — frame the route on the left (card column reserved on the right) to learn its
    // rendered pixel width at the fitted zoom.
    map.fitBounds(coords, Object.assign({}, fit, {
      paddingTopLeft: [60, FIT.paddingTopLeft[1]],
      paddingBottomRight: [Math.round(cardW + gap + 60), FIT.paddingBottomRight[1]],
    }));
    const b = L.latLngBounds(coords);
    const routeW = Math.abs(
      map.latLngToContainerPoint(b.getSouthEast()).x -
      map.latLngToContainerPoint(b.getNorthWest()).x
    );

    // Centre the [route + gap + card] block; bail to a centred card if it won't fit.
    const margin = Math.round((size.x - (routeW + gap + cardW)) / 2);
    if (margin < 20) { card.style.left = ''; map.fitBounds(coords, fit); return; }

    // Pass 2 — frame the route into a column exactly its own width, anchored at `margin`,
    // so it fills the column (its left edge sits at `margin`); pin the card a gap past it.
    map.fitBounds(coords, Object.assign({}, fit, {
      paddingTopLeft: [margin, FIT.paddingTopLeft[1]],
      paddingBottomRight: [Math.round(size.x - margin - routeW), FIT.paddingBottomRight[1]],
    }));
    card.style.left = Math.round(margin + routeW + gap + cardW / 2) + 'px';
  }

  // Fetch and show an activity's float card on demand (cards aren't server-rendered up
  // front), then frame the map route beside it once the card has a measurable width.
  function loadActivityCard(id, coords) {
    if (!cardHost) return;
    // ?map=1 → the route-less, full-bleed-photo card variant (route is drawn on the map).
    fetch(cardUrl(id) + '?map=1', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function(r) { return r.ok ? r.text() : ''; })
      .then(function(html) {
        cardHost.innerHTML = html;
        const card = cardHost.querySelector('.float-card');
        if (!card) return;
        card.style.display = '';
        if (window.renderCardRoute) window.renderCardRoute(card);
        const closeBtn = card.querySelector('.fc-close');
        if (closeBtn) closeBtn.addEventListener('click', onCardClose);
        if (coords && coords.length) frameRouteBesideCard(coords, card);
      });
  }

  // Hide every other marker/cluster and the routes overlay, leaving a lone pin for the
  // selected activity. Restored by restoreMarkers() when the card closes.
  function hideOtherMarkers(m) {
    if (clusters && map.hasLayer(clusters)) map.removeLayer(clusters);
    if (allRoutesLayer) { map.removeLayer(allRoutesLayer); allRoutesLayer = null; }
    if (selectedMarker) map.removeLayer(selectedMarker);
    selectedMarker = L.marker([m.lat, m.lng], { icon: pinIcon(m) }).addTo(map);
  }
  function restoreMarkers() {
    if (selectedMarker) { map.removeLayer(selectedMarker); selectedMarker = null; }
    if (clusters && !map.hasLayer(clusters)) map.addLayer(clusters);
    renderAllRoutes();
  }

  // Draw the activity's route (replacing any previous one), load its card, frame the map.
  function selectActivity(m) {
    clearHoverRoute();
    if (!routeLayer) savedView = { center: map.getCenter(), zoom: map.getZoom() };
    userMoved = false;
    if (routeLayer) { map.removeLayer(routeLayer); routeLayer = null; }
    const coords = activityCoords(m);
    if (!coords.length) return;
    hideOtherMarkers(m);
    const color = COLORS[m.map_sport_type] || COLORS.other;
    routeLayer = L.layerGroup([
      L.polyline(coords, { color: '#fff', weight: 7, opacity: 0.85 }),
      L.polyline(coords, { color: color, weight: 4, opacity: 0.95 }),
    ]).addTo(map);
    loadActivityCard(m.id, coords);
  }

  // Hide any open card and drop its route, without moving the map.
  function closeCard() {
    if (cardHost) cardHost.innerHTML = '';
    if (routeLayer) { map.removeLayer(routeLayer); routeLayer = null; }
    restoreMarkers();
    savedView = null;
    userMoved = false;
  }

  // The close button also restores the prior view if the user hasn't panned/zoomed.
  function onCardClose() {
    const view = (savedView && !userMoved) ? savedView : null;
    closeCard();
    if (view) map.setView(view.center, view.zoom);
  }

  let resetView;
  let clusters = null;
  const leafletMarkers = [];
  // The markers currently on the map (all of them, or the active filter's matches).
  // visibleCoords backs reset framing; visibleMarkers backs the "all routes" overlay.
  let visibleMarkers = markers.slice();
  let visibleCoords = markers.map(function(m) { return [m.lat, m.lng]; });
  if (markers.length) {
    clusters = L.markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 60,
      // Zoom to clusters ourselves so the fit honours FIT padding (the default
      // zoomToBounds ignores it, leaving the bottom marker under the Season totals).
      // spiderfyOnMaxZoom stays enabled so coincident markers still fan out.
      zoomToBoundsOnClick: false,
      iconCreateFunction: function(cluster) {
        return L.divIcon({
          html: '<span class="map-cluster">' + cluster.getChildCount() + '</span>',
          className: '', iconSize: [36, 36], iconAnchor: [18, 18],
        });
      },
    });
    clusters.on('clusterclick', function(e) {
      closeCard();  // drilling into a cluster dismisses any open activity card
      clearHoverRoute();
      const cluster = e.layer;
      // If the cluster can only fan out (its markers can't be separated by zooming),
      // let markercluster's own handler spiderfy it; otherwise zoom in with padding.
      let bottom = cluster;
      while (bottom._childClusters.length === 1) bottom = bottom._childClusters[0];
      if (bottom._zoom === clusters._maxZoom && bottom._childCount === cluster._childCount) return;
      map.fitBounds(cluster.getBounds(), Object.assign({ maxZoom: clusters._maxZoom }, FIT));
    });
    markers.forEach(function(m, i) {
      const marker = L.marker([m.lat, m.lng], { icon: pinIcon(m) })
        .bindTooltip(m.title)
        .on('mouseover', function() { showHoverRoute(m, marker); })
        .on('mouseout', function() { clearHoverRoute(); })
        .on('click', function() { selectActivity(m); });
      m._marker = marker;  // let a route-line hover highlight this same marker
      leafletMarkers.push(marker);
      clusters.addLayer(marker);
    });
    map.addLayer(clusters);
    // Reset frames whatever markers are currently visible (all of them, or the
    // active filter's matches). Tracked from marker coords rather than
    // markercluster.getBounds(), which shrinks once off-screen markers unload.
    resetView = function() { frameVisible(); };
  } else {
    resetView = function() { map.setView([48.6, 18.2], 6); };  // default when no GPS activities exist
  }
  resetView();  // frame all markers on load

  // On touch devices a one-finger drag would both pan the map and scroll the page.
  // Require two fingers to pan (pinch-zoom already needs two), so a single-finger
  // swipe scrolls the page past the map.
  if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) {
    map.dragging.disable();
    el.addEventListener('touchstart', function(e) {
      if (e.touches.length >= 2) {
        map.dragging.enable();
      } else {
        map.dragging.disable();
      }
    }, { passive: true });
    el.addEventListener('touchend', function(e) {
      if (e.touches.length < 2) map.dragging.disable();
    });
  }

  // Wire the zoom slider + / − buttons to the map (two-way: controls drive zoom,
  // map moves sync back).
  const zslider = document.getElementById('map-zoom-slider');
  if (zslider) {
    zslider.min = map.getMinZoom();
    zslider.max = map.getMaxZoom();
    function syncSlider() { zslider.value = Math.round(map.getZoom()); }
    syncSlider();
    zslider.addEventListener('input', function() {
      markUserMoved();
      map.setZoom(Number(zslider.value), { animate: false });
    });
    map.on('zoomend', syncSlider);
  }
  const zin = document.getElementById('map-zoom-in');
  const zout = document.getElementById('map-zoom-out');
  if (zin) zin.addEventListener('click', function() { markUserMoved(); map.zoomIn(); });
  if (zout) zout.addEventListener('click', function() { markUserMoved(); map.zoomOut(); });

  // Expand button: grow the map widget to fill the viewport in-page (not OS fullscreen).
  // Leaflet must recompute its size once the container's dimensions change.
  const hero = el.closest('.maphero');
  const fsBtn = document.getElementById('map-fullscreen');
  if (fsBtn && hero) fsBtn.addEventListener('click', function() {
    const expanded = hero.classList.toggle('expanded');
    document.body.classList.toggle('map-expanded', expanded);  // keeps the header on top
    if (expanded) window.scrollTo(0, 0);  // align with the header pinned at the top
    map.invalidateSize();  // recompute tiles/markers for the new size
  });

  // Reset button: close any card/route and re-frame all markers.
  const reset = document.getElementById('map-reset');
  if (reset) reset.addEventListener('click', function() {
    closeCard();
    clearHoverRoute();
    resetView();
  });

  // Routes toggle: overlay in-view routes (only when zoomed in), or clear them.
  const routesToggle = document.getElementById('map-routes-toggle');
  if (routesToggle) {
    // Reflect the default-on state on the button, then draw the initial overlay.
    routesToggle.classList.toggle('active', showAllRoutes);
    routesToggle.setAttribute('aria-pressed', showAllRoutes ? 'true' : 'false');
    routesToggle.addEventListener('click', function() {
      showAllRoutes = !showAllRoutes;
      routesToggle.classList.toggle('active', showAllRoutes);
      routesToggle.setAttribute('aria-pressed', showAllRoutes ? 'true' : 'false');
      renderAllRoutes();
    });
    renderAllRoutes();
  }
  // Re-render as the view changes so routes appear once zoomed in and track the viewport.
  map.on('moveend zoomend', function() { if (showAllRoutes) renderAllRoutes(); });

  // ---- Map filters: search box + sport / gear / year pills ----
  // The map itself filters its markers client-side (below); the same state is mirrored
  // into the hidden #dash-filters form so the dependent dashboard sections (season
  // totals, latest activities, trends, calendar, gear stats) recompute server-side.
  const filterState = { q: '', sport: 'all', gear: 'all', year: 'all', dist_min: 0, dist_max: Infinity };

  function syncDashboard() {
    const form = document.getElementById('dash-filters');
    if (!form || typeof htmx === 'undefined') return;
    document.getElementById('df-q').value = filterState.q;
    document.getElementById('df-sport').value = filterState.sport;
    document.getElementById('df-gear').value = filterState.gear;
    document.getElementById('df-year').value = filterState.year;
    document.getElementById('df-dist_min').value = filterState.dist_min;
    document.getElementById('df-dist_max').value = filterState.dist_max;
    htmx.trigger(form, 'refresh');
  }

  // Lowercase and strip diacritics, the client-side equivalent of unaccent().
  function unaccent(s) {
    return (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  }

  // Show only markers matching every active filter, then reframe to the matches.
  // Search mirrors the server-side `name__unaccent__icontains` — accent-insensitive,
  // with each whitespace-separated token required to match (AND).
  function applyFilters() {
    if (!clusters) return;
    const tokens = unaccent(filterState.q.trim()).split(/\s+/).filter(Boolean);
    closeCard();
    clearHoverRoute();
    clusters.clearLayers();
    const shown = [];
    visibleMarkers = [];
    markers.forEach(function(m, i) {
      const haystack = unaccent(m.title + ' ' + (m.map_sport_type || ''));
      const ok = tokens.every(function(t) { return haystack.indexOf(t) !== -1; })
        && (window.DSSport ? DSSport.match(filterState.sport, m.sport_type) : filterState.sport === 'all' || m.sport_type === filterState.sport)
        && (filterState.gear === 'all' || m.gear === filterState.gear)
        && (filterState.year === 'all' || String(m.year) === filterState.year)
        && (m.distance >= filterState.dist_min && m.distance <= filterState.dist_max);
      if (ok) {
        clusters.addLayer(leafletMarkers[i]);
        visibleMarkers.push(m);
        shown.push([m.lat, m.lng]);
      }
    });
    visibleCoords = shown;  // reset re-frames the active filter, not every marker
    renderAllRoutes();      // keep the all-routes overlay in sync with the filter
    frameVisible();         // frame the matches (full routes when the overlay is on)
    syncDashboard();        // recompute the dependent sections for the new filter
  }

  const searchInput = document.querySelector('.map-search-input');
  if (searchInput) {
    let searchTimer;
    searchInput.addEventListener('input', function() {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function() { filterState.q = searchInput.value; applyFilters(); }, 200);
    });
  }

  // Distance range slider (shared DSDistSlider module). Filtering runs client-side on
  // release; the sport dropdown rescales the track to the selected sport's ceiling.
  const distCeils = window.DSDistSlider.ceils('map-dist-ceils');
  const distSlider = window.DSDistSlider.build(document.getElementById('map-dist-slider'), {
    onChange: function(lo, hi) { filterState.dist_min = lo; filterState.dist_max = hi; applyFilters(); }
  });
  if (distSlider) { filterState.dist_min = distSlider.min(); filterState.dist_max = distSlider.max(); }

  // Sport / gear / year all use shared dropdown modules (options come from the server so
  // GPS-less activities' sports/gear/years appear too, matching the stats sync). Each
  // onSelect updates filterState and re-runs the client-side marker filter.
  const sportBtn = document.getElementById('map-sport-btn');
  if (sportBtn && window.DSSport) {
    filterState.sport = sportBtn.getAttribute('data-sport-current') || 'all';
    DSSport.build(sportBtn, { onSelect: function(value) {
      filterState.sport = value;
      // Rescale the distance slider to the newly-selected sport and reset the window, so
      // the reset dist_min/dist_max ride along in the same refresh.
      if (distSlider) {
        distSlider.setCeil(value in distCeils ? distCeils[value] : distCeils.all);
        filterState.dist_min = distSlider.min();
        filterState.dist_max = distSlider.max();
      }
      applyFilters();
    } });
  }
  const gearBtn = document.getElementById('map-gear-btn');
  if (gearBtn && window.DSPill) {
    filterState.gear = gearBtn.getAttribute('data-pill-current') || 'all';
    DSPill.build(gearBtn, {
      sections: [{ key: 'bike', label: 'Bikes' }, { key: 'shoe', label: 'Shoes' }],
      onSelect: function(value) { filterState.gear = value; applyFilters(); }
    });
  }
  const yearBtn = document.getElementById('map-year-btn');
  if (yearBtn && window.DSPill) {
    filterState.year = yearBtn.getAttribute('data-pill-current') || 'all';
    DSPill.build(yearBtn, { onSelect: function(value) { filterState.year = value; applyFilters(); } });
  }
})();
