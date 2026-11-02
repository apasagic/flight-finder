from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import flight_finder_v2 as finder


def moment(day: int, hour: int, minute: int) -> SimpleNamespace:
    return SimpleNamespace(date=(2027, 10, day), time=(hour, minute))


def segment(
    origin: str,
    destination: str,
    departure: SimpleNamespace,
    arrival: SimpleNamespace,
    duration: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        from_airport=SimpleNamespace(code=origin),
        to_airport=SimpleNamespace(code=destination),
        departure=departure,
        arrival=arrival,
        duration=duration,
        plane_type="Test aircraft",
    )


def row(origin: str, destination: str, travel_date: str, price: int) -> dict:
    return {
        "origin": origin,
        "destination": destination,
        "departure_date": travel_date,
        "price_eur": price,
        "airlines": "Test Air",
        "airport_path": f"{origin}-{destination}",
        "departure_time": f"{travel_date} 10:00",
        "arrival_time": f"{travel_date} 14:00",
        "duration": "4h 00m",
        "duration_minutes": 240,
        "stops": 0,
        "layover_minutes_total": 0,
        "max_layover_minutes": 0,
        "layovers": "",
        "search_url": "https://example.invalid/flights",
    }


class FlightFinderTests(unittest.TestCase):
    def test_inclusive_dates_includes_both_endpoints(self) -> None:
        self.assertEqual(
            finder.inclusive_dates(date(2027, 10, 1), date(2027, 10, 3)),
            [date(2027, 10, 1), date(2027, 10, 2), date(2027, 10, 3)],
        )

    def test_elapsed_duration_and_layover(self) -> None:
        legs = [
            segment("BER", "SAW", moment(7, 10, 0), moment(7, 13, 0), 180),
            segment("SAW", "ECN", moment(7, 14, 10), moment(7, 15, 40), 90),
        ]
        self.assertEqual(finder.layover_minutes(legs), [70])
        self.assertEqual(finder.itinerary_duration_minutes(legs), 340)

    def test_individual_combinations_include_open_jaw(self) -> None:
        rows = [
            row("BER", "LCA", "2027-10-01", 100),
            row("BER", "PFO", "2027-10-01", 120),
            row("LCA", "BER", "2027-10-06", 90),
            row("PFO", "BER", "2027-10-06", 80),
        ]
        combinations = finder.build_individual_combinations(
            rows,
            origin="BER",
            destinations=["LCA", "PFO"],
            departure_dates=[date(2027, 10, 1)],
            min_stay=5,
            max_stay=5,
        )
        self.assertEqual(len(combinations), 4)
        self.assertEqual(combinations[0]["total_price_eur"], 180)
        self.assertTrue(combinations[0]["open_jaw"])
        self.assertEqual(combinations[0]["outbound_destination"], "LCA")
        self.assertEqual(combinations[0]["return_origin"], "PFO")

    def test_write_csv_preserves_union_of_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "results.csv"
            finder.write_csv(output, [{"a": 1}, {"a": 2, "b": 3}])
            text = output.read_text(encoding="utf-8-sig")
        self.assertEqual(text.splitlines()[0], "a,b")
        self.assertIn("2,3", text)


if __name__ == "__main__":
    unittest.main()
