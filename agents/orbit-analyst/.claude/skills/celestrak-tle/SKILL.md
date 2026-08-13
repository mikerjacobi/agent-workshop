---
name: celestrak-tle
description: "Two-line element sets (TLEs) for any object in the public satellite catalog, by name or NORAD ID, from CelesTrak. Also covers what you may and may not derive from a single element set: inclination, mean motion, period, approximate altitude, epoch age. Use for questions about a satellite's orbit, altitude, period, or how current the catalog data is."
---

# CelesTrak element sets

Public, no authentication. `curl` and `jq` are on your PATH. CelesTrak asks
that clients not poll faster than the data updates — element sets refresh a
few times a day, so one fetch per question is right and a loop is not.

## Fetch by NORAD catalog number

```bash
curl -s "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=json" | jq
```

## Fetch by name

```bash
curl -s "https://celestrak.org/NORAD/elements/gp.php?NAME=STARLINK-1007&FORMAT=json" | jq
```

`NAME=` is a substring match and frequently returns many objects. If you get
more than one, show the user the candidates with their NORAD IDs and ask which
they meant. Do not silently pick the first.

If the response body is the literal string `No GP data found`, the object is
not in the public catalog. Say that; do not fall back to memory.

## Reading the JSON response

```json
[{
  "OBJECT_NAME": "ISS (ZARYA)",
  "NORAD_CAT_ID": 25544,
  "EPOCH": "2026-08-12T14:22:31.123456",
  "MEAN_MOTION": 15.50123456,
  "ECCENTRICITY": 0.0004123,
  "INCLINATION": 51.6412,
  "RA_OF_ASC_NODE": 210.4471,
  "ARG_OF_PERICENTER": 88.1234,
  "MEAN_ANOMALY": 271.9876,
  "BSTAR": 0.00012345
}]
```

- `EPOCH` is UTC and is the **only** time this data describes. Always report
  it, and always report how old it is. Compute the age with
  `date -u +%Y-%m-%dT%H:%M:%S` and subtract; do not assume today's date.
- `MEAN_MOTION` is revolutions per day.
- `INCLINATION`, `RA_OF_ASC_NODE`, `ARG_OF_PERICENTER`, `MEAN_ANOMALY` are degrees.

## Derivations you may make

**Orbital period**, minutes: `1440 / MEAN_MOTION`. Show the division.

**Semi-major axis**, km, from mean motion `n` in rev/day:

```
n_rad = MEAN_MOTION * 2π / 86400          # rad/s
a     = (398600.4418 / n_rad²)^(1/3)      # km, μ_Earth = 398600.4418 km³/s²
```

**Approximate altitude**, km: `a - 6378.137` (equatorial Earth radius). This is
a mean altitude for a near-circular orbit. For `ECCENTRICITY` above about
0.01, report perigee and apogee separately instead:

```
perigee = a * (1 - ECCENTRICITY) - 6378.137
apogee  = a * (1 + ECCENTRICITY) - 6378.137
```

Do the arithmetic with `python3 -c` and show the expression you evaluated.

**Latitude coverage**: the ground track reaches ±`INCLINATION` degrees latitude
(or ±(180 − `INCLINATION`) for retrograde orbits, where inclination > 90°). So
a site poleward of that latitude never sees the satellite overhead.

## Derivations you may NOT make

A single element set does not support:

- **Where the satellite is right now.** That needs SGP4 propagation from the
  epoch. State that, and offer the epoch elements instead.
- **Pass times over a ground site.** Same reason, plus a site geometry.
- **Conjunctions or collision probability.** Needs covariance data that is not
  in a public TLE.
- **Re-entry date.** `BSTAR` hints at drag but a decay estimate needs a
  propagator and an atmosphere model.

Say what is missing and why. An analyst asking these already knows the answer
is no; they are checking whether you know it too.

## When it fails

Report the exact URL, the HTTP status, and the first line of the body.
CelesTrak returns HTML error pages on rate limiting, so a JSON parse failure
usually means you polled too fast, not that the object is missing.
