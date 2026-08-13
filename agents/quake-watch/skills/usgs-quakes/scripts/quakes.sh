#!/usr/bin/env bash
# Query the USGS earthquake catalog around a point and flatten the GeoJSON
# into one readable line per event.
#
#   ./quakes.sh --lat 61.218 --lon -149.900 --radius 300 --min-mag 2.5 --days 7
#   ./quakes.sh --lat 35.7 --lon 139.7 --days 30 --raw > /tmp/tokyo.json
#
# Defaults come from the agent parameters QUAKE_DEFAULT_RADIUS_KM and
# QUAKE_MIN_MAGNITUDE. Everything is public — no key, no auth.
set -euo pipefail

LAT="" LON=""
RADIUS="${QUAKE_DEFAULT_RADIUS_KM:-300}"
MIN_MAG="${QUAKE_MIN_MAGNITUDE:-2.5}"
DAYS=7
LIMIT=50
RAW=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lat)      LAT="$2"; shift 2 ;;
    --lon)      LON="$2"; shift 2 ;;
    --radius)   RADIUS="$2"; shift 2 ;;
    --min-mag)  MIN_MAG="$2"; shift 2 ;;
    --days)     DAYS="$2"; shift 2 ;;
    --limit)    LIMIT="$2"; shift 2 ;;
    --raw)      RAW=1; shift ;;
    -h|--help)  sed -n '2,10p' "$0"; exit 0 ;;
    *)          echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$LAT" || -z "$LON" ]]; then
  echo "--lat and --lon are required (run the geocode skill first)" >&2
  exit 2
fi

# BSD and GNU date disagree on relative-date syntax; try both.
START=$(date -u -v-"${DAYS}"d +%F 2>/dev/null || date -u -d "${DAYS} days ago" +%F)
END=$(date -u +%F)

URL="https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
URL+="&latitude=${LAT}&longitude=${LON}&maxradiuskm=${RADIUS}"
URL+="&minmagnitude=${MIN_MAG}&starttime=${START}&endtime=${END}"
URL+="&orderby=time&limit=${LIMIT}"

response=$(curl -s -w '\n%{http_code}' "$URL")
status=$(tail -n1 <<<"$response")
body=$(sed '$d' <<<"$response")

if [[ "$status" != "200" ]]; then
  # USGS returns a plain-text body naming the bad parameter.
  echo "USGS returned HTTP $status" >&2
  echo "$body" | head -5 >&2
  echo "url: $URL" >&2
  exit 1
fi

if [[ "$RAW" == "1" ]]; then
  echo "$body"
  exit 0
fi

echo "search: ${RADIUS} km around ${LAT},${LON} | M${MIN_MAG}+ | ${START} to ${END}"

count=$(jq '.features | length' <<<"$body")
if [[ "$count" == "0" ]]; then
  echo "no events matched"
  exit 0
fi

# time is epoch MILLISECONDS; depth is coordinates[2] (the array is
# [lon, lat, depth]). Both are documented traps — see SKILL.md.
jq -r '.features[] | [
    "M" + (.properties.mag | tostring),
    "depth " + (.geometry.coordinates[2] | tostring) + " km",
    (.properties.time / 1000 | strftime("%Y-%m-%dT%H:%M:%SZ")),
    .properties.place,
    "felt=" + (.properties.felt // 0 | tostring),
    "mmi=" + (.properties.mmi // 0 | tostring),
    "type=" + .properties.type,
    "status=" + .properties.status
  ] | @tsv' <<<"$body" | column -t -s $'\t'

echo "${count} event(s)"
