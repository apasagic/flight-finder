#!/usr/bin/env python3
"""Flexible Google Flights search for round trips and separate one-way tickets.

This replacement does not use the retired/unsubscribed RapidAPI endpoint from the
original project. It uses the open-source ``fast-flights`` Google Flights client,
adds an EU consent-cookie workaround, validates constraints locally, caches each
query, and writes comparison CSV/JSON files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    from fast_flights import (
        FlightQuery,
        FlightsNotFound,
        Passengers,
        create_query,
        get_flights,
    )
    from fast_flights.fetcher import URL
    from fast_flights.integrations.base import FetchIntegration
    from primp import Client
except ModuleNotFoundError as exc:  # pragma: no cover - user-facing startup path
    raise SystemExit(
        "Missing dependency. Run: py -3 -m pip install -r requirements.txt"
    ) from exc


PROVIDER_VERSION = "google-fast-flights-v3-consent-1"
CONSENT_COOKIES = {
    "CONSENT": "YES+cb.20210720-07-p0.en+FX+410",
    "SOCS": "CAI",
}


@dataclass(frozen=True)
class SearchSpec:
    trip: str
    origin: str
    destination: str
    departure_date: str
    return_date: str | None = None

    @property
    def stay_days(self) -> int | None:
        if self.return_date is None:
            return None
        outbound = date.fromisoformat(self.departure_date)
        inbound = date.fromisoformat(self.return_date)
        return (inbound - outbound).days


class ConsentFetcher(FetchIntegration):
    """Thread-local Google client that bypasses the EU consent interstitial."""

    def __init__(self, timeout_seconds: int = 60):
        self._local = threading.local()
        self._timeout_seconds = timeout_seconds

    def _client(self) -> Client:
        client = getattr(self._local, "client", None)
        if client is None:
            client = Client(
                impersonate="chrome_145",
                impersonate_os="windows",
                referer=True,
                cookie_store=True,
                cookies=CONSENT_COOKIES,
                timeout=self._timeout_seconds,
            )
            self._local.client = client
        return client

    def fetch_html(self, query, /) -> str:
        params = query.params() if hasattr(query, "params") else {"q": query}
        html = self._client().get(URL, params=params).text
        if "consent.google.com" in html[:5000]:
            raise RuntimeError("Google returned its consent interstitial instead of flight data")
        return html


def inclusive_dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("departure end must not be before departure start")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def local_datetime(simple_datetime: Any) -> datetime:
    year, month, day = simple_datetime.date
    hour, minute = simple_datetime.time
    return datetime(year, month, day, hour, minute)


def itinerary_duration_minutes(segments: list[Any]) -> int:
    """Total elapsed minutes without needing an airport-timezone database.

    Flight durations are physical elapsed durations. Layover gaps are measured
    between arrival and next departure at the same connecting airport, so both
    timestamps are in the same local timezone.
    """
    if not segments:
        return 0
    total = sum(int(segment.duration) for segment in segments)
    for current, following in zip(segments, segments[1:]):
        gap = local_datetime(following.departure) - local_datetime(current.arrival)
        total += max(0, int(gap.total_seconds() // 60))
    return total


def layover_minutes(segments: list[Any]) -> list[int]:
    values: list[int] = []
    for current, following in zip(segments, segments[1:]):
        gap = local_datetime(following.departure) - local_datetime(current.arrival)
        values.append(max(0, int(gap.total_seconds() // 60)))
    return values


def fmt_simple_datetime(simple_datetime: Any) -> str:
    return local_datetime(simple_datetime).strftime("%Y-%m-%d %H:%M")


def normalize_result(result: Any, spec: SearchSpec, search_url: str) -> dict[str, Any]:
    segments = list(result.flights)
    airport_path = [segments[0].from_airport.code] if segments else [spec.origin]
    airport_path.extend(segment.to_airport.code for segment in segments)
    stops = max(0, len(segments) - 1)
    duration = itinerary_duration_minutes(segments)
    layovers = layover_minutes(segments)
    layover_labels = [
        f"{segments[index].to_airport.code} {minutes // 60}h {minutes % 60:02d}m"
        for index, minutes in enumerate(layovers)
    ]
    segment_details = [
        {
            "origin": segment.from_airport.code,
            "destination": segment.to_airport.code,
            "departure": fmt_simple_datetime(segment.departure),
            "arrival": fmt_simple_datetime(segment.arrival),
            "flight_minutes": int(segment.duration),
            "aircraft": segment.plane_type,
        }
        for segment in segments
    ]
    return {
        "trip_type": spec.trip,
        "origin": spec.origin,
        "destination": spec.destination,
        "departure_date": spec.departure_date,
        "return_date": spec.return_date or "",
        "stay_days": spec.stay_days if spec.stay_days is not None else "",
        "price_eur": int(result.price),
        "airlines": " / ".join(result.airlines),
        "stops": stops,
        "duration_minutes": duration,
        "duration": f"{duration // 60}h {duration % 60:02d}m",
        "layover_minutes_total": sum(layovers),
        "max_layover_minutes": max(layovers, default=0),
        "layovers": " / ".join(layover_labels),
        "airport_path": "-".join(airport_path),
        "departure_time": fmt_simple_datetime(segments[0].departure) if segments else "",
        "arrival_time": fmt_simple_datetime(segments[-1].arrival) if segments else "",
        "aircraft": " / ".join(segment.plane_type for segment in segments),
        "segments_json": json.dumps(segment_details, ensure_ascii=False),
        "search_url": search_url,
        "provider": "Google Flights via fast-flights",
    }


class GoogleFlightsProvider:
    def __init__(
        self,
        cache_dir: Path,
        max_stops: int,
        max_duration_minutes: int,
        max_layover_minutes: int | None = None,
        retries: int = 3,
    ):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_stops = max_stops
        self.max_duration_minutes = max_duration_minutes
        self.max_layover_minutes = max_layover_minutes
        self.retries = retries
        self.fetcher = ConsentFetcher()

    def _cache_path(self, spec: SearchSpec) -> Path:
        key_data = {
            "provider": PROVIDER_VERSION,
            "spec": asdict(spec),
            "max_stops": self.max_stops,
            "max_duration_minutes": self.max_duration_minutes,
            "currency": "EUR",
        }
        if self.max_layover_minutes is not None:
            key_data["max_layover_minutes"] = self.max_layover_minutes
        digest = hashlib.sha256(
            json.dumps(key_data, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _query(self, spec: SearchSpec):
        legs = [
            FlightQuery(
                date=spec.departure_date,
                from_airport=spec.origin,
                to_airport=spec.destination,
                max_stops=self.max_stops,
                max_duration_minutes=self.max_duration_minutes,
                max_layover_minutes=self.max_layover_minutes,
            )
        ]
        if spec.trip == "round-trip":
            if not spec.return_date:
                raise ValueError("round-trip search requires a return date")
            legs.append(
                FlightQuery(
                    date=spec.return_date,
                    from_airport=spec.destination,
                    to_airport=spec.origin,
                    max_stops=self.max_stops,
                    max_duration_minutes=self.max_duration_minutes,
                    max_layover_minutes=self.max_layover_minutes,
                )
            )
        return create_query(
            flights=legs,
            trip=spec.trip,
            seat="economy",
            passengers=Passengers(adults=1),
            language="en-US",
            currency="EUR",
            hide_separate_and_self_transfer=True,
        )

    @staticmethod
    def _write_cache(cache_path: Path, rows: list[dict[str, Any]]) -> None:
        payload = {
            "provider_version": PROVIDER_VERSION,
            "searched_at": datetime.now().astimezone().isoformat(),
            "rows": rows,
        }
        temp_path = cache_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(cache_path)

    def search(self, spec: SearchSpec) -> tuple[list[dict[str, Any]], str | None, bool]:
        cache_path = self._cache_path(spec)
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                return payload["rows"], None, True
            except (OSError, KeyError, json.JSONDecodeError):
                pass

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                query = self._query(spec)
                results = get_flights(query, integration=self.fetcher)
                rows = [normalize_result(result, spec, query.url()) for result in results]
                rows = [
                    row
                    for row in rows
                    if int(row["stops"]) <= self.max_stops
                    and int(row["duration_minutes"]) <= self.max_duration_minutes
                    and (
                        self.max_layover_minutes is None
                        or int(row["max_layover_minutes"]) <= self.max_layover_minutes
                    )
                ]
                self._write_cache(cache_path, rows)
                return rows, None, False
            except FlightsNotFound:
                self._write_cache(cache_path, [])
                return [], None, False
            except TypeError as exc:
                # fast-flights 3.1.0 assumes payload[3] is always a list.
                # Google uses payload[3] = null when no itinerary satisfies
                # the filters, which raises this exact parser error.
                if str(exc) == "'NoneType' object is not subscriptable":
                    self._write_cache(cache_path, [])
                    return [], None, False
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.5 * attempt)
                    continue
                break
            except Exception as exc:  # network and upstream parser failures
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.5 * attempt)

        assert last_error is not None
        message = f"{type(last_error).__name__}: {last_error}"
        return [], message, False


def run_specs(
    provider: GoogleFlightsProvider,
    specs: list[SearchSpec],
    workers: int,
    label: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    completed = 0
    cache_hits = 0
    started = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(provider.search, spec): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            result_rows, error, cached = future.result()
            rows.extend(result_rows)
            completed += 1
            cache_hits += int(cached)
            if error:
                errors.append({**asdict(spec), "error": error})
            if completed == len(specs) or completed % 10 == 0:
                elapsed = time.monotonic() - started
                print(
                    f"{label}: {completed}/{len(specs)} queries, "
                    f"{len(rows)} options, {len(errors)} errors, "
                    f"{cache_hits} cached, {elapsed:.0f}s",
                    flush=True,
                )
    return rows, errors


def cheapest_by_leg(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["origin"], row["destination"], row["departure_date"])
        if key not in best or int(row["price_eur"]) < int(best[key]["price_eur"]):
            best[key] = row
    return best


def build_individual_combinations(
    one_way_rows: list[dict[str, Any]],
    origin: str,
    destinations: list[str],
    departure_dates: list[date],
    min_stay: int,
    max_stay: int,
) -> list[dict[str, Any]]:
    best = cheapest_by_leg(one_way_rows)
    combinations: list[dict[str, Any]] = []
    for outbound_date in departure_dates:
        outbound_iso = outbound_date.isoformat()
        for stay_days in range(min_stay, max_stay + 1):
            return_iso = (outbound_date + timedelta(days=stay_days)).isoformat()
            for outbound_destination in destinations:
                outgoing = best.get((origin, outbound_destination, outbound_iso))
                if not outgoing:
                    continue
                for return_origin in destinations:
                    returning = best.get((return_origin, origin, return_iso))
                    if not returning:
                        continue
                    combinations.append(
                        {
                            "booking_type": "two separate one-way tickets",
                            "total_price_eur": int(outgoing["price_eur"])
                            + int(returning["price_eur"]),
                            "departure_date": outbound_iso,
                            "return_date": return_iso,
                            "stay_days": stay_days,
                            "outbound_destination": outbound_destination,
                            "return_origin": return_origin,
                            "open_jaw": outbound_destination != return_origin,
                            "outbound_price_eur": outgoing["price_eur"],
                            "outbound_airlines": outgoing["airlines"],
                            "outbound_path": outgoing["airport_path"],
                            "outbound_departure": outgoing["departure_time"],
                            "outbound_arrival": outgoing["arrival_time"],
                            "outbound_duration": outgoing["duration"],
                            "outbound_duration_minutes": outgoing["duration_minutes"],
                            "outbound_stops": outgoing["stops"],
                            "outbound_layover_minutes_total": outgoing[
                                "layover_minutes_total"
                            ],
                            "outbound_max_layover_minutes": outgoing[
                                "max_layover_minutes"
                            ],
                            "outbound_layovers": outgoing["layovers"],
                            "outbound_search_url": outgoing["search_url"],
                            "return_price_eur": returning["price_eur"],
                            "return_airlines": returning["airlines"],
                            "return_path": returning["airport_path"],
                            "return_departure": returning["departure_time"],
                            "return_arrival": returning["arrival_time"],
                            "return_duration": returning["duration"],
                            "return_duration_minutes": returning["duration_minutes"],
                            "return_stops": returning["stops"],
                            "return_layover_minutes_total": returning[
                                "layover_minutes_total"
                            ],
                            "return_max_layover_minutes": returning[
                                "max_layover_minutes"
                            ],
                            "return_layovers": returning["layovers"],
                            "return_search_url": returning["search_url"],
                        }
                    )
    return sorted(combinations, key=lambda row: (row["total_price_eur"], row["departure_date"]))


def roundtrip_specs(
    origin: str,
    destinations: list[str],
    departure_dates: list[date],
    min_stay: int,
    max_stay: int,
) -> list[SearchSpec]:
    return [
        SearchSpec(
            trip="round-trip",
            origin=origin,
            destination=destination,
            departure_date=departure_date.isoformat(),
            return_date=(departure_date + timedelta(days=stay_days)).isoformat(),
        )
        for departure_date in departure_dates
        for stay_days in range(min_stay, max_stay + 1)
        for destination in destinations
    ]


def shortlist_roundtrips(
    all_specs: list[SearchSpec],
    individual_rows: list[dict[str, Any]],
    limit: int,
) -> list[SearchSpec]:
    scores = {
        (
            row["outbound_destination"],
            row["departure_date"],
            row["return_date"],
        ): int(row["total_price_eur"])
        for row in individual_rows
        if not row["open_jaw"]
    }
    ranked = sorted(
        all_specs,
        key=lambda spec: scores.get(
            (spec.destination, spec.departure_date, spec.return_date or ""), 10**9
        ),
    )
    return ranked[:limit]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="BER")
    parser.add_argument("--destinations", nargs="+", default=["LCA", "PFO"])
    parser.add_argument("--departure-start", default="2026-10-01")
    parser.add_argument("--departure-end", default="2026-10-31")
    parser.add_argument("--min-stay", type=int, default=5)
    parser.add_argument("--max-stay", type=int, default=7)
    parser.add_argument("--max-stops", type=int, default=1)
    parser.add_argument("--max-duration-minutes", type=int, default=300)
    parser.add_argument(
        "--max-layover-minutes",
        type=int,
        default=None,
        help="Optional maximum duration of each individual layover.",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--roundtrip-mode",
        choices=("full", "shortlist", "skip"),
        default="full",
        help="Full scans every date pair; shortlist checks the cheapest separate-ticket dates.",
    )
    parser.add_argument("--roundtrip-shortlist", type=int, default=30)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "flight_search_results",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(__file__).resolve().parent / ".flight_finder_cache",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    start = date.fromisoformat(args.departure_start)
    end = date.fromisoformat(args.departure_end)
    departure_dates = inclusive_dates(start, end)
    if args.min_stay < 1 or args.max_stay < args.min_stay:
        raise SystemExit("Stay range must be positive and max-stay >= min-stay")
    if args.workers < 1:
        raise SystemExit("workers must be at least 1")

    destinations = [code.upper() for code in args.destinations]
    origin = args.origin.upper()
    return_dates = inclusive_dates(
        start + timedelta(days=args.min_stay),
        end + timedelta(days=args.max_stay),
    )
    outbound_specs = [
        SearchSpec("one-way", origin, destination, travel_date.isoformat())
        for travel_date in departure_dates
        for destination in destinations
    ]
    inbound_specs = [
        SearchSpec("one-way", destination, origin, travel_date.isoformat())
        for travel_date in return_dates
        for destination in destinations
    ]
    all_roundtrip_specs = roundtrip_specs(
        origin,
        destinations,
        departure_dates,
        args.min_stay,
        args.max_stay,
    )

    print(
        f"Planned: {len(outbound_specs) + len(inbound_specs)} one-way queries and "
        f"{len(all_roundtrip_specs)} possible round-trip queries."
    )
    if args.dry_run:
        return 0

    provider = GoogleFlightsProvider(
        args.cache_dir,
        max_stops=args.max_stops,
        max_duration_minutes=args.max_duration_minutes,
        max_layover_minutes=args.max_layover_minutes,
    )
    one_way_rows, errors = run_specs(
        provider,
        outbound_specs + inbound_specs,
        workers=args.workers,
        label="One-way",
    )
    one_way_rows.sort(
        key=lambda row: (row["departure_date"], row["origin"], row["price_eur"])
    )
    individual_rows = build_individual_combinations(
        one_way_rows,
        origin,
        destinations,
        departure_dates,
        args.min_stay,
        args.max_stay,
    )

    selected_roundtrip_specs: list[SearchSpec] = []
    if args.roundtrip_mode == "full":
        selected_roundtrip_specs = all_roundtrip_specs
    elif args.roundtrip_mode == "shortlist":
        selected_roundtrip_specs = shortlist_roundtrips(
            all_roundtrip_specs,
            individual_rows,
            args.roundtrip_shortlist,
        )

    roundtrip_rows: list[dict[str, Any]] = []
    if selected_roundtrip_specs:
        roundtrip_rows, roundtrip_errors = run_specs(
            provider,
            selected_roundtrip_specs,
            workers=args.workers,
            label="Round-trip",
        )
        errors.extend(roundtrip_errors)
        for row in roundtrip_rows:
            row["price_interpretation"] = "advertised total round-trip fare"
            row["return_details"] = (
                "Provider validates return filters but exposes return choices only after "
                "selecting the outbound; open search_url to confirm the exact return."
            )
        roundtrip_rows.sort(
            key=lambda row: (row["price_eur"], row["departure_date"], row["destination"])
        )

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "one_way_options.csv", one_way_rows)
    write_csv(output_dir / "individual_combinations.csv", individual_rows)
    write_csv(output_dir / "roundtrip_options.csv", roundtrip_rows)
    write_csv(output_dir / "search_errors.csv", errors)

    cheapest_individual = individual_rows[0] if individual_rows else None
    cheapest_roundtrip = roundtrip_rows[0] if roundtrip_rows else None
    summary = {
        "report_generated_at": datetime.now().astimezone().isoformat(),
        "query": {
            "origin": origin,
            "destinations": destinations,
            "departure_start": start.isoformat(),
            "departure_end": end.isoformat(),
            "return_may_enter_next_month": True,
            "stay_days_inclusive": [args.min_stay, args.max_stay],
            "max_stops_per_leg": args.max_stops,
            "max_duration_minutes_per_leg": args.max_duration_minutes,
            "max_layover_minutes": args.max_layover_minutes,
            "currency": "EUR",
            "adults": 1,
        },
        "counts": {
            "one_way_queries": len(outbound_specs) + len(inbound_specs),
            "one_way_options": len(one_way_rows),
            "individual_combinations": len(individual_rows),
            "roundtrip_queries": len(selected_roundtrip_specs),
            "roundtrip_options": len(roundtrip_rows),
            "errors": len(errors),
        },
        "cheapest_individual": cheapest_individual,
        "cheapest_roundtrip": cheapest_roundtrip,
        "notes": [
            "Prices are live search snapshots and can change before booking.",
            "Report generation may reuse per-query cached snapshots from an earlier run.",
            "Separate-ticket combinations may require airport transfer when open_jaw=true.",
            "The round-trip parser exposes the priced outbound; confirm the return flight via search_url.",
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Results written to {output_dir.resolve()}")
    if cheapest_individual:
        print(
            "Cheapest separate tickets: "
            f"EUR {cheapest_individual['total_price_eur']} | "
            f"{cheapest_individual['departure_date']} to {cheapest_individual['return_date']} | "
            f"{cheapest_individual['outbound_destination']}/"
            f"{cheapest_individual['return_origin']}"
        )
    if cheapest_roundtrip:
        print(
            "Cheapest advertised round trip: "
            f"EUR {cheapest_roundtrip['price_eur']} | "
            f"{cheapest_roundtrip['departure_date']} to "
            f"{cheapest_roundtrip['return_date']} | "
            f"{cheapest_roundtrip['destination']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
