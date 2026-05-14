import httpx

from backend.schemas import Location
from backend.tools import location_labeler
from backend.tools.location_labeler import (
    MapboxReverseGeocoder,
    ReverseGeocodeResult,
    label_location,
)


class StubResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_mapbox_reverse_geocoder_parses_and_caches_success(monkeypatch) -> None:
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return StubResponse(
            {
                "features": [
                    {
                        "properties": {
                            "full_address": "101 Avenue A, New York, NY 10009",
                            "name": "101 Avenue A",
                            "context": {
                                "neighborhood": {"name": "East Village"},
                                "district": {"name": "Manhattan"},
                            },
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(location_labeler.httpx, "get", fake_get)

    geocoder = MapboxReverseGeocoder("test-token")
    first = geocoder.reverse_geocode(40.7271, -73.9837)
    second = geocoder.reverse_geocode(40.7271001, -73.9837001)

    assert calls == 1
    assert first == second
    assert first is not None
    assert first.label == "101 Avenue A, New York, NY 10009"
    assert first.neighborhood == "East Village"
    assert first.borough == "Manhattan"
    assert first.source == "reverse_geocoder:mapbox"


def test_mapbox_reverse_geocoder_normalizes_nyc_county_to_borough(monkeypatch) -> None:
    def fake_get(*args, **kwargs):
        return StubResponse(
            {
                "features": [
                    {
                        "properties": {
                            "name": "115 Saint Marks Place",
                            "context": {
                                "neighborhood": {"name": "Alphabet City"},
                                "district": {"name": "New York County"},
                            },
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(location_labeler.httpx, "get", fake_get)

    result = MapboxReverseGeocoder("test-token").reverse_geocode(40.7271, -73.9837)

    assert result is not None
    assert result.neighborhood == "Alphabet City"
    assert result.borough == "Manhattan"


def test_mapbox_reverse_geocoder_does_not_cache_failures(monkeypatch) -> None:
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary dns failure")
        return StubResponse(
            {
                "features": [
                    {
                        "properties": {
                            "name": "East 8th Street",
                            "context": {
                                "neighborhood": {"name": "East Village"},
                                "district": {"name": "Manhattan"},
                            },
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(location_labeler.httpx, "get", fake_get)

    geocoder = MapboxReverseGeocoder("test-token")

    assert geocoder.reverse_geocode(40.7271, -73.9837) is None
    second = geocoder.reverse_geocode(40.7271, -73.9837)

    assert calls == 2
    assert second is not None
    assert second.label == "East 8th Street"


def test_label_location_preserves_existing_reverse_geocoded_location() -> None:
    class FailingIfCalledGeocoder:
        def reverse_geocode(self, latitude: float, longitude: float):
            raise AssertionError("reverse geocoder should not be called")

    location = Location(
        label="Near E 8th St and Avenue A",
        latitude=40.7271,
        longitude=-73.9837,
        source="browser geolocation + reverse_geocoder:mapbox",
    )

    labeled = label_location(location, FailingIfCalledGeocoder())

    assert labeled.label == "Near E 8th St and Avenue A"
    assert labeled.source == "browser geolocation + reverse_geocoder:mapbox"


def test_label_location_uses_reverse_geocoder_result_with_provenance() -> None:
    class StubGeocoder:
        def reverse_geocode(self, latitude: float, longitude: float):
            return ReverseGeocodeResult(
                label="Near E 8th St and Avenue A",
                intersection="E 8th St and Avenue A",
                neighborhood="East Village",
                borough="Manhattan",
                source="reverse_geocoder:test",
            )

    location = Location(
        label="Current phone location",
        latitude=40.7271,
        longitude=-73.9837,
        accuracy_meters=12,
        source="browser geolocation",
    )

    labeled = label_location(location, StubGeocoder())

    assert labeled.label == "Near E 8th St and Avenue A"
    assert labeled.intersection == "E 8th St and Avenue A"
    assert labeled.neighborhood == "East Village"
    assert labeled.borough == "Manhattan"
    assert labeled.source == "browser geolocation + reverse_geocoder:test"
