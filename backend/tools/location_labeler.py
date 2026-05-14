from dataclasses import dataclass
import logging
from math import atan2, cos, radians, sin, sqrt
from typing import Protocol

import httpx

from backend.schemas import Location
from backend.settings import Settings

logger = logging.getLogger("uvicorn.error")


GENERIC_LOCATION_LABELS = {
    None,
    "",
    "Current phone location",
    "Location provided without a label",
    "Approximate location",
}

NYC_COUNTY_TO_BOROUGH = {
    "New York County": "Manhattan",
    "Kings County": "Brooklyn",
    "Queens County": "Queens",
    "Bronx County": "Bronx",
    "Richmond County": "Staten Island",
}


@dataclass(frozen=True)
class KnownPlace:
    label: str
    latitude: float
    longitude: float
    street_address: str | None
    intersection: str | None
    neighborhood: str
    borough: str
    radius_meters: float


@dataclass(frozen=True)
class ReverseGeocodeResult:
    label: str | None = None
    street_address: str | None = None
    intersection: str | None = None
    neighborhood: str | None = None
    borough: str | None = None
    source: str = "reverse geocoder"


class ReverseGeocoder(Protocol):
    def reverse_geocode(
        self,
        latitude: float,
        longitude: float,
    ) -> ReverseGeocodeResult | None:
        ...


