import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from main import run_flight_search   # your wrapper function

st.title("✈️ Flight Finder Tool")

st.markdown("Configure your search parameters below:")

# ----------- User inputs -------------
st.header("Search Settings")

departureId = st.text_input("Departure Airport (IATA)", "BER")
arrivalId = st.text_input("Arrival Airport (IATA)", "BKK")

col1, col2 = st.columns(2)

with col1:
    departureDateStart = st.date_input(
        "Earliest Departure",
        datetime(2026, 1, 5)
    )

with col2:
    departureDateEnd = st.date_input(
        "Latest Departure",
        datetime(2026, 2, 15)
    )

st.divider()

st.header("Trip Duration")

col3, col4, col5 = st.columns(3)

with col3:
    minDurationDays = st.number_input(
        "Minimum trip length (days)",
        1, 60, 15
    )

with col4:
    maxDurationDays = st.number_input(
        "Maximum trip length (days)",
        1, 60, 23
    )

with col5:
    maxDuration = st.number_input(
        "Max flight duration (hours)",
        1, 48, 16
    )

st.divider()

st.header("Flight Filters")

maxPrice = st.number_input("Max Price (€)", 1, 2000, 850)
adults = st.number_input("Adults", 1, 6, 1)

maxFlights = st.slider("Max outgoing flights per day", 1, 20, 6)

isRoundtrip = st.checkbox("Roundtrip", True)

# ----------- Sorting option ----------
st.header("Sort Results")
sort_col = st.selectbox(
    "Sort flights by:",
    ["Price", "duration_hours", "Departure Date Outgoing"]
)

# ----------- Run search ----------------
run_button = st.button("🔎 Search flights")

if run_button:
    st.write("Searching flights... Please wait ⏳")

    df = run_flight_search(
        departureId=str(departureId),
        arrivalId=str(arrivalId),
        departureDateStart=str(departureDateStart),
        departureDateEnd=str(departureDateEnd),
        minDurationDays=minDurationDays,
        maxDurationDays=maxDurationDays,
        maxPrice=str(maxPrice),
        adults=str(adults),
        maxDuration=str(maxDuration) + "h00",
        maxFlights=maxFlights,
        isRoundtrip=isRoundtrip
    )

    # ----------- Convert duration to hours ----------
    def minutes_to_hhmm(x):
        try:
            minutes = int(x)
            h = minutes // 60
            m = minutes % 60
            return f"{h}h {m}m"
        except:
            return x  # keep original if conversion fails

    if "duration" in df.columns:
        df["duration_hours"] = df["duration"].apply(minutes_to_hhmm)

    # ----------- Sort DataFrame ----------
    if sort_col == "duration_hours":
        # Convert HHhMM to minutes for proper sorting
        def hhmm_to_minutes(x):
            try:
                parts = x.split("h")
                h = int(parts[0])
                m = int(parts[1].replace("m",""))
                return h*60 + m
            except:
                return 0
        df["duration_minutes"] = df["duration_hours"].apply(hhmm_to_minutes)
        df_sorted = df.sort_values(by="duration_minutes", ascending=True)
        df_sorted = df_sorted.drop(columns=["duration_minutes"])
    else:
        df_sorted = df.sort_values(by=sort_col, ascending=True)

    st.success("Search complete!")

    st.dataframe(df_sorted)

    # Excel download
    excel_file = "flights_export.xlsx"
    df_sorted.to_excel(excel_file, index=False)

    with open(excel_file, "rb") as f:
        st.download_button(
            label="📥 Download Excel",
            data=f,
            file_name=excel_file,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
