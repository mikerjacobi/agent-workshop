---
name: geocode
description: "Turn a place name into latitude, longitude, timezone, and country/region, using the Open-Meteo geocoding API. Use whenever the user names a place instead of coordinates — which is nearly always — and before any search that needs a point."
---

# Geocoding a place name

Public, no authentication, no key. `curl` and `jq` are on your PATH.

## The call

```bash
curl -s "https://geocoding-api.open-meteo.com/v1/search?name=Anchorage&count=5&format=json" | jq
```

URL-encode the name if it has spaces or accents (`San%20Francisco`). Ask for
`count=5`, not `count=1` — you need to see whether the name was ambiguous
before you commit to a point.

## The response

```json
{"results": [
  {
    "id": 5879400,
    "name": "Anchorage",
    "latitude": 61.21806,
    "longitude": -149.90028,
    "elevation": 31.0,
    "feature_code": "PPLA2",
    "country_code": "US",
    "timezone": "America/Anchorage",
    "population": 289600,
    "country": "United States",
    "admin1": "Alaska",
    "admin2": "Anchorage Municipality"
  }
]}
```

The fields you actually use:

- `latitude` / `longitude` — decimal degrees, WGS84. Longitude is negative
  west of Greenwich.
- `timezone` — IANA name. Carry this forward; every time you show the user
  should be rendered in it.
- `admin1` / `country` — the region and country. Say these back to the user so
  they can catch a wrong match.
- `population` — the tiebreaker, see below.

**No `results` key at all** means no match, not an empty list. Check for the
key's absence, not for an empty array.

## Ambiguity is the normal case

`name=Anchorage` returns Anchorage, Alaska (population 289,600) **and**
Anchorage, Kentucky (population 2,420). `name=Springfield` returns a dozen.
Getting this wrong silently produces a confident answer about the wrong
hemisphere.

The rule:

1. If the user gave a qualifier — "Anchorage, Alaska", "Springfield, Illinois"
   — filter the results on `admin1` or `country` and use the match.
2. If exactly one result is dramatically larger than the rest (an order of
   magnitude in `population`), take it, and **say which one you took**:
   "Anchorage, Alaska (61.22°N, 149.90°W)".
3. Otherwise, show the top candidates with their region and population, and
   ask which one they meant. Do not guess between two comparable cities.

Never silently take `results[0]`.

## What this skill does not do

It resolves populated places. It does not resolve street addresses,
landmarks, bodies of water, or coordinates in reverse. If the user gives you
something it can't resolve, say so and ask for a nearby town rather than
approximating a location yourself.

## When it fails

Report the URL and the HTTP status. A `200` with no `results` key means the
name didn't match anything — that is a real answer, and the right response is
to ask for a different spelling or a nearby larger town, not to invent
coordinates.
