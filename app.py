"""Optional Streamlit interface with a command-line fallback.

Run ``streamlit run app.py`` for the browser interface. Running this file with
ordinary Python delegates to ``flight_finder_v2.py`` and does not require
Streamlit to be installed.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import flight_finder_v2 as finder


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_DIR = REPO_ROOT / ".flight_finder_ui" / "results"
DEFAULT_CACHE_DIR = REPO_ROOT / ".flight_finder_ui" / "cache"


def streamlit_installed() -> bool:
    """Return whether the optional UI dependency is importable."""

    return importlib.util.find_spec("streamlit") is not None


def streamlit_runtime_exists() -> bool:
    """Distinguish ``streamlit run`` from a normal ``python app.py`` call."""

    if not streamlit_installed():
        return False
    try:
        from streamlit.runtime import exists

        return bool(exists())
    except (ImportError, RuntimeError):
        return False


def parse_destinations(value: str) -> list[str]:
    """Parse comma- or whitespace-separated IATA codes and preserve order."""

    result: list[str] = []
    for token in value.replace(",", " ").split():
        code = token.strip().upper()
        if code and code not in result:
            result.append(code)
    return result


def build_cli_args(settings: dict[str, Any]) -> list[str]:
    """Convert UI settings to the v2 command-line interface."""

    args = [
        "--origin",
        str(settings["origin"]).upper(),
        "--destinations",
        *settings["destinations"],
        "--departure-start",
        settings["departure_start"].isoformat(),
        "--departure-end",
        settings["departure_end"].isoformat(),
        "--min-stay",
        str(settings["min_stay"]),
        "--max-stay",
        str(settings["max_stay"]),
        "--max-stops",
        str(settings["max_stops"]),
        "--max-duration-minutes",
        str(settings["max_duration_minutes"]),
        "--workers",
        str(settings["workers"]),
        "--roundtrip-mode",
        str(settings["roundtrip_mode"]),
        "--output-dir",
        str(settings["output_dir"]),
        "--cache-dir",
        str(settings["cache_dir"]),
    ]
    max_layover = settings.get("max_layover_minutes")
    if max_layover is not None:
        args.extend(["--max-layover-minutes", str(max_layover)])
    return args


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_result_bundle(output_dir: Path) -> dict[str, Any]:
    summary_path = output_dir / "summary.json"
    summary = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.exists()
        else {}
    )
    return {
        "summary": summary,
        "individual": read_csv_rows(output_dir / "individual_combinations.csv"),
        "roundtrip": read_csv_rows(output_dir / "roundtrip_options.csv"),
        "one_way": read_csv_rows(output_dir / "one_way_options.csv"),
        "errors": read_csv_rows(output_dir / "search_errors.csv"),
        "output_dir": output_dir,
        "example": False,
    }


def demo_result_bundle() -> dict[str, Any]:
    """Return deterministic illustrative rows for the README screenshots."""

    link = "https://www.google.com/travel/flights"
    individual = [
        {
            "total_price_eur": 207,
            "departure_date": "2027-10-07",
            "return_date": "2027-10-13",
            "stay_days": 6,
            "outbound_destination": "ECN",
            "return_origin": "ECN",
            "open_jaw": False,
            "outbound_airlines": "AJet",
            "outbound_departure": "16:35",
            "outbound_duration": "5h 40m",
            "outbound_stops": 1,
            "outbound_layovers": "SAW 1h 15m",
            "return_airlines": "Pegasus",
            "return_departure": "12:50",
            "return_duration": "6h 45m",
            "return_stops": 1,
            "return_layovers": "SAW 2h 10m",
            "outbound_search_url": link,
            "return_search_url": link,
        },
        {
            "total_price_eur": 243,
            "departure_date": "2027-10-07",
            "return_date": "2027-10-15",
            "stay_days": 8,
            "outbound_destination": "ECN",
            "return_origin": "LCA",
            "open_jaw": True,
            "outbound_airlines": "AJet",
            "outbound_departure": "16:35",
            "outbound_duration": "5h 40m",
            "outbound_stops": 1,
            "outbound_layovers": "SAW 1h 15m",
            "return_airlines": "easyJet",
            "return_departure": "18:55",
            "return_duration": "4h 05m",
            "return_stops": 0,
            "return_layovers": "—",
            "outbound_search_url": link,
            "return_search_url": link,
        },
        {
            "total_price_eur": 259,
            "departure_date": "2027-10-08",
            "return_date": "2027-10-15",
            "stay_days": 7,
            "outbound_destination": "LCA",
            "return_origin": "LCA",
            "open_jaw": False,
            "outbound_airlines": "Eurowings",
            "outbound_departure": "11:20",
            "outbound_duration": "3h 45m",
            "outbound_stops": 0,
            "outbound_layovers": "—",
            "return_airlines": "easyJet",
            "return_departure": "18:55",
            "return_duration": "4h 05m",
            "return_stops": 0,
            "return_layovers": "—",
            "outbound_search_url": link,
            "return_search_url": link,
        },
    ]
    roundtrip = [
        {
            "price_eur": 205,
            "departure_date": "2027-10-07",
            "return_date": "2027-10-13",
            "destination": "ECN",
            "airlines": "AJet",
            "departure_time": "16:35",
            "arrival_time": "23:15",
            "duration": "5h 40m",
            "stops": 1,
            "layovers": "SAW 1h 15m",
            "search_url": link,
        },
        {
            "price_eur": 280,
            "departure_date": "2027-10-08",
            "return_date": "2027-10-15",
            "destination": "LCA",
            "airlines": "Eurowings",
            "departure_time": "11:20",
            "arrival_time": "16:05",
            "duration": "3h 45m",
            "stops": 0,
            "layovers": "—",
            "search_url": link,
        },
    ]
    summary = {
        "report_generated_at": "2027-08-28T12:00:00+02:00",
        "query": {
            "origin": "BER",
            "destinations": ["LCA", "PFO", "ECN"],
            "departure_start": "2027-10-01",
            "departure_end": "2027-10-20",
            "stay_days_inclusive": [5, 7],
        },
        "counts": {
            "one_way_queries": 126,
            "one_way_options": 384,
            "individual_combinations": 241,
            "roundtrip_queries": 180,
            "roundtrip_options": 522,
            "errors": 0,
        },
        "cheapest_individual": individual[0],
        "cheapest_roundtrip": roundtrip[0],
    }
    return {
        "summary": summary,
        "individual": individual,
        "roundtrip": roundtrip,
        "one_way": [],
        "errors": [],
        "output_dir": None,
        "example": True,
    }


def run_search(settings: dict[str, Any]) -> tuple[int, str, dict[str, Any] | None]:
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            exit_code = finder.main(build_cli_args(settings))
    except Exception as error:  # Display provider and filesystem failures in the UI.
        return 1, f"{output.getvalue()}\n{type(error).__name__}: {error}", None
    bundle = load_result_bundle(Path(settings["output_dir"])) if exit_code == 0 else None
    return exit_code, output.getvalue(), bundle


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def render_table(st: Any, rows: list[dict[str, Any]], columns: list[str], key: str) -> None:
    if not rows:
        st.info("No matching rows were returned for this view.")
        return
    compact = [{column: row.get(column, "") for column in columns} for row in rows[:100]]
    st.dataframe(compact, use_container_width=True, hide_index=True)
    st.download_button(
        "Download this table",
        rows_to_csv(rows),
        file_name=f"{key}.csv",
        mime="text/csv",
        key=f"download-{key}",
    )


def render_streamlit() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Flight Finder",
        page_icon="✈️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {background: #f4f7fb;}
        [data-testid="stMetric"] {
            background: white; border: 1px solid #e3e8ef; border-radius: 12px;
            padding: 14px 16px;
        }
        .ff-card {
            min-height: 115px; padding: 18px; border: 1px solid #e3e8ef;
            border-radius: 14px; background: white;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("✈️ Flight Finder")
    st.caption(
        "Compare flexible dates, advertised round trips, and pairs of one-way tickets. "
        "Prices are snapshots—confirm the final itinerary before booking."
    )

    today = date.today()
    october_year = today.year + 1 if today.month >= 10 else today.year
    october_start = date(october_year, 10, 1)
    with st.sidebar:
        st.header("Search settings")
        origin = st.text_input("From", "BER", max_chars=3).upper()
        destination_text = st.text_input("To (one or more IATA codes)", "LCA, PFO, ECN")
        default_dates = (october_start, october_start + timedelta(days=19))
        selected_dates = st.date_input("Departure window", value=default_dates)
        if isinstance(selected_dates, (list, tuple)) and len(selected_dates) == 2:
            departure_start, departure_end = selected_dates
        else:
            departure_start = departure_end = selected_dates

        stay_col1, stay_col2 = st.columns(2)
        min_stay = stay_col1.number_input("Min nights", 1, 30, 5)
        max_stay = stay_col2.number_input("Max nights", 1, 30, 7)
        max_stops = st.selectbox("Maximum stops per direction", [0, 1, 2], index=1)
        max_duration_hours = st.slider("Maximum travel time", 3, 16, 8, format="%d h")
        max_layover = st.slider("Maximum individual layover", 30, 360, 150, step=15)

        with st.expander("Advanced"):
            workers = st.slider("Parallel searches", 1, 8, 4)
            roundtrip_mode = st.selectbox(
                "Round-trip scan",
                ["full", "shortlist", "skip"],
                help="Full is thorough; shortlist is faster; skip checks separate tickets only.",
            )
            output_dir = Path(st.text_input("Results folder", str(DEFAULT_RESULTS_DIR)))
            cache_dir = Path(st.text_input("Cache folder", str(DEFAULT_CACHE_DIR)))

        search_clicked = st.button("Search flights", type="primary", use_container_width=True)

    destinations = parse_destinations(destination_text)
    if "bundle" not in st.session_state:
        st.session_state.bundle = None
    if "search_log" not in st.session_state:
        st.session_state.search_log = ""

    button_col1, button_col2, spacer = st.columns([1.35, 1, 4])
    if button_col1.button("Load example results", use_container_width=True):
        st.session_state.bundle = demo_result_bundle()
        st.session_state.search_log = "Loaded built-in illustrative results; no live request was made."
    if button_col2.button("Clear results", use_container_width=True):
        st.session_state.bundle = None
        st.session_state.search_log = ""

    if search_clicked:
        validation_errors = []
        if len(origin) != 3:
            validation_errors.append("Enter a three-letter origin code.")
        if not destinations:
            validation_errors.append("Enter at least one destination code.")
        if min_stay > max_stay:
            validation_errors.append("Minimum nights cannot exceed maximum nights.")
        if departure_start > departure_end:
            validation_errors.append("The departure window is reversed.")
        if validation_errors:
            for message in validation_errors:
                st.error(message)
        else:
            settings = {
                "origin": origin,
                "destinations": destinations,
                "departure_start": departure_start,
                "departure_end": departure_end,
                "min_stay": min_stay,
                "max_stay": max_stay,
                "max_stops": max_stops,
                "max_duration_minutes": max_duration_hours * 60,
                "max_layover_minutes": max_layover,
                "workers": workers,
                "roundtrip_mode": roundtrip_mode,
                "output_dir": output_dir,
                "cache_dir": cache_dir,
            }
            with st.spinner("Searching flexible dates. This can take several minutes…"):
                exit_code, log, bundle = run_search(settings)
            st.session_state.search_log = log
            if exit_code == 0 and bundle is not None:
                st.session_state.bundle = bundle
                st.success("Search complete.")
            else:
                st.error("The search did not finish. Open the search log below for details.")

    bundle = st.session_state.bundle
    if bundle is None:
        st.info("Set a date window and search live prices, or load the example results for a quick tour.")
        cards = st.columns(3)
        cards[0].markdown(
            '<div class="ff-card"><b>Flexible dates</b><br><br>Search a whole window and choose a 5–7 night stay.</div>',
            unsafe_allow_html=True,
        )
        cards[1].markdown(
            '<div class="ff-card"><b>Ticket strategies</b><br><br>Compare round trips with separate and open-jaw tickets.</div>',
            unsafe_allow_html=True,
        )
        cards[2].markdown(
            '<div class="ff-card"><b>Practical filters</b><br><br>Limit stops, total travel time, and individual layovers.</div>',
            unsafe_allow_html=True,
        )
        return

    if bundle.get("example"):
        st.warning("Example data for interface demonstration only—not current prices or bookable results.")

    summary = bundle.get("summary", {})
    counts = summary.get("counts", {})
    cheapest_individual = summary.get("cheapest_individual") or {}
    cheapest_roundtrip = summary.get("cheapest_roundtrip") or {}
    metrics = st.columns(4)
    metrics[0].metric(
        "Best separate tickets",
        f"€{cheapest_individual.get('total_price_eur', '—')}",
    )
    metrics[1].metric(
        "Best advertised round trip",
        f"€{cheapest_roundtrip.get('price_eur', '—')}",
    )
    metrics[2].metric("Separate combinations", counts.get("individual_combinations", 0))
    metrics[3].metric("Search errors", counts.get("errors", 0))

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Separate tickets", "Round trips", "One-way options", "Errors"]
    )
    with tab1:
        st.subheader("Cheapest separate-ticket combinations")
        render_table(
            st,
            bundle["individual"],
            [
                "total_price_eur",
                "departure_date",
                "return_date",
                "stay_days",
                "outbound_destination",
                "return_origin",
                "open_jaw",
                "outbound_airlines",
                "outbound_departure",
                "outbound_duration",
                "outbound_stops",
                "outbound_layovers",
                "return_airlines",
                "return_departure",
                "return_duration",
                "return_stops",
                "return_layovers",
            ],
            "individual_combinations",
        )
    with tab2:
        st.subheader("Advertised round-trip options")
        st.caption("Open the generated search link to confirm the exact return flight and final total.")
        render_table(
            st,
            bundle["roundtrip"],
            [
                "price_eur",
                "departure_date",
                "return_date",
                "destination",
                "airlines",
                "departure_time",
                "arrival_time",
                "duration",
                "stops",
                "layovers",
                "search_url",
            ],
            "roundtrip_options",
        )
    with tab3:
        st.subheader("Qualifying one-way options")
        render_table(
            st,
            bundle["one_way"],
            [
                "price_eur",
                "departure_date",
                "origin",
                "destination",
                "airlines",
                "departure_time",
                "arrival_time",
                "duration",
                "stops",
                "layovers",
                "search_url",
            ],
            "one_way_options",
        )
    with tab4:
        st.subheader("Search errors")
        render_table(st, bundle["errors"], list(bundle["errors"][0]) if bundle["errors"] else [], "search_errors")

    if st.session_state.search_log:
        with st.expander("Search log"):
            st.code(st.session_state.search_log, language="text")


def cli_main(argv: list[str] | None = None) -> int:
    """Run the v2 CLI; this path has no optional UI dependencies."""

    return finder.main(argv)


if __name__ == "__main__":
    if streamlit_runtime_exists():
        render_streamlit()
    else:
        raise SystemExit(cli_main(sys.argv[1:]))
