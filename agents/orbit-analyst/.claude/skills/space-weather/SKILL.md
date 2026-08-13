---
name: space-weather
description: "Recent solar flares, coronal mass ejections, and geomagnetic storms from NASA's DONKI database, and whether they matter for a given orbit. Use for questions about solar activity, radiation environment, geomagnetic conditions, or drag events."
---

# Space weather (NASA DONKI)

DONKI is the Space Weather Database of Notifications, Knowledge, Information,
served from `api.nasa.gov`. Authentication is an API key passed as a query
parameter.

## The key

Read it from the environment — it is declared as an agent parameter:

```bash
: "${NASA_API_KEY:?NASA_API_KEY is not set}"
```

It defaults to `DEMO_KEY`, which is rate-limited to roughly 30 requests per
hour per IP. Budget your calls: pull one window and reason over it rather than
issuing one request per question. Never echo the key value.

## Endpoints

All take `startDate` and `endDate` as `YYYY-MM-DD`. Get today's date from
`date -u +%F` rather than assuming it; default to a 7-day window unless the
user names one.

**Solar flares:**

```bash
curl -s "https://api.nasa.gov/DONKI/FLR?startDate=2026-08-06&endDate=2026-08-13&api_key=$NASA_API_KEY" | jq
```

**Coronal mass ejections:**

```bash
curl -s "https://api.nasa.gov/DONKI/CME?startDate=2026-08-06&endDate=2026-08-13&api_key=$NASA_API_KEY" | jq
```

**Geomagnetic storms:**

```bash
curl -s "https://api.nasa.gov/DONKI/GST?startDate=2026-08-06&endDate=2026-08-13&api_key=$NASA_API_KEY" | jq
```

An empty array `[]` is a valid and common answer. "Nothing above background in
the last week" is the correct report, not a failure to find data.

## Reading the results

**Flares (`FLR`)** carry `classType` (`A`, `B`, `C`, `M`, `X` — each letter is
10× the previous), `beginTime`, `peakTime`, `sourceLocation`, and
`activeRegionNum`. Operationally: C-class is background noise, M-class can
cause brief HF radio degradation on the sunlit side, X-class is worth naming
explicitly. The number after the letter is a linear multiplier within the
decade, so X2 is twice X1 and twenty times M1.

**CMEs (`CME`)** carry `startTime` and a `cmeAnalyses` array; inside each
analysis, `speed` (km/s), `type`, `isMostAccurate`, and sometimes
`enlilList[].estimatedShockArrivalTime`. Use the analysis with
`isMostAccurate: true`. A CME only matters to Earth if its trajectory is
Earth-directed — check for an `estimatedShockArrivalTime`; if there is none,
say the event was not forecast to reach Earth rather than reporting its speed
as if it were incoming.

**Geomagnetic storms (`GST`)** carry `allKpIndex[]` with `kpIndex` and
`observedTime`. Kp runs 0–9. Kp ≥ 5 is storm level. Report the peak Kp and
when it was observed.

## Connecting it to an orbit

This is where the analyst actually needs you, so be careful and be honest
about the limits:

- **Drag.** Geomagnetic storms heat and expand the thermosphere, increasing
  drag on objects below roughly 600 km. A Kp 7 storm measurably perturbs an
  ISS-altitude orbit within a day or two; a Kp 3 does not. Above ~800 km the
  effect is negligible over days. You can say a storm is large enough to
  matter for a given altitude — you cannot quantify the resulting decay
  without a drag model, and you should say so.
- **Radiation.** Solar particle events raise dose most at high latitudes and
  in polar-crossing orbits, because the geomagnetic field shields low
  latitudes. An inclination above ~60° means regular polar passes; below ~30°
  the exposure is largely trapped-belt background, not solar.
- **Communications.** M and X flares cause shortwave fadeout on the sunlit
  hemisphere for minutes to hours. This affects HF links, not S/X-band.

State which of these apply and which don't. "Kp peaked at 4 on the 11th, below
storm threshold, no meaningful drag effect at 550 km" is a complete answer.

## When it fails

HTTP 429 means the rate limit is exhausted — say so and report when the window
resets, do not retry in a loop. HTTP 403 means the key is invalid. Report the
status and the endpoint; do not answer the question from memory.
