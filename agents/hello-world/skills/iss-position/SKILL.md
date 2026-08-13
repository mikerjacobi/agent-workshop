---
name: iss-position
description: "Current position of the International Space Station: latitude, longitude, altitude, ground speed, and what it is passing over. Use whenever the user asks where the ISS is, whether it is overhead, or what it is flying over right now."
---

# ISS position

One public endpoint, no authentication, no configuration. `curl` and `jq` are
already on your PATH.

## Get the current position

```bash
curl -s https://api.wheretheiss.at/v1/satellites/25544 | jq
```

`25544` is the ISS's NORAD catalog number. The response:

```json
{
  "name": "iss",
  "id": 25544,
  "latitude": 12.3456,
  "longitude": -45.6789,
  "altitude": 420.1,
  "velocity": 27580.3,
  "visibility": "daylight",
  "footprint": 4506.2,
  "timestamp": 1765432100,
  "solar_lat": -21.2,
  "solar_lon": 142.7,
  "units": "kilometers"
}
```

Field notes, because the names are easy to misread:

- `altitude` — kilometers above the ellipsoid, not above sea level at that point.
- `velocity` — kilometers **per hour**, not per second. Divide by 3600 if the
  user asks how far it moves in a second (~7.66 km).
- `footprint` — diameter in km of the circle on the ground with line of sight
  to the station. This is the honest answer to "can I see it from X" only in
  combination with `visibility`.
- `visibility` — `daylight`, `eclipsed`, or `visible`. The station is only
  naked-eye visible from the ground when it is sunlit and the observer is in
  darkness; `visible` means that condition holds at the sub-satellite point.
- `timestamp` — Unix seconds. Always report the position as of a time.

## Name the place, don't just read coordinates

Raw latitude/longitude is not an answer. Resolve it yourself to the nearest
recognizable feature — ocean, sea, country, or major city — from what you
already know about world geography. Most of the time the honest answer is
an ocean, and saying "over the South Pacific, nearest land ~2,000 km away"
is more useful than pretending to a precision you don't have.

## What this skill does not do

No pass predictions, no orbital elements, no other satellites, no history.
If the user asks for those, say so — do not derive them from a single
position sample.

## When it fails

If `curl` returns non-zero or the JSON has no `latitude`, report the exact
command, the exit code, and the raw body. Do not answer the question from
memory; a remembered ISS position is wrong by thousands of kilometers.
