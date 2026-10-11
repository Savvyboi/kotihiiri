"""The site's demo dataset must stay valid against the models and the PII rules."""

from pathlib import Path

from kunta.validate import validate_city

DEMO = Path(__file__).resolve().parent.parent / "site" / "demo-data"


def test_demo_data_is_valid():
    for city in ("helsinki", "espoo", "tampere", "vantaa"):
        report = validate_city(city, DEMO)
        assert report.files > 0
        assert report.ok, report.errors
