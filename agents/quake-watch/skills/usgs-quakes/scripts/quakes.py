"""Query the USGS earthquake catalog around a point and print one line per event.

    python3 .claude/skills/usgs-quakes/scripts/quakes.py --latitude 61.218 --longitude -149.900
    python3 .claude/skills/usgs-quakes/scripts/quakes.py --latitude 35.7 --longitude 139.7 --days 30 --raw

Defaults for radius and magnitude come from the agent parameters
QUAKE_DEFAULT_RADIUS_KM and QUAKE_MIN_MAGNITUDE. Everything is public — no key,
no auth.

The response models below are the reason this is Python rather than jq: the
feed has three fields that are easy to misread, and a typed model makes each
one wrong exactly once, here, instead of every time an agent reads the JSON.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, CliApp, SettingsConfigDict

USGS_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
EARTH_REQUEST_TIMEOUT_SEC = 30.0


class QuakeError(Exception):
    """Base for every failure this script raises. Handled once, in ``main``."""


class UpstreamRejected(QuakeError):
    """USGS returned a non-200. Its body names the offending parameter."""


class UpstreamUnreachable(QuakeError):
    """The request never got a response."""


class ResponseUnparseable(QuakeError):
    """USGS answered with something that is not the GeoJSON we expect."""


class QuakeProperties(BaseModel):
    """The ``properties`` object on one feature.

    ``extra="ignore"``: the feed carries a dozen fields about internal
    contributor networks that no consumer here needs, and they change."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    mag: float | None = Field(default=None, description="Magnitude on the scale named by mag_type")
    mag_type: str | None = Field(default=None, alias="magType", description="ml, mb, mww … — not interconvertible")
    place: str | None = Field(default=None, description="Human description, already relative to a town")
    time_ms: int = Field(alias="time", description="Origin time in epoch MILLISECONDS, not seconds")
    felt: int | None = Field(default=None, description="Did You Feel It? report count; None means nobody reported")
    mmi: float | None = Field(default=None, description="Estimated Modified Mercalli shaking intensity")
    cdi: float | None = Field(default=None, description="Community-reported intensity")
    alert: str | None = Field(default=None, description="PAGER level when one was issued")
    tsunami: int = Field(default=0, description="Region marker, NOT a warning that a tsunami occurred")
    sig: int | None = Field(default=None, description="USGS significance score, 0-1000")
    status: str = Field(default="automatic", description="'automatic' magnitudes can still change")
    type: str = Field(default="earthquake", description="Also 'quarry blast', 'explosion', 'ice quake'")

    @property
    def origin_time(self) -> datetime:
        """The trap this model exists for: epoch milliseconds, not seconds.
        Treating the raw value as seconds lands around the year 58,000, or
        raises outright."""
        return datetime.fromtimestamp(self.time_ms / 1000, tz=UTC)


class QuakeGeometry(BaseModel):
    """GeoJSON point. The coordinate order is [longitude, latitude, depth_km] —
    longitude first, which is the reverse of how everyone says it aloud, and
    depth is here rather than in properties where you would look for it."""

    model_config = ConfigDict(extra="ignore")

    coordinates: list[float] = Field(min_length=3, max_length=3)

    @property
    def longitude(self) -> float:
        return self.coordinates[0]

    @property
    def latitude(self) -> float:
        return self.coordinates[1]

    @property
    def depth_km(self) -> float:
        return self.coordinates[2]


class QuakeFeature(BaseModel):
    """One catalogued event."""

    model_config = ConfigDict(extra="ignore")

    id: str
    properties: QuakeProperties
    geometry: QuakeGeometry

    def render(self) -> str:
        magnitude = f"M{self.properties.mag:.1f}" if self.properties.mag is not None else "M?"
        stamp = self.properties.origin_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        return (
            f"{magnitude:<6} depth {self.geometry.depth_km:>6.1f} km  {stamp}  "
            f"{(self.properties.place or 'unknown location'):<48} "
            f"felt={self.properties.felt or 0:<5} mmi={self.properties.mmi or 0:<6.3g} "
            f"type={self.properties.type} status={self.properties.status}"
        )


class QuakeResponse(BaseModel):
    """The FeatureCollection USGS returns."""

    model_config = ConfigDict(extra="ignore")

    features: list[QuakeFeature] = Field(default_factory=list)


