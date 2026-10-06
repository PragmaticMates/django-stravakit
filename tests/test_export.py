"""The activities Excel export: what lands in the workbook and how the page links to it.

The view tests go through the URLconf (``tests.urls`` includes ``stravakit.urls``), so a
rename of the route or a change to the response headers shows up here. The ``q=`` search
param is avoided for the usual reason: it needs PostgreSQL's ``unaccent``.
"""
import datetime
import io
from datetime import timezone as tz

import pytest
from django.test import RequestFactory
from django.urls import reverse
from openpyxl import load_workbook

from stravakit import export
from stravakit.models import Activity, Athlete, Gear
from stravakit.views import ActivitiesExportView, ActivitiesView


def dt(y, m, d, h=12):
    return datetime.datetime(y, m, d, h, tzinfo=tz.utc)


def make_activity(id, sport_type="Run", distance=10000, moving_time=3000, start_date=None,
                  gear=None, is_private=False, json=None, athlete=None, elevation=100):
    return Activity.objects.create(
        id=id,
        name=f"Activity {id}",
        start_date=start_date or dt(2025, 6, 15),
        sport_type=sport_type,
        distance=distance,
        moving_time=moving_time,
        elapsed_time=moving_time + 60,
        total_elevation_gain=elevation,
        average_speed=distance / moving_time,
        gear=gear,
        athlete=athlete,
        is_private=is_private,
        json={"id": id, **(json or {})},
    )


def workbook_from(response):
    assert response.status_code == 200
    assert response["Content-Type"] == export.XLSX_CONTENT_TYPE
    return load_workbook(io.BytesIO(response.content))


def export_response(**params):
    request = RequestFactory().get(reverse("stravakit:activities_export"), params)
    return ActivitiesExportView.as_view()(request)


def rows_of(sheet):
    return [[cell.value for cell in row] for row in sheet.iter_rows(min_row=2)]


@pytest.mark.django_db
class TestActivitiesExportView:
    def test_download_headers_name_an_xlsx(self):
        response = export_response()
        workbook_from(response)
        disposition = response["Content-Disposition"]
        assert disposition.startswith('attachment; filename="strava-activities-')
        assert disposition.endswith('.xlsx"')

    def test_filename_folds_the_athlete_name_to_ascii(self):
        athlete = Athlete.objects.create(id=1, firstname="Erik", lastname="Telepovský", json={})
        assert export.export_filename(athlete).startswith("strava-activities-erik-telepovsky-")
        assert export.export_filename(None).startswith("strava-activities-2")

    def test_one_row_per_public_activity_with_the_header_in_front(self):
        make_activity(1)
        make_activity(2, is_private=True)
        sheet = workbook_from(export_response())["Activities"]
        headers = [cell.value for cell in sheet[1]]
        assert headers[:3] == ["ID", "Name", "Date"]
        assert headers[-1] == "Strava"
        rows = rows_of(sheet)
        assert [row[0] for row in rows] == [1]

    def test_filters_and_sort_are_the_pages_own(self):
        make_activity(1, "Run", distance=5000, start_date=dt(2024, 3, 1))
        make_activity(2, "Run", distance=12000, start_date=dt(2025, 3, 1))
        make_activity(3, "Ride", distance=40000, start_date=dt(2025, 4, 1))
        sheet = workbook_from(export_response(year="2025", sort="dist", dir="asc"))["Activities"]
        assert [row[0] for row in rows_of(sheet)] == [2, 3]

    def test_cells_carry_converted_units_and_the_strava_link(self):
        gear = Gear.objects.create(id="g1", brand_name="Nike", model_name="Pegasus",
                                   description="", gear_type="shoe", json={})
        make_activity(7, distance=10000, moving_time=3000, gear=gear,
                      json={"start_date_local": "2025-06-15T14:00:00Z", "device_name": "Garmin"})
        sheet = workbook_from(export_response())["Activities"]
        (row,) = rows_of(sheet)
        header = [cell.value for cell in sheet[1]]
        cell = dict(zip(header, row))
        assert cell["Date"] == datetime.datetime(2025, 6, 15, 14, 0)
        assert cell["Year"] == "=YEAR(C2)"
        assert cell["Distance (km)"] == 10.0
        assert cell["Moving time"] == datetime.timedelta(seconds=3000)
        assert cell["Avg speed (km/h)"] == 12.0
        assert cell["Gear"] == "Nike Pegasus"
        assert cell["Device"] == "Garmin"
        assert cell["Strava"] == "https://strava.com/activities/7"
        assert sheet.cell(row=2, column=export.LINK_COLUMN).hyperlink.target == cell["Strava"]

    def test_local_start_falls_back_to_the_project_timezone(self):
        activity = make_activity(1, start_date=dt(2025, 6, 15, 12))
        assert export.local_start(activity).tzinfo is None
        assert export.local_start(activity).date() == datetime.date(2025, 6, 15)

    def test_summary_formulas_span_exactly_the_data_rows(self):
        make_activity(1, "Run", start_date=dt(2024, 3, 1))
        make_activity(2, "Ride", start_date=dt(2025, 3, 1))
        make_activity(3, "Ride", start_date=dt(2025, 4, 1))
        summary = workbook_from(export_response())["Summary"]
        assert summary["A1"].value == "Year"
        assert [summary[f"A{r}"].value for r in (2, 3, 4)] == [2024, 2025, "Total"]
        assert summary["B2"].value == "=COUNTIF(Activities!$D$2:$D$4,A2)"
        assert summary["C2"].value == "=SUMIF(Activities!$D$2:$D$4,A2,Activities!$F$2:$F$4)"
        assert summary["B4"].value == "=SUM(B2:B3)"
        # The sport block follows the year block after a blank row.
        assert summary["A6"].value == "Sport"
        assert [summary[f"A{r}"].value for r in (7, 8, 9)] == ["Ride", "Run", "Total"]
        assert summary["B7"].value == "=COUNTIF(Activities!$E$2:$E$4,A7)"

    def test_empty_result_is_still_a_valid_workbook(self):
        workbook = workbook_from(export_response(year="1999"))
        assert rows_of(workbook["Activities"]) == []
        assert workbook["Summary"]["A1"].value == "No activities match the filter."

    def test_page_context_links_to_the_export_with_the_same_query(self):
        view = ActivitiesView()
        view.setup(RequestFactory().get("/", {"year": "2025", "sort": "dist"}))
        view.object_list = view.get_queryset()
        url = view.get_context_data()["export_url"]
        assert url.startswith(reverse("stravakit:activities_export") + "?")
        assert "year=2025" in url and "sort=dist" in url
