/* django-stravakit · gear page — gear detail sheet */
function wearColor(pct) {
  if (pct < 40) return '#22C065';
  if (pct < 75) return '#F5A623';
  return '#EE4D0D';
}

function openSheet(card) {
  const d = card.dataset;
  const wear = parseInt(d.wear) || 0;
  document.getElementById('gs-name').textContent = d.name;
  document.getElementById('gs-brand').textContent = d.brand;
  // Reuse the card's own sport glyph (rendered from strava/sport_icons.py) so the
  // sheet stays in sync with the card and there's a single source of truth.
  document.getElementById('gs-img-icon').innerHTML = card.querySelector('.gear-card-img-icon').innerHTML;
  document.getElementById('gs-stats').innerHTML = `
    <div class="gear-sheet-stat">
      <div class="gear-sheet-stat-val">${d.km}</div>
      <div class="gear-sheet-stat-lbl">km logged</div>
    </div>
    <div class="gear-sheet-stat">
      <div class="gear-sheet-stat-val">${d.rides}</div>
      <div class="gear-sheet-stat-lbl">${d.ridesLabel}</div>
    </div>
    <div class="gear-sheet-stat">
      <div class="gear-sheet-stat-val">${wear}%</div>
      <div class="gear-sheet-stat-lbl">wear</div>
    </div>`;
  document.getElementById('gs-wear-pct').textContent = wear + '%';
  const fill = document.getElementById('gs-wear-fill');
  fill.style.width = wear + '%';
  fill.style.background = wearColor(wear);
  document.getElementById('gs-last-used').textContent = d.lastUsed;
  document.getElementById('gs-type').textContent = d.type;
  document.getElementById('gear-sheet').classList.add('open');
  document.addEventListener('keydown', sheetKeyHandler);
}

function closeSheet() {
  document.getElementById('gear-sheet').classList.remove('open');
  document.removeEventListener('keydown', sheetKeyHandler);
}
function closeSheetOnBg(e) {
  if (e.target === document.getElementById('gear-sheet')) closeSheet();
}
function sheetKeyHandler(e) {
  if (e.key === 'Escape') closeSheet();
}

function toggleDir() {
  const d = document.getElementById('g-dir');
  d.value = d.value === 'asc' ? 'desc' : 'asc';
  document.getElementById('gear-filters').requestSubmit();
}
