---
name: usgs-quakes
description: "Earthquakes near a point in a time window, from the live USGS catalog: magnitude, depth, distance and direction from a place, how widely it was felt, and shaking intensity. Use for any question about recent seismic activity, whether something was an earthquake, or how big a quake was. Does not forecast."
---

# USGS earthquake catalog

The USGS FDSN event service. Public, no authentication, no key. Returns
GeoJSON.

You need a point first — run `Skill(skill="geocode")` on the place name before
you come here.

## The easy path

This skill ships a script that runs the query and flattens the GeoJSON into
one line per event, with the misread-prone fields already decoded. Run it from
your workspace root, where skills live under `.claude/skills/`:

```bash
python3 .claude/skills/usgs-quakes/scripts/quakes.py \
  --latitude 61.218 --longitude -149.900 --radius_km 300 --min_magnitude 2.5 --days 7
```

```
search: 300 km around 61.218,-149.9 | M2.5+ | 2026-08-06 to 2026-08-13
M3.9   depth  147.2 km  2026-08-11T22:26:55Z  59 km NE of Pedro Bay, Alaska    felt=3     mmi=1.65  …
M5.6   depth   10.0 km  2026-08-08T04:50:34Z  57 km WNW of Skwentna, Alaska    felt=1137  mmi=5.88  …
2 event(s)
```

`--radius_km` and `--min_magnitude` default to `$QUAKE_DEFAULT_RADIUS_KM` and
`$QUAKE_MIN_MAGNITUDE`; a flag beats the environment. `--raw` prints the
unmodified GeoJSON — redirect that to a file in your working directory when a
follow-up question is likely. `--help` lists everything.

The first line is the search itself. Keep it: an empty result is only a useful
answer when the reader can see what was looked for.

If the script is missing, don't hunt for it — use the direct call below. It is
a convenience, not a dependency.

```
M5.6  depth  10.0 km  2026-08-06T05:30:34Z  57 km WNW of Skwentna, Alaska        felt=1137  mmi=5.9
M3.9  depth  85.0 km  2026-08-09T23:06:55Z  59 km NE of Pedro Bay, Alaska        felt=3     mmi=1.7
```

Pass `--raw` to get the unmodified GeoJSON instead. Write that to a file in
your working directory when a follow-up question is likely.

The defaults come from `$QUAKE_DEFAULT_RADIUS_KM` and `$QUAKE_MIN_MAGNITUDE`.

## The direct call

Use this when you need a parameter the script doesn't expose. The full
parameter list is in [references/query-parameters.md](references/query-parameters.md).

```bash
curl -s "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson\
&latitude=61.218&longitude=-149.900&maxradiuskm=300\
&minmagnitude=2.5&starttime=2026-08-06&endtime=2026-08-13\
&orderby=magnitude&limit=20" | jq
```

Get today's date from `date -u +%F` rather than assuming it.

## Reading the response

```json
{"features": [{
  "properties": {
    "mag": 5.6,
    "place": "57 km WNW of Skwentna, Alaska",
    "time": 1786164634985,
    "updated": 1786597242869,
    "felt": 1137,
    "cdi": 5.4,
    "mmi": 5.879,
    "alert": null,
    "tsunami": 0,
    "sig": 1022,
    "magType": "ml",
    "status": "reviewed",
    "type": "earthquake"
  },
  "geometry": { "type": "Point", "coordinates": [-152.314, 62.269, 10] },
  "id": "aka2026powmkf"
}]}
```

Three fields here are misread constantly. Get them right:

1. **`time` is epoch MILLISECONDS, not seconds.** Divide by 1000 before
   converting, or you will report the year 1970.
   ```bash
   date -u -r $(( 1786164634985 / 1000 )) +%Y-%m-%dT%H:%M:%SZ    # macOS/BSD
   date -u -d @$(( 1786164634985 / 1000 )) +%Y-%m-%dT%H:%M:%SZ   # GNU
   ```
2. **Depth is not a named field.** It is the *third* element of
   `geometry.coordinates`, in kilometers. And the array is GeoJSON order:
   `[longitude, latitude, depth]` — longitude first, which is the reverse of
   how everyone says it out loud.
   ```bash
   jq -r '.features[] | "\(.properties.mag) \(.geometry.coordinates[2]) km"'
   ```
3. **`mag` values are not all the same scale.** `magType` says which:
   `ml` (local), `mb` (body wave), `mww` (moment tensor), and others. They are
   broadly comparable and you should not convert between them, but do not
   present a difference of 0.1 between two events of different `magType` as
   meaningful.

The rest, in order of usefulness to a person:

- **`place`** — a human description already relative to a town. Use it; don't
  re-derive the distance yourself.
- **`felt`** — number of people who filed a "Did You Feel It?" report. This is
  the field that makes a magnitude mean something. `null` means nobody
  reported, which for a remote or deep event is normal and not a data problem.
- **`mmi`** — estimated Modified Mercalli intensity, the shaking actually
  experienced. Roughly: under 2 not felt, 3–4 light, 5 moderate (hanging
  objects swing), 6 strong (people run outdoors), 7+ damaging. This is the
  honest way to answer "was it a big one".
- **`sig`** — USGS's own 0–1000 significance score, combining magnitude, felt
  reports, and impact. Good for ranking.
- **`tsunami`** — a `1` means the event was in a region where tsunami
  evaluation applies. It does **not** mean a tsunami occurred or was warned.
  Never report it as a warning.
- **`status`** — `automatic` means not yet reviewed by a human and the
  magnitude may still change. Say so when reporting a recent event.
- **`alert`** — PAGER alert level (`green`/`yellow`/`orange`/`red`) when one
  was issued, usually `null`.
- **`type`** — not every entry is an earthquake. `quarry blast`, `explosion`,
  and `ice quake` appear. Filter or label them; reporting a quarry blast as
  seismic activity is wrong.

## What you may conclude

- How much activity there was near a place, over a window, above a magnitude.
- How strongly a specific event was felt, from `mmi` and `felt`.
- Whether an event is unusual **for that region**, from the count of
  comparable events in the surrounding weeks — computed from the data you
  pulled, with the window stated.

## What you may NOT conclude

- **Anything about future earthquakes.** No probabilities, no "elevated
  risk", no "a larger one may follow", no reading of a sequence as a trend.
  No method predicts earthquakes. Aftershock *statistics* exist, but they are
  a specialist product and not something to derive from this feed.
- **Damage, casualties, or structural risk.** `mmi` is estimated shaking, not
  consequence.
- **Tsunami status.** The `tsunami` flag is a region marker, not a warning.
  Point at official channels.

When asked for any of these, say plainly that you can't, say why in one
sentence, and offer what you do have.

## When it fails

Report the URL and the HTTP status. USGS returns **HTTP 400 with a plain-text
body** for a bad parameter — read that body, it names the parameter. An empty
`features` array is a valid and common answer: "nothing above M2.5 within
300 km in the last 7 days" is a complete response, provided you state the
search you ran.