class QuakeSearch(BaseModel):
    """The search that was run. Printed with the results because 'no events'
    is only a useful answer when the reader can see what was looked for."""

    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float
    radius_km: float
    min_magnitude: float
    start_date: str
    end_date: str
    limit: int

    def url(self) -> str:
        query = urllib.parse.urlencode(
            {
                "format": "geojson",
                "latitude": self.latitude,
                "longitude": self.longitude,
                "maxradiuskm": self.radius_km,
                "minmagnitude": self.min_magnitude,
                "starttime": self.start_date,
                "endtime": self.end_date,
                "orderby": "time",
                "limit": self.limit,
            }
        )
        return f"{USGS_QUERY_URL}?{query}"

    def render(self) -> str:
        return (
            f"search: {self.radius_km:g} km around {self.latitude},{self.longitude} | "
            f"M{self.min_magnitude:g}+ | {self.start_date} to {self.end_date}"
        )


class QuakeReport(BaseModel):
    """What was searched and what came back."""

    model_config = ConfigDict(extra="forbid")

    search: QuakeSearch
    response: QuakeResponse

    def render(self) -> str:
        lines = [self.search.render()]
        if not self.response.features:
            lines.append("no events matched")
            return "\n".join(lines)
        lines.extend(feature.render() for feature in self.response.features)
        lines.append(f"{len(self.response.features)} event(s)")
        return "\n".join(lines)


def fetch(search: QuakeSearch) -> str:
    """GET the catalog. USGS answers a bad parameter with HTTP 400 and a
    plain-text body that names it, so the body is worth surfacing verbatim."""
    url = search.url()
    try:
        # noqa: S310 — the host is a fixed https literal, not caller-supplied.
        with urllib.request.urlopen(url, timeout=EARTH_REQUEST_TIMEOUT_SEC) as response:
            payload: bytes = response.read()
        return payload.decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace").strip().splitlines()
        raise UpstreamRejected(
            f"USGS returned HTTP {exc.code}\n  {detail[0] if detail else '(no body)'}\n  url: {url}"
        ) from exc
    except urllib.error.URLError as exc:
        raise UpstreamUnreachable(f"could not reach USGS: {exc.reason}\n  url: {url}") from exc


def search_quakes(search: QuakeSearch) -> QuakeReport:
    payload = fetch(search)
    try:
        return QuakeReport(search=search, response=QuakeResponse.model_validate_json(payload))
    except ValueError as exc:
        raise ResponseUnparseable(f"USGS returned something unexpected: {exc}\n  url: {search.url()}") from exc


class Quakes(BaseSettings):
    """Earthquakes near a point, from the live USGS catalog.

    Radius and magnitude defaults come from the agent parameters; everything
    else is a flag."""

    model_config = SettingsConfigDict(
        extra="forbid", cli_parse_args=True, cli_implicit_flags=True, populate_by_name=True
    )

    latitude: float = Field(description="Decimal degrees; run the geocode skill first")
    longitude: float = Field(description="Decimal degrees, negative west of Greenwich")
    # AliasChoices keeps the flag named after the field while still reading the
    # agent parameter from the environment. A bare alias= would rename the flag.
    radius_km: float = Field(
        default=300.0,
        validation_alias=AliasChoices("radius_km", "QUAKE_DEFAULT_RADIUS_KM"),
        gt=0,
        description="Search radius; defaults to the QUAKE_DEFAULT_RADIUS_KM agent parameter",
    )
    min_magnitude: float = Field(
        default=2.5,
        validation_alias=AliasChoices("min_magnitude", "QUAKE_MIN_MAGNITUDE"),
        description="Magnitude floor; defaults to the QUAKE_MIN_MAGNITUDE agent parameter",
    )
    days: int = Field(default=7, gt=0, description="Window ending today, in days")
    limit: int = Field(default=50, gt=0, le=20000, description="Max events; USGS errors above 20000")
    raw: bool = Field(default=False, description="Print the unmodified GeoJSON instead of a table")

    def to_search(self) -> QuakeSearch:
        end = datetime.now(UTC).date()
        return QuakeSearch(
            latitude=self.latitude,
            longitude=self.longitude,
            radius_km=self.radius_km,
            min_magnitude=self.min_magnitude,
            start_date=(end - timedelta(days=self.days)).isoformat(),
            end_date=end.isoformat(),
            limit=self.limit,
        )

    def cli_cmd(self) -> None:
        search = self.to_search()
        print(fetch(search) if self.raw else search_quakes(search).render())


def describe_validation_error(error: ValidationError) -> str:
    """Render a pydantic failure as the flag the user actually typed."""
    lines = []
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"])
        flag = f"--{field.replace('_', '-')}" if field else ""
        lines.append(f"{flag}: {item['msg']}".lstrip(": "))
    return "\n".join(lines)


def main() -> None:
    try:
        CliApp.run(Quakes)
    except QuakeError as exc:
        sys.stderr.write(f"\n{exc}\n")
        raise SystemExit(1) from exc
    except ValidationError as exc:
        sys.stderr.write(f"\nError: {describe_validation_error(exc)}\n")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