class MapboxReverseGeocoder:
    def __init__(self, access_token: str, timeout_seconds: float = 1.5) -> None:
        self._access_token = access_token
        self._timeout_seconds = timeout_seconds
        self._cache: dict[tuple[float, float], ReverseGeocodeResult | None] = {}

    def reverse_geocode(
        self,
        latitude: float,
        longitude: float,
    ) -> ReverseGeocodeResult | None:
        cache_key = (round(latitude, 5), round(longitude, 5))
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            response = httpx.get(
                "https://api.mapbox.com/search/geocode/v6/reverse",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "access_token": self._access_token,
                    "country": "US",
                    "limit": 1,
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            result = _parse_mapbox_reverse_response(response.json())
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("mapbox reverse geocode failed: %s", type(exc).__name__)
            result = None

        if result:
            self._cache[cache_key] = result
        return result


def reverse_geocoder_from_settings(settings: Settings) -> ReverseGeocoder | None:
    mode = settings.location_label_mode.lower().strip()
    if mode in {"deterministic", "fallback", "off", ""}:
        return None
    if mode == "mapbox" and settings.mapbox_access_token:
        return MapboxReverseGeocoder(
            settings.mapbox_access_token,
            settings.reverse_geocode_timeout_seconds,
        )
    return None


KNOWN_PLACES = (
    KnownPlace(
        label="W 43rd St and 8th Ave school crossing, Theater District, Manhattan",
        latitude=40.7589,
        longitude=-73.9891,
        street_address=None,
        intersection="W 43rd St and 8th Ave",
        neighborhood="Theater District",
        borough="Manhattan",
        radius_meters=180,
    ),
    KnownPlace(
        label="Near City Hall Park, Civic Center, Manhattan",
        latitude=40.7128,
        longitude=-74.0060,
        street_address=None,
        intersection="Broadway and Park Row",
        neighborhood="Civic Center",
        borough="Manhattan",
        radius_meters=260,
    ),
)


def label_location(
    location: Location,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> Location:
    if location.latitude is None or location.longitude is None:
        return location

    if _has_reverse_geocode_source(location) and location.label not in GENERIC_LOCATION_LABELS:
        return location

    if reverse_geocoder:
        geocoded = reverse_geocoder.reverse_geocode(location.latitude, location.longitude)
        if geocoded:
            return _apply_reverse_geocode(location, geocoded)

    known_place = _nearest_known_place(location)
    if known_place:
        return _apply_known_place(location, known_place)

    borough = _borough_for_coordinates(location.latitude, location.longitude)
    label = location.label
    if label in GENERIC_LOCATION_LABELS:
        label = _fallback_coordinate_label(location, borough)

    return location.model_copy(
        update={
            "label": label,
            "borough": location.borough or borough,
            "source": location.source or "gps coordinate fallback",
        }
    )


def _apply_reverse_geocode(
    location: Location,
    result: ReverseGeocodeResult,
) -> Location:
    label = location.label
    if label in GENERIC_LOCATION_LABELS:
        label = result.label or _fallback_coordinate_label(
            location,
            result.borough
            or _borough_for_coordinates(location.latitude, location.longitude),
        )

    source = result.source
    if location.source:
        source = f"{location.source} + {result.source}"

    return location.model_copy(
        update={
            "label": label,
            "street_address": location.street_address or result.street_address,
            "intersection": location.intersection or result.intersection,
            "neighborhood": location.neighborhood or result.neighborhood,
            "borough": location.borough or result.borough,
            "source": source,
        }
    )


def _has_reverse_geocode_source(location: Location) -> bool:
    return bool(location.source and "reverse_geocoder:" in location.source)


def _apply_known_place(location: Location, place: KnownPlace) -> Location:
    label = location.label
    if label in GENERIC_LOCATION_LABELS:
        label = place.label

    return location.model_copy(
        update={
            "label": label,
            "street_address": location.street_address or place.street_address,
            "intersection": location.intersection or place.intersection,
            "neighborhood": location.neighborhood or place.neighborhood,
            "borough": location.borough or place.borough,
            "source": location.source or "deterministic demo geocoder",
        }
    )


def _nearest_known_place(location: Location) -> KnownPlace | None:
    nearest: tuple[float, KnownPlace] | None = None
    for place in KNOWN_PLACES:
        distance = _distance_meters(
            location.latitude,
            location.longitude,
            place.latitude,
            place.longitude,
        )
        if distance <= place.radius_meters and (
            nearest is None or distance < nearest[0]
        ):
            nearest = (distance, place)
    return nearest[1] if nearest else None


def _parse_mapbox_reverse_response(payload: dict) -> ReverseGeocodeResult | None:
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        return None

    feature = features[0]
    if not isinstance(feature, dict):
        return None

    properties = feature.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    context = properties.get("context")
    if not isinstance(context, dict):
        context = {}

    full_address = _string_or_none(properties.get("full_address"))
    name = _string_or_none(properties.get("name"))
    label = full_address or name

    neighborhood = _mapbox_context_name(context.get("neighborhood"))
    borough = _mapbox_context_name(context.get("district")) or _mapbox_context_name(
        context.get("place")
    )
    if borough in NYC_COUNTY_TO_BOROUGH:
        borough = NYC_COUNTY_TO_BOROUGH[borough]
    if borough == "New York":
        borough = None

    return ReverseGeocodeResult(
        label=label,
        street_address=full_address if full_address != name else None,
        neighborhood=neighborhood,
        borough=borough,
        source="reverse_geocoder:mapbox",
    )


def _mapbox_context_name(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    return _string_or_none(value.get("name"))


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _distance_meters(
    first_latitude: float,
    first_longitude: float,
    second_latitude: float,
    second_longitude: float,
) -> float:
    earth_radius_meters = 6_371_000
    lat_1 = radians(first_latitude)
    lat_2 = radians(second_latitude)
    delta_lat = radians(second_latitude - first_latitude)
    delta_lon = radians(second_longitude - first_longitude)
    a = (
        sin(delta_lat / 2) ** 2
        + cos(lat_1) * cos(lat_2) * sin(delta_lon / 2) ** 2
    )
    return earth_radius_meters * 2 * atan2(sqrt(a), sqrt(1 - a))


def _borough_for_coordinates(latitude: float, longitude: float) -> str | None:
    if 40.68 <= latitude <= 40.88 and -74.03 <= longitude <= -73.90:
        return "Manhattan"
    if 40.47 <= latitude <= 40.74 and -74.05 <= longitude <= -73.83:
        return "Brooklyn"
    if 40.54 <= latitude <= 40.81 and -73.96 <= longitude <= -73.70:
        return "Queens"
    if 40.78 <= latitude <= 40.92 and -73.93 <= longitude <= -73.76:
        return "Bronx"
    if 40.47 <= latitude <= 40.65 and -74.26 <= longitude <= -74.05:
        return "Staten Island"
    return None


def _fallback_coordinate_label(location: Location, borough: str | None) -> str:
    coordinate_label = f"{location.latitude:.5f}, {location.longitude:.5f}"
    if borough:
        return f"Approximate phone location in {borough} ({coordinate_label})"
    return f"Approximate phone location ({coordinate_label})"
