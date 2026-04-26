import csv
import os
from functools import lru_cache
from typing import Dict, List, Tuple

import requests
from django.conf import settings

from .utils import haversine_miles, min_distance_to_route_miles


RANGE_MILES = 500
MPG = 10
ROUTE_SAMPLING_STEP = 15
ROUTE_STATION_MAX_OFFSET_MILES = 25
ROUTE_STATION_FALLBACK_OFFSETS = (25, 75, 150, 250)
STATE_CENTERS = {
    "AL": (32.806671, -86.79113),
    "AR": (34.969704, -92.373123),
    "AZ": (34.048927, -111.093735),
    "CA": (36.7783, -119.4179),
    "CO": (39.550051, -105.782067),
    "CT": (41.603221, -73.087749),
    "DE": (38.910832, -75.52767),
    "FL": (27.664827, -81.515754),
    "GA": (32.157435, -82.907123),
    "IA": (41.878003, -93.097702),
    "ID": (44.068202, -114.742041),
    "IL": (40.633125, -89.398528),
    "IN": (40.551217, -85.602364),
    "KS": (39.011902, -98.484246),
    "KY": (37.839333, -84.270018),
    "LA": (30.984298, -91.962333),
    "MA": (42.407211, -71.382437),
    "MD": (39.045755, -76.641271),
    "ME": (45.253783, -69.445469),
    "MI": (44.314844, -85.602364),
    "MN": (46.729553, -94.6859),
    "MO": (37.964253, -91.831833),
    "MS": (32.354668, -89.398528),
    "MT": (46.879682, -110.362566),
    "NC": (35.759573, -79.0193),
    "ND": (47.551493, -101.002012),
    "NE": (41.492537, -99.901813),
    "NH": (43.193852, -71.572395),
    "NJ": (40.058324, -74.405661),
    "NM": (34.51994, -105.87009),
    "NV": (38.80261, -116.419389),
    "NY": (43.299428, -74.217933),
    "OH": (40.417287, -82.907123),
    "OK": (35.007752, -97.092877),
    "OR": (43.804133, -120.554201),
    "PA": (41.203322, -77.194525),
    "SC": (33.836081, -81.163725),
    "SD": (43.969515, -99.901813),
    "TN": (35.517491, -86.580447),
    "TX": (31.968599, -99.901813),
    "UT": (39.32098, -111.093731),
    "VA": (37.431573, -78.656894),
    "VT": (44.558803, -72.577841),
    "WA": (47.751074, -120.740139),
    "WI": (43.78444, -88.787868),
    "WV": (38.597626, -80.454903),
    "WY": (43.075968, -107.290284),
}


