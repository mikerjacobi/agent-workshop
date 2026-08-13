# USGS FDSN event query parameters

Base URL: `https://earthquake.usgs.gov/fdsnws/event/1/query`

Load this when `scripts/quakes.sh` doesn't expose the parameter you need. For
ordinary "what happened near X" questions the script is enough.

## Always set

| Parameter | Value | Note |
|-----------|-------|------|
| `format` | `geojson` | The other formats (`csv`, `quakeml`, `text`) parse worse. Use geojson. |

## Location

Two mutually exclusive ways to bound a search. Mixing them is an HTTP 400.

**Radial** — a point and a distance. This is the one you want after geocoding.

| Parameter | Value |
|-----------|-------|
| `latitude` | decimal degrees, −90 to 90 |
| `longitude` | decimal degrees, −180 to 180 |
| `maxradiuskm` | kilometers from the point |
| `minradiuskm` | kilometers; excludes a hole around the point |

**Rectangular** — a bounding box.

| Parameter | Value |
|-----------|-------|
| `minlatitude` / `maxlatitude` | decimal degrees |
| `minlongitude` / `maxlongitude` | decimal degrees; may exceed ±180 to cross the antimeridian |

## Time

| Parameter | Value |
|-----------|-------|
| `starttime` / `endtime` | `YYYY-MM-DD` or full ISO-8601 (`2026-08-06T00:00:00`). Always UTC. |
| `updatedafter` | Only events whose record changed after this time — for polling without re-reading everything. |

Omitting both defaults to the last 30 days. Get today from `date -u +%F`
rather than assuming it.

## Magnitude and depth

| Parameter | Value |
|-----------|-------|
| `minmagnitude` / `maxmagnitude` | Applied against `mag` regardless of `magType`. |
| `mindepth` / `maxdepth` | Kilometers. Negative values are above sea level and are legitimate. |

## Result shaping

| Parameter | Value |
|-----------|-------|
| `orderby` | `time` (newest first, default), `time-asc`, `magnitude` (largest first), `magnitude-asc` |
| `limit` | Max 20000. The service errors rather than truncating silently if you exceed it. |
| `offset` | 1-based, not 0-based. |
| `eventtype` | `earthquake`, `quarry blast`, `explosion`, `ice quake`, … Set `eventtype=earthquake` when a non-seismic entry would mislead. |
| `minsig` | Minimum significance (0–1000). A quick way to ask for "notable only". |
| `reviewstatus` | `automatic` or `reviewed`. Reviewed magnitudes are final; automatic ones can move. |

## Counting without fetching

Swap `query` for `count` to get just a number. Cheap, and the right first call
when you suspect the result set is large.

```bash
curl -s "https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson\
&latitude=61.218&longitude=-149.900&maxradiuskm=300&starttime=2026-01-01"
```

## A single event by id

```bash
curl -s "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&eventid=aka2026powmkf"
```

The `id` on each feature, and the `detail` URL in its properties, both point
here. The detail response carries additional products (ShakeMap, moment
tensor) that the summary feed omits.

## Errors

The service returns **HTTP 400 with a plain-text body naming the offending
parameter**, not JSON. Read the body — it is specific and it tells you exactly
what to fix. Common causes:

- Radial and rectangular parameters in the same request.
- `starttime` after `endtime`.
- `limit` above 20000.

HTTP 204 means the query was valid and matched nothing. That is an answer, not
an error.

## Rate limits

There is no published key or quota, but this is a public good funded by a
government agency. One query per question. If you need a wide window and a
tight one, fetch the wide one and filter locally.
