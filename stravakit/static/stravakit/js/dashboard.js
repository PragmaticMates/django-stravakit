/* django-stravakit · dashboard wiring (non-map): records/calendar/trends,
   lazy float-card route rendering, activity modal, row-height sync, gear donut. */

/* ---- Records, calendar & trends charts (formerly classic-data.js) ---- */
(function () {
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];

  function readJSON(id) {
    const el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }

  /* ---- Trends series (real data from the server) ---- */
  // Re-read on a filter change (ds:datachanged) so the chart tracks the active filter.
  let weekly = [], monthly = [], yearly = [];
  function loadTrends() {
    const realTrends = readJSON("dashboard-trends") || {};
    weekly = realTrends.weekly || [];
    monthly = realTrends.monthly || [];
    yearly = realTrends.yearly || [];
  }
  loadTrends();

  /* ---- Personal records (per sport, real data from the server) ---- */
  // Each record is tied to the activity that set it; clicking a row opens that
  // activity's card (window.openActivityModal). Re-read on a filter change so the
  // records track the active filter like every other section.
  let records = readJSON("dashboard-records") || {};
  let recSport = "Running";
  const recList = $("#rec-list");
  function showRecords(sport) {
    recSport = sport;
    const rows = records[sport] || [];
    recList.innerHTML = rows.length
      ? rows.map(r => `
          <div class="kv kv-record" role="button" tabindex="0" data-activity="${r.id}"
               title="View activity">
            <span class="k">${r.label}</span>
            <span class="v">${r.value}${r.unit ? ` <small>${r.unit}</small>` : ""}</span>
          </div>`).join("")
      : `<div class="rec-empty">No ${sport.toLowerCase()} activities yet.</div>`;
    $$("#rec-tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.sport === sport));
  }
  $("#rec-tabs").addEventListener("click", e => {
    const b = e.target.closest("button"); if (b) showRecords(b.dataset.sport);
  });
  function openRecord(row) {
    if (row && row.dataset.activity && window.openActivityModal) {
      window.openActivityModal(row.dataset.activity);
    }
  }
  recList.addEventListener("click", e => openRecord(e.target.closest(".kv-record")));
  recList.addEventListener("keydown", e => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest(".kv-record");
    if (row) { e.preventDefault(); openRecord(row); }
  });
  showRecords(recSport);
  // A filter change swaps in fresh records JSON — reload and re-render the active tab.
  window.addEventListener("ds:datachanged", () => {
    records = readJSON("dashboard-records") || {};
    showRecords(recSport);
  });

  /* ---- Activity calendar dots (5-week window, sizes 0–2, with paging) ---- */
  // The server embeds every week from the first activity to now; we show a sliding
  // 5-week window and page through the rest with the ‹ › arrows. Re-read on a filter
  // change (ds:datachanged) so the dots track the active filter.
  const CAL_WIN = 5;
  let calWeeks = [], calStart = 0;
  function renderCalendar() {
    const total = calWeeks.length;
    calStart = Math.max(0, Math.min(calStart, total - CAL_WIN));
    const view = calWeeks.slice(calStart, calStart + CAL_WIN);
    $("#dotcal-rows").innerHTML = view.map(w => `
      <span class="wk">${w.label}</span>
      ${w.dots.map(s => `<span class="dot" data-s="${s}"></span>`).join("")}`).join("");
    const range = $("#cal-range");
    if (range) range.textContent = view.length
      ? `${view[0].label.split(" – ")[0]} – ${view[view.length - 1].label.split(" – ").pop()}`
      : "";
    const prev = $("#cal-prev"), next = $("#cal-next");
    if (prev) prev.disabled = calStart <= 0;
    if (next) next.disabled = calStart + CAL_WIN >= total;
  }
  function loadCalendar() {
    calWeeks = readJSON("dashboard-calendar") || [];
    calStart = calWeeks.length;  // clamp lands on the most recent window
    renderCalendar();
  }
  $("#cal-prev").addEventListener("click", () => { calStart -= CAL_WIN; renderCalendar(); });
  $("#cal-next").addEventListener("click", () => { calStart += CAL_WIN; renderCalendar(); });
  loadCalendar();

  /* ---- Charts ---- */
  const tip = $("#tip-trend");
  let metric = "km", range = "weekly";
  const rows = () => range === "weekly" ? weekly :
                     range === "monthly" ? monthly : yearly;
  function draw() {
    const host = $("#trend-host");
    const data = rows();
    if (!data.length) { host.innerHTML = '<div class="chart-empty">No activity data yet.</div>'; return; }
    window.DSCharts.renderTrends(host, data, metric, tip);
  }
  draw();
  $("#seg-metric").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    metric = b.dataset.metric;
    $$("#seg-metric button").forEach(x => x.setAttribute("aria-pressed", x === b));
    draw();
  });
  $("#seg-range").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    range = b.dataset.range;
    $$("#seg-range button").forEach(x => x.setAttribute("aria-pressed", x === b));
    draw();
  });
  let rsT;
  window.addEventListener("resize", () => { clearTimeout(rsT); rsT = setTimeout(draw, 120); });
  window.addEventListener("ds:tweaks", () => requestAnimationFrame(draw));
  // A filter change swaps in fresh trends/calendar JSON — reload and redraw both.
  window.addEventListener("ds:datachanged", () => {
    loadTrends();
    loadCalendar();
    requestAnimationFrame(draw);
  });
})();

