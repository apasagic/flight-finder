---
name: flight-search
description: Search and compare flexible-date flights with this repository's cached Google Flights CLI when a user asks for airfare, round trips versus separate tickets, open-jaw routes, stops, duration, layovers, or ranked options. Do not use it to purchase tickets or modify airline accounts.
---

# Flight Search

Use `flight_finder_v2.py` for broad discovery before opening individual flight
pages. It produces consistent, auditable results while avoiding one browser
search per date combination.

Prefer a Git checkout containing `flight_finder_v2.py`. If the current workspace
is not that checkout, locate an existing `flight-finder` repository before
creating another copy, and avoid stale exported scripts.

## Search workflow

1. Translate the request into explicit origin and destination IATA codes,
   departure range, stay range, maximum stops, elapsed time, and individual
   layover limit. Preserve the user's stated airports and constraints.
2. Run the CLI from the repository root. Use a date-stamped cache directory for
   a fresh search; reuse that cache only within the same price-checking session.
3. Use `--roundtrip-mode full` when the user asks to compare true round trips
   with separate tickets. Use `shortlist` only when speed matters more than an
   exhaustive round-trip scan.
4. Rank `individual_combinations.csv` and `roundtrip_options.csv` separately,
   then merge the best candidates. Include open-jaw transfer costs as an explicit
   caveat rather than silently treating airports as interchangeable.
5. If the user cares about departure time, airline, or direct service, filter
   `one_way_options.csv` first and recombine eligible outbound and return legs.
   `individual_combinations.csv` contains the cheapest leg, not every convenient
   leg.
6. Open the generated `search_url` for the leading candidates and verify current
   price, exact return flight, baggage conditions, and booking provider. The
   round-trip parser exposes only the selected outbound details.

## Reporting

State the search timestamp and assumptions. For each shortlisted itinerary show
dates, airports, airlines, departure times, elapsed time per direction, stops,
individual layovers, fare per traveler, total for the requested travelers, and
the comparison baseline when one was supplied.

Keep cached/parser prices distinct from live-verified prices. Do not claim that
a fare is bookable until its current Google Flights page has been checked.

Do not purchase, reserve, message, or create an airline account without explicit
user authorization.
