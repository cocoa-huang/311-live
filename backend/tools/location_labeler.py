from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt

from backend.schemas import Location


GENERIC_LOCATION_LABELS = {
    None,
    "",
    "Current phone location",
    "Location provided without a label",
    "Approximate location",
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


def label_location(location: Location) -> Location:
    if location.latitude is None or location.longitude is None:
        return location

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