/* ---- Float-card route rendering + activity modal ---- */
  // Render a float card's route trace, once, the first time the card is shown.
  // Float cards are hidden until their marker is clicked, so rendering every card's
  // route up front (a heavy polyline decode + SVG build per activity) needlessly
  // blocked page load — slow with a large map. Map markers call this lazily.
  window.renderCardRoute = function(card) {
    if (!card) return;
    var svg = card.querySelector('.fc-route[data-polyline]');
    if (svg) window.DSCharts.renderRouteSvg(svg);
  };
  // Render only the cards already visible on load (e.g. the latest-activity hero).
  document.querySelectorAll('.float-card').forEach(function(card) {
    if (card.offsetParent !== null) window.renderCardRoute(card);
  });

  // ---- Activity modal: a centered overlay showing one activity's card ----
  // Opened from clickable widgets (e.g. Personal Records rows). The card HTML is
  // fetched on demand from ActivityCardView, the same endpoint the map markers use.
  (function() {
    const modal = document.getElementById('activity-modal');
    if (!modal) return;
    const host = modal.querySelector('.act-modal-host');
    const cardUrl = function(id) { return modal.dataset.cardUrl.replace('/0/card/', '/' + id + '/card/'); };

    function close() {
      modal.hidden = true;
      host.innerHTML = '';
      document.body.classList.remove('modal-open');
    }

    window.openActivityModal = function(id) {
      fetch(cardUrl(id), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function(r) { return r.ok ? r.text() : ''; })
        .then(function(html) {
          if (!html) return;
          host.innerHTML = html;
          // Reveal the modal before drawing the route: the map-backed trace measures
          // the card's .fc-map, which has no size while the modal is display:none.
          modal.hidden = false;
          document.body.classList.add('modal-open');
          const card = host.querySelector('.float-card');
          if (card) {
            card.style.display = '';
            if (window.renderCardRoute) window.renderCardRoute(card);
            const closeBtn = card.querySelector('.fc-close');
            if (closeBtn) closeBtn.addEventListener('click', close);
          }
        });
    };

    modal.querySelector('.act-modal-backdrop').addEventListener('click', close);
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && !modal.hidden) close();
    });

    // Running Performance "Best Time" values open the activity that set them. The card
    // is OOB-swapped on a filter change, so delegate from the document to catch the
    // freshly-swapped elements too.
    document.addEventListener('click', function(e) {
      const el = e.target.closest('.perf-best-link');
      if (el && el.dataset.activity) window.openActivityModal(el.dataset.activity);
    });
    document.addEventListener('keydown', function(e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const el = e.target.closest('.perf-best-link');
      if (el && el.dataset.activity) { e.preventDefault(); window.openActivityModal(el.dataset.activity); }
    });
  })();

  // After a filter swaps in fresh sections, draw the new latest-activity card routes
  // and tell the charts/calendar/donut to reload their data (ds:datachanged) and the
  // trends/calendar cards to re-equalise their heights (ds:tweaks).
  document.body.addEventListener('htmx:afterSettle', function(e) {
    if (e.target && e.target.id !== 'dash-sink') return;
    document.querySelectorAll('#latest-activities .float-card').forEach(function(card) {
      if (card.offsetParent !== null) window.renderCardRoute(card);
    });
    window.dispatchEvent(new Event('ds:datachanged'));
    window.dispatchEvent(new Event('ds:tweaks'));
  });

