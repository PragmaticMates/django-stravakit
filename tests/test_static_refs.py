"""Every {% static %} path in a template must name a file that ships.

Nothing else catches this. With DEBUG=True the static tag builds a URL without
touching the filesystem, so a stale path renders a dead link and the page looks
fine; only ManifestStaticFilesStorage — i.e. production — turns it into a
"Missing staticfiles manifest entry" ValueError and a 500. Renaming the static
directory once left ``stravakit/css/strava.css`` behind pointing at a file that
had become ``stravakit.css``, and every page but the admin went down.
"""
import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "stravakit"
STATIC_ROOT = PACKAGE_ROOT / "static"
STATIC_TAG = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]""")


def _static_references():
    for template in sorted(PACKAGE_ROOT.rglob("*.html")):
        for match in STATIC_TAG.finditer(template.read_text()):
            yield match.group(1), template


@pytest.mark.parametrize(
    "reference,template",
    list(_static_references()),
    ids=lambda value: value if isinstance(value, str) else value.name,
)
def test_static_reference_exists(reference, template):
    assert (STATIC_ROOT / reference).is_file(), f"{template} references missing static file {reference!r}"


def test_every_shipped_static_file_is_referenced():
    """The reverse guard: a file nothing points at is usually a rename half-done."""
    referenced = {reference for reference, _ in _static_references()}
    shipped = {str(path.relative_to(STATIC_ROOT)) for path in STATIC_ROOT.rglob("*") if path.is_file()}
    assert shipped - referenced == set()