class RoutePlanningError(Exception):
    def __init__(self, message: str, payload: Dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


def _clean_float(value: str, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _state_coordinate(state_code: str) -> Tuple[float, float]:
    return STATE_CENTERS.get(state_code.upper(), (39.8283, -98.5795))


@lru_cache(maxsize=1)
def load_fuel_stations() -> List[Dict]:
    """
    Load stations once and reuse in memory.
    Coordinates are approximated with state center if not available.
    """
    csv_path = os.path.join(settings.BASE_DIR, "data", "fuel_stations.csv")
    stations: List[Dict] = []

    with open(csv_path, "r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            state = row.get("State", "").strip()
            lat = _clean_float(row.get("Latitude"))
            lon = _clean_float(row.get("Longitude"))
            if not lat or not lon:
                lat, lon = _state_coordinate(state)

            stations.append(
                {
                    "name": row.get("Truckstop Name", "").strip(),
                    "city": row.get("City", "").strip(),
                    "state": state,
                    "price": _clean_float(row.get("Retail Price"), 0.0),
                    "lat": lat,
                    "lon": lon,
                }
            )
    return stations


def fetch_route_from_openrouteservice(start: str, end: str) -> Dict:
    api_key = settings.OPENROUTESERVICE_API_KEY or os.getenv("OPENROUTESERVICE_API_KEY")
    if not api_key:
        raise RoutePlanningError("OpenRouteService API key is missing.")

    geocode_url = "https://api.openrouteservice.org/geocode/search"
    headers = {"Authorization": api_key}

    start_geo = requests.get(geocode_url, params={"api_key": api_key, "text": start, "size": 1}, timeout=20).json()
    end_geo = requests.get(geocode_url, params={"api_key": api_key, "text": end, "size": 1}, timeout=20).json()

    try:
        start_lon, start_lat = start_geo["features"][0]["geometry"]["coordinates"]
        end_lon, end_lat = end_geo["features"][0]["geometry"]["coordinates"]
    except (KeyError, IndexError, TypeError):
        raise RoutePlanningError("Invalid start or end location.")

    directions_url = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
    payload = {"coordinates": [[start_lon, start_lat], [end_lon, end_lat]]}
    response = requests.post(directions_url, json=payload, headers=headers, timeout=30)

    if response.status_code != 200:
        raise RoutePlanningError("Routing provider failed to compute a route.")

    data = response.json()
    try:
        if "features" in data:
            # GeoJSON response
            route_coordinates = data["features"][0]["geometry"]["coordinates"]
            summary = data["features"][0]["properties"]["summary"]
            distance_miles = summary["distance"] * 0.000621371
        elif "routes" in data:
            # Fallback for standard JSON response
            route = data["routes"][0]
            summary = route["summary"]
            distance_miles = summary["distance"] * 0.000621371
            geometry = route.get("geometry")
            if not isinstance(geometry, list):
                raise RoutePlanningError("Routing response does not include route coordinates.")
            route_coordinates = geometry
        else:
            raise RoutePlanningError("Unexpected route response format.")
    except (KeyError, IndexError, TypeError):
        raise RoutePlanningError("Unexpected route response format.")

    return {
        "route_coordinates": [[coord[1], coord[0]] for coord in route_coordinates],  # lat/lon
        "total_distance_miles": distance_miles,
        "start": (start_lat, start_lon),
        "end": (end_lat, end_lon),
    }


def _route_sample_points(route_points: List[List[float]]) -> List[Tuple[float, float]]:
    sampled = [tuple(point) for idx, point in enumerate(route_points) if idx % ROUTE_SAMPLING_STEP == 0]
    if route_points:
        sampled.append(tuple(route_points[-1]))
    return sampled


def _stations_near_route(route_points: List[List[float]], stations: List[Dict]) -> List[Dict]:
    sampled = _route_sample_points(route_points)
    filtered: List[Dict] = []
    for station in stations:
        offset = min_distance_to_route_miles((station["lat"], station["lon"]), sampled)
        if offset <= ROUTE_STATION_MAX_OFFSET_MILES:
            station_copy = dict(station)
            station_copy["route_offset_miles"] = offset
            filtered.append(station_copy)
    return filtered


def _stations_along_route_with_progress(
    route_points: List[List[float]],
    stations: List[Dict],
    max_offset_miles: float,
) -> List[Dict]:
    route_miles = _route_progress_miles(route_points)
    sampled = _route_sample_points(route_points)
    filtered: List[Dict] = []
    for station in stations:
        offset = min_distance_to_route_miles((station["lat"], station["lon"]), sampled)
        if offset > max_offset_miles:
            continue
        station_copy = dict(station)
        station_copy["route_offset_miles"] = offset
        station_copy["route_mile"] = _nearest_route_mile((station["lat"], station["lon"]), route_points, route_miles)
        filtered.append(station_copy)
    return filtered


def _route_bounding_box(route_points: List[List[float]], padding: float = 1.5) -> Tuple[float, float, float, float]:
    lats = [point[0] for point in route_points]
    lons = [point[1] for point in route_points]
    return (
        min(lats) - padding,
        max(lats) + padding,
        min(lons) - padding,
        max(lons) + padding,
    )


def _filter_stations_by_bbox(stations: List[Dict], route_points: List[List[float]], padding: float = 1.5) -> List[Dict]:
    if not route_points:
        return list(stations)
    min_lat, max_lat, min_lon, max_lon = _route_bounding_box(route_points, padding=padding)
    return [
        station
        for station in stations
        if min_lat <= station["lat"] <= max_lat and min_lon <= station["lon"] <= max_lon
    ]


def _route_progress_miles(route_points: List[List[float]]) -> List[float]:
    if not route_points:
        return []
    progress = [0.0]
    for idx in range(1, len(route_points)):
        prev = tuple(route_points[idx - 1])
        cur = tuple(route_points[idx])
        progress.append(progress[-1] + haversine_miles(prev, cur))
    return progress


def _nearest_route_mile(
    point: Tuple[float, float],
    route_points: List[List[float]],
    route_miles: List[float],
) -> float:
    if not route_points:
        return 0.0
    best_idx = 0
    best_distance = float("inf")
    for idx, route_point in enumerate(route_points):
        distance = haversine_miles(point, tuple(route_point))
        if distance < best_distance:
            best_distance = distance
            best_idx = idx
    return route_miles[best_idx]


def _stations_with_route_mile(
    stations: List[Dict],
    route_points: List[List[float]],
    route_miles: List[float],
) -> List[Dict]:
    enriched: List[Dict] = []
    for station in stations:
        station_copy = dict(station)
        station_copy["route_mile"] = _nearest_route_mile((station["lat"], station["lon"]), route_points, route_miles)
        enriched.append(station_copy)
    return enriched


def _pick_station_within_range(
    current: Tuple[float, float],
    destination: Tuple[float, float],
    candidates: List[Dict],
    require_progress: bool = True,
) -> Dict:
    reachable: List[Dict] = []
    current_to_destination = haversine_miles(current, destination)
    for station in candidates:
        distance = haversine_miles(current, (station["lat"], station["lon"]))
        station_to_destination = haversine_miles((station["lat"], station["lon"]), destination)
        is_progressing = station_to_destination < current_to_destination
        if distance <= RANGE_MILES and (is_progressing or not require_progress):
            station_with_distance = dict(station)
            station_with_distance["leg_distance"] = distance
            station_with_distance["remaining_to_destination"] = station_to_destination
            reachable.append(station_with_distance)
    if not reachable:
        return {}
    reachable.sort(
        key=lambda s: (
            s.get("route_offset_miles", float("inf")),
            s["price"],
            s["remaining_to_destination"],
            s["leg_distance"],
        )
    )
    return reachable[0]


def _nearest_station_price(point: Tuple[float, float], stations: List[Dict]) -> float:
    priced_stations = [station for station in stations if station.get("price", 0) > 0]
    if not priced_stations:
        return 0.0
    best_station = min(
        priced_stations,
        key=lambda station: (
            haversine_miles(point, (station["lat"], station["lon"])),
            station["price"],
        ),
    )
    return float(best_station["price"])


def plan_route_with_fuel(start: str, end: str) -> Dict:
    route_data = fetch_route_from_openrouteservice(start, end)
    route_points = route_data["route_coordinates"]
    sampled_route_points = _route_sample_points(route_points)
    total_distance = route_data["total_distance_miles"]
    destination = route_data["end"]

    all_stations = load_fuel_stations()
    if not all_stations:
        raise RoutePlanningError("No fuel stations available.")
    prefiltered_stations = _filter_stations_by_bbox(all_stations, route_points, padding=2.5)
    candidate_stations = prefiltered_stations or all_stations
    stations = _stations_along_route_with_progress(route_points, candidate_stations, 5000)
    if not stations:
        raise RoutePlanningError("No fuel stations found in this corridor.")

    fuel_stops: List[Dict] = []
    total_cost = 0.0
    current_point = route_data["start"]
    start_fuel_price = _nearest_station_price(current_point, all_stations)
    traveled_progress = 0.0
    remaining_route_stations = list(stations)

    while (total_distance - traveled_progress) > RANGE_MILES:
        best_station: Dict = {}
        for offset_limit in ROUTE_STATION_FALLBACK_OFFSETS:
            candidates = [
                station
                for station in remaining_route_stations
                if station.get("route_offset_miles", float("inf")) <= offset_limit
            ]
            best_station = _pick_station_within_range(
                current=current_point,
                destination=destination,
                candidates=candidates,
                require_progress=True,
            )
            if best_station:
                break
        if not best_station:
            partial_distance = min(total_distance, max(traveled_progress, 0.0))
            raise RoutePlanningError(
                "Route not feasible",
                payload={
                    "error": "Route not feasible",
                    "reason": "No fuel station within 500 miles",
                    "partial_distance": round(max(partial_distance, 0.0), 2),
                    "fuel_stops_so_far": fuel_stops,
                },
            )

        leg_distance = best_station["leg_distance"]
        total_cost += (leg_distance / MPG) * best_station["price"]
        destination_progress = max(total_distance - best_station["remaining_to_destination"], 0.0)
        traveled_progress = min(total_distance, max(traveled_progress, destination_progress))

        fuel_stops.append(
            {
                "name": best_station["name"],
                "city": best_station["city"],
                "state": best_station["state"],
                "price": round(best_station["price"], 4),
                "distance_from_start": round(traveled_progress, 2),
                "reason": "cheapest within 500 mile range",
            }
        )

        current_point = (best_station["lat"], best_station["lon"])
        remaining_route_stations = [
            s
            for s in remaining_route_stations
            if s["name"] != best_station["name"] or s["city"] != best_station["city"]
        ]
    remaining_route_distance = total_distance - traveled_progress
    final_leg = haversine_miles(current_point, destination)
    if remaining_route_distance > RANGE_MILES:
        partial_distance = min(total_distance, max(traveled_progress, 0.0))
        raise RoutePlanningError(
            "Route not feasible",
            payload={
                "error": "Route not feasible",
                "reason": "No fuel station within 500 miles",
                "partial_distance": round(max(partial_distance, 0.0), 2),
                "fuel_stops_so_far": fuel_stops,
            },
        )
    final_leg_price = fuel_stops[-1]["price"] if fuel_stops else start_fuel_price
    total_cost += (final_leg / MPG) * final_leg_price

    if total_distance > RANGE_MILES and not fuel_stops:
        raise RoutePlanningError(
            "Route not feasible",
            payload={
                "error": "Route not feasible",
                "reason": "No fuel station within 500 miles",
                "partial_distance": 0.0,
                "fuel_stops_so_far": [],
            },
        )

    fuel_used_gallons = total_distance / MPG
    pricing_strategy = "fuel_stops_based" if fuel_stops else "nearest_station_to_start"
    response: Dict = {
        "status": "success",
        "summary": {
            "distance_miles": round(total_distance, 2),
            "fuel_used_gallons": round(fuel_used_gallons, 2),
            "total_cost_usd": round(total_cost, 2),
        },
        "fuel_stops": fuel_stops,
        "route": {
            "points_sampled": sampled_route_points,
            "total_points": len(route_points),
        },
        "meta": {
            "pricing_strategy": pricing_strategy,
        },
    }
    if not fuel_stops:
        response["meta"]["note"] = "No fuel stop required within 500 miles range."
    return response
