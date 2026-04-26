import math
from typing import Iterable, Tuple


EARTH_RADIUS_MILES = 3958.8


def haversine_miles(point_a: Tuple[float, float], point_b: Tuple[float, float]) -> float:
    """Return great-circle distance in miles between (lat, lon) points."""
    lat1, lon1 = point_a
    lat2, lon2 = point_b

    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_MILES * c


def min_distance_to_route_miles(point: Tuple[float, float], route_points: Iterable[Tuple[float, float]]) -> float:
    """Return minimum distance from a point to any sampled route coordinate."""
    min_distance = float("inf")
    for route_point in route_points:
        distance = haversine_miles(point, route_point)
        if distance < min_distance:
            min_distance = distance
    return min_distance
