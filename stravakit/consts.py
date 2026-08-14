"""Shared constants for the strava app.

Plain, behaviour-free values collected in one place so models, analytics and views can
reference them without importing one another just to read a number.
"""

# Scalar fields present only on Strava's DetailedActivity (not SummaryActivity). They are
# null/absent for activities imported with summary data only, so their presence marks a
# fully-fetched payload — read_json promotes that into the `is_detailed` boolean column.
DETAIL_MARKER_FIELDS = ("embed_token", "calories", "description", "device_name")

# Short month labels for trend/compare axes (index 0 == January).
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

MAP_MARKER_LIMIT = 1000   # cap markers so a busy map stays readable

# Expected service life per gear type (km), used to compute wear percentage.
SHOE_LIFESPAN_KM = 700
BIKE_LIFESPAN_KM = 12000

# Gear not used within this many days (or never used) counts as "old" — hidden from the
# dashboard's no-filter view and selectable via the gear page's age filter.
GEAR_OLD_DAYS = 365

# --- Personal-record plausibility caps ---
# Rides averaging faster than this (km/h) are excluded from the fastest-avg-speed PR as
# implausible (GPS errors or mis-tagged motorized activities).
MAX_RIDE_AVG_KMH = 60
# Likewise for the instantaneous top-speed PR. Higher than the average cap, since real
# descents legitimately exceed 60 km/h; only clear GPS glitches are dropped.
MAX_RIDE_TOP_KMH = 100
# Hikes faster than this pace (seconds per km) are excluded from the hiking
# longest/fastest PRs — anything quicker than 7:00/km is almost certainly a mis-tagged run.
MIN_HIKE_PACE_SEC = 7 * 60

# --- Running-performance widget ---
# (display label, Strava best-effort name lowercased, distance in metres). Best times come
# from each run's `best_efforts`; the estimate is a Riegel projection
# (T2 = T1·(D2/D1)^1.06) from the athlete's best efforts.
RUN_PERF_DISTANCES = [
    ('5 km', '5k', 5000.0),
    ('10 km', '10k', 10000.0),
    ('Half Marathon', 'half-marathon', 21097.5),
    ('Marathon', 'marathon', 42195.0),
]
RIEGEL_EXP = 1.06
# Riegel is only reliable when the reference and target distances are within
# roughly this factor of each other. Projecting a marathon from a short sprint
# split (e.g. a 400 m burst inside a run) yields absurdly fast, unrealistic
# times, so predictors outside [target / ratio, target * ratio] are ignored.
RIEGEL_MAX_RATIO = 3.0

# --- "By the Numbers" fun-stat reference values ---
EARTH_CIRCUMFERENCE_KM = 40075
EVEREST_HEIGHT_M = 8849
MARATHON_KM = 42.195
CO2_KG_PER_KM = 0.12   # ~avg car tailpipe CO2 per km, avoided by cycling instead
