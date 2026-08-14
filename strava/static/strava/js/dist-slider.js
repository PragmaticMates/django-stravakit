/* django-stravakit · shared dual-handle distance range slider */
// Two overlapping range inputs kept from crossing, with a painted fill between them and a
// live km readout. Backs the distance filter on both the activities filter bar and the
// dashboard map filter bar. `build` returns a controller (or null when the root is
// absent); `ceils` reads the per-sport ceiling map emitted alongside the slider.
window.DSDistSlider = (function() {
  // Wire up a `.af-dist` root. `onChange(lo, hi)` fires on release (native `change`);
  // pass it when the slider isn't inside a form that already listens for `change`.
  function build(root, opts) {
    if (!root) return null;
    opts = opts || {};
    var ceil = Number(root.dataset.ceil) || 1;
    var track = root.querySelector('.af-dist-track');
    var lo = root.querySelector('.af-dist-min');
    var hi = root.querySelector('.af-dist-max');
    var loOut = root.querySelector('.af-dist-lo');
    var hiOut = root.querySelector('.af-dist-hi');

    function paint() {
      track.style.setProperty('--lo-pct', (lo.value / ceil * 100) + '%');
      track.style.setProperty('--hi-pct', (hi.value / ceil * 100) + '%');
      loOut.textContent = lo.value;
      hiOut.textContent = hi.value;
    }

    lo.addEventListener('input', function() {
      if (Number(lo.value) > Number(hi.value)) lo.value = hi.value;
      paint();
    });
    hi.addEventListener('input', function() {
      if (Number(hi.value) < Number(lo.value)) hi.value = lo.value;
      paint();
    });
    if (opts.onChange) {
      var fire = function() { opts.onChange(Number(lo.value), Number(hi.value)); };
      lo.addEventListener('change', fire);
      hi.addEventListener('change', fire);
    }
    paint();

    return {
      min: function() { return Number(lo.value); },
      max: function() { return Number(hi.value); },
      // Rescale to a new upper bound and reset the window to the full range — the old
      // handle positions are meaningless against a different sport's distances.
      setCeil: function(newCeil) {
        ceil = Number(newCeil) || 1;
        lo.max = hi.max = ceil;
        root.dataset.ceil = ceil;
        lo.value = 0;
        hi.value = ceil;
        paint();
      }
    };
  }

  // Per-sport distance ceilings ('all' / group key / sport_type → km), see the views'
  // distance_slider_context. Returns {} when the JSON script element is absent.
  function ceils(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : {};
  }

  return { build: build, ceils: ceils };
})();