/* ---- Trends/calendar row-height sync ---- */
  function syncRowHeights() {
    const trends = document.querySelector('.row-trends-aoty section.card:last-child');
    const cal = document.querySelector('.row-trends-aoty section.card:first-child');
    if (!trends || !cal) return;
    cal.style.minHeight = '';
    // Stacked single-column on mobile — don't stretch the calendar to the chart's height.
    if (window.matchMedia('(max-width: 900px)').matches) return;
    cal.style.minHeight = trends.getBoundingClientRect().height + 'px';
  }
  window.addEventListener('load', syncRowHeights);
  window.addEventListener('resize', syncRowHeights);
  window.addEventListener('ds:tweaks', syncRowHeights);

/* ---- Gear usage donut ---- */
  // Gear donut chart
  (function() {
    // Re-read on a filter change (ds:datachanged) so the donut tracks the active filter.
    let data = [];
    let total = 0;
    let metric = 'acts'; // 'acts' | 'dist'
    function computeTotal() { total = data.reduce((s, d) => s + d[metric], 0); }
    function loadData() {
      const dataEl = document.getElementById('dashboard-gear-usage');
      data = dataEl ? JSON.parse(dataEl.textContent) : [];
      computeTotal();
    }

    let hoveredIdx = -1;
    const segments = []; // {startAngle, endAngle}

    function draw(canvas, hovered) {
      const dpr = window.devicePixelRatio || 1;
      const size = 260;
      canvas.width = size * dpr; canvas.height = size * dpr;
      canvas.style.width = size + 'px'; canvas.style.height = size + 'px';
      const ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);
      const cx = size/2, cy = size/2, r = 86, inner = 55;
      segments.length = 0;
      // Reserve one gap per segment out of the full circle so sweeps + gaps sum to
      // exactly 2π; otherwise the last segment wraps past the top under the first.
      const gap = 0.015;
      const avail = Math.PI * 2 - data.length * gap;
      let angle = -Math.PI / 2;
      data.forEach((d, i) => {
        const sweep = total ? (d[metric] / total) * avail : 0;
        const isHov = i === hovered;
        const rOuter = isHov ? r + 6 : r;
        ctx.beginPath();
        ctx.moveTo(cx + rOuter * Math.cos(angle), cy + rOuter * Math.sin(angle));
        ctx.arc(cx, cy, rOuter, angle, angle + sweep);
        ctx.arc(cx, cy, inner, angle + sweep, angle, true);
        ctx.closePath();
        ctx.fillStyle = isHov ? d.hoverColor : d.color;
        ctx.fill();
        segments.push({ startAngle: angle, endAngle: angle + sweep });
        angle += sweep + gap;
      });
      // Center text
      const numFont = getComputedStyle(document.documentElement).getPropertyValue('--font-numbers').trim().replace(/"/g,'').split(',')[0].trim() || 'Barlow Condensed';
      const label = metric === 'dist' ? 'km' : 'activities';
      // While a segment is hovered, show that gear's usage; otherwise the grand total.
      const centerVal = (hovered >= 0 && data[hovered]) ? data[hovered][metric] : total;
      const valStr = centerVal.toLocaleString('en-US');
      const numSize = valStr.length > 6 ? 30 : valStr.length > 4 ? 36 : 44;
      ctx.fillStyle = '#1F1B18';
      ctx.font = `800 ${numSize}px "${numFont}", "Barlow Condensed", sans-serif`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(valStr, cx, cy - 10);
      ctx.fillStyle = '#888'; ctx.font = '500 14px Barlow, sans-serif';
      ctx.fillText(label, cx, cy + 14);
    }

    function renderDonut() {
      const canvas = document.getElementById('gear-donut');
      const legend = document.getElementById('gear-donut-legend');
      if (!canvas || !legend) return;
      draw(canvas, hoveredIdx);
      legend.innerHTML = data.map((d, i) => `
        <div class="donut-legend-item" data-idx="${i}">
          <span class="donut-legend-dot" style="background:${d.color}"></span>
          <span class="donut-legend-name">${d.name}</span>
        </div>`).join('');
      syncLegend(hoveredIdx);
    }

    // Reflect the hovered segment in the legend: dim the rest, highlight the match.
    function syncLegend(idx) {
      const legend = document.getElementById('gear-donut-legend');
      if (!legend) return;
      const items = legend.querySelectorAll('.donut-legend-item');
      legend.classList.toggle('has-hover', idx >= 0);
      items.forEach((el, i) => el.classList.toggle('is-active', i === idx));
    }

    // Bind hover behaviour once; it reads the current segments/data each move.
    function bindHover() {
      const canvas = document.getElementById('gear-donut');
      if (!canvas) return;
      canvas.addEventListener('mousemove', (e) => {
        const rect = canvas.getBoundingClientRect();
        const size = 260;
        const mx = (e.clientX - rect.left) * (size / rect.width);
        const my = (e.clientY - rect.top) * (size / rect.height);
        const cx = size/2, cy = size/2, r = 86, inner = 55;
        const dx = mx - cx, dy = my - cy;
        const dist = Math.sqrt(dx*dx + dy*dy);
        let found = -1;
        if (dist >= inner && dist <= r + 6) {
          let a = Math.atan2(dy, dx);
          if (a < -Math.PI/2) a += Math.PI * 2;
          segments.forEach((seg, i) => {
            let s = seg.startAngle, en = seg.endAngle;
            if (s < -Math.PI/2) { s += Math.PI*2; en += Math.PI*2; }
            if (a >= s && a <= en) found = i;
          });
        }
        canvas.style.cursor = found >= 0 ? 'pointer' : 'default';
        if (found !== hoveredIdx) { hoveredIdx = found; draw(canvas, hoveredIdx); syncLegend(hoveredIdx); }
      });
      canvas.addEventListener('mouseleave', () => {
        hoveredIdx = -1; draw(canvas, -1); syncLegend(-1);
      });
    }

    // Reverse direction: hovering a legend item highlights the matching segment.
    // Delegated on the container so it survives the legend's innerHTML rebuilds.
    function bindLegendHover() {
      const legend = document.getElementById('gear-donut-legend');
      const canvas = document.getElementById('gear-donut');
      if (!legend || !canvas) return;
      const setFromEvent = (e) => {
        const item = e.target.closest('.donut-legend-item');
        const idx = item ? parseInt(item.dataset.idx, 10) : -1;
        if (idx !== hoveredIdx) { hoveredIdx = idx; draw(canvas, hoveredIdx); syncLegend(hoveredIdx); }
      };
      legend.addEventListener('mouseover', setFromEvent);
      legend.addEventListener('mouseleave', () => {
        hoveredIdx = -1; draw(canvas, -1); syncLegend(-1);
      });
    }

    // Switch the donut between activity-count and distance weighting.
    function bindMetricToggle() {
      const seg = document.getElementById('seg-gear-metric');
      if (!seg) return;
      seg.addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b || b.dataset.gmetric === metric) return;
        metric = b.dataset.gmetric;
        seg.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b));
        computeTotal();
        renderDonut();
      });
    }

    window.addEventListener('load', () => { loadData(); bindHover(); bindLegendHover(); bindMetricToggle(); renderDonut(); });
    window.addEventListener('ds:tweaks', renderDonut);
    window.addEventListener('ds:datachanged', () => { hoveredIdx = -1; loadData(); renderDonut(); });
  })();
