# Route Fuel Optimizer API

## Goal

Design an efficient backend API that computes routes and minimizes fuel cost under real-world constraints.

Backend API for computing a drive route, estimating fuel usage/cost, and planning cost-aware fuel stops between US locations.

## Stack

- Python
- Django
- Django REST Framework
- OpenRouteService (geocoding + routing)

## Core Rules

- Vehicle max range per leg: `500` miles
- Fuel efficiency: `10` miles/gallon
- Fuel consumption is calculated as: `distance_miles / 10`
- Greedy stop selection: iteratively choose the cheapest reachable station that advances toward the destination

## Design Decisions

- Used a greedy algorithm to balance simplicity, performance, and real-time decision making.
- Limited external API calls to reduce latency and stay within free-tier constraints.

## Algorithm Note

The greedy approach selects the cheapest reachable station at each step.
While efficient, it does not guarantee a globally optimal solution across the entire route.

## Endpoint

### `POST /route/`

Method notes:
- `POST` is required for `/route/`
- `GET /route/` returns `405 Method Not Allowed`

Request body:

```json
{
  "start": "Dallas, TX",
  "end": "Austin, TX"
}
```

### Success Response (`200`)

```json
{
  "status": "success",
  "summary": {
    "distance_miles": 200.45,
    "fuel_used_gallons": 20.05,
    "total_cost_usd": 53.83
  },
  "fuel_stops": [],
  "route": {
    "points_sampled": [[32.736137, -96.784448], [32.73525, -96.786069]],
    "total_points": 1710
  },
  "meta": {
    "pricing_strategy": "nearest_station_to_start",
    "note": "No fuel stop required within 500 miles range."
  }
}
```

### Example (Long Route with Stops)

```json
{
  "status": "success",
  "summary": {
    "distance_miles": 1062.44,
    "fuel_used_gallons": 106.24,
    "total_cost_usd": 336.89
  },
  "fuel_stops": [
    {
      "name": "CIRCLE K #2612042",
      "state": "TX",
      "price": 2.919,
      "distance_from_start": 218.97,
      "reason": "cheapest within 500 mile range"
    }
  ],
  "meta": {
    "pricing_strategy": "fuel_stops_based"
  }
}
```

### Infeasible Route Response (`400`)

Returned when no forward fuel station is reachable within 500 miles:

```json
{
  "error": "Route not feasible",
  "reason": "No fuel station within 500 miles",
  "partial_distance": 218.97,
  "fuel_stops_so_far": [
    {
      "name": "CIRCLE K #2612042",
      "state": "TX",
      "price": 2.919,
      "distance_from_start": 218.97,
      "reason": "cheapest within 500 mile range"
    }
  ]
}
```

### Validation Error Response (`400`)

```json
{
  "error": "Invalid request",
  "message": "Both 'start' and 'end' fields are required."
}
```

## Pricing Strategy in Responses

- `nearest_station_to_start`: used when trip can be completed without a fuel stop (`distance <= 500` miles)
- `fuel_stops_based`: used when one or more stops are required

## External API Call Budget

Per request:
- Geocode start: 1 call
- Geocode end: 1 call
- Directions: 1 call

Total external calls: `3` (max), with only `1` routing/directions call.

## Performance Notes

- Fuel station CSV is loaded once and cached in memory.
- Stations are prefiltered by a route bounding box before route-proximity scoring.
- Route is returned as sampled points (`points_sampled`) plus `total_points` to keep payloads efficient.

## Data Notes

- Route coordinates are in `[latitude, longitude]` format.

## Run Locally

1. Create virtual environment and install dependencies:
   - `python -m venv .venv`
   - `.venv\Scripts\activate`
   - `pip install -r requirements.txt`
2. Configure OpenRouteService key:
   - Environment variable: `OPENROUTESERVICE_API_KEY=your_key`
   - Or set in `config/settings.py`
3. Start app:
   - `python manage.py migrate`
   - `python manage.py runserver`
4. Test endpoint:
   - `POST http://127.0.0.1:8000/route/`

PowerShell quick test:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/route/" `
  -ContentType "application/json" `
  -Body '{"start":"Dallas, TX","end":"Austin, TX"}'
```

Python quick test:

```python
import requests

payload = {"start": "Dallas, TX", "end": "Austin, TX"}
response = requests.post("http://127.0.0.1:8000/route/", json=payload, timeout=120)
print(response.status_code)
print(response.json())
```

## Assumptions and Limits

- Fuel prices come from `data/fuel_stations.csv`.
- If no stop is needed, cost is estimated using the nearest station price to the start point.
- Route feasibility depends on station coverage in the dataset and the 500-mile max-leg constraint.
- `points_sampled` is optimized for API payload size; it is not intended for turn-by-turn navigation.

## Scalability Considerations

The service is structured to allow easy extension with larger datasets, caching layers (e.g., Redis), and more advanced optimization strategies.

## Error Handling Philosophy

The API prioritizes returning explicit, structured errors over silent failures or incorrect results.

## Future Improvements

- Replace greedy strategy with global optimization (e.g., dynamic programming or shortest path with cost weighting)
- Integrate real-time fuel price APIs instead of static CSV data
- Add Redis caching for route and geocode responses
- Support multiple vehicle profiles (different MPG and tank capacities)

## Project Layout

- `routing/views.py` endpoint + error mapping
- `routing/services.py` routing, station filtering, greedy fuel planning
- `routing/serializers.py` request validation
- `routing/utils.py` distance utilities
- `routing/urls.py` URL routes
- `data/fuel_stations.csv` station/pricing source data
