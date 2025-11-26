import http.client
import json
import pandas as pd
from datetime import datetime, timedelta
import requests
from utilities import (
    get_request,
    pretty_print,
    get_outgoing_flight,
    find_returns,
    print_dict,
    add_entry_table,
    load_config
)


def run_flight_search(
        departureDateStart,
        departureDateEnd,
        departureId,
        arrivalId,
        adults,
        maxPrice,
        maxDuration,
        minDurationDays,
        maxDurationDays,
        maxFlights,
        isRoundtrip=True
    ):
    """
    Main function to run the flight search.
    Returns:
        df (DataFrame) – all collected flight options
    """
    
    # -------------------------------------------------------
    # Load config
    # -------------------------------------------------------
    config = load_config()
    api_config = config['api']

    base_url_google_flights = api_config['base_url']
    headers = api_config['headers']

    # Output filename
    if isRoundtrip:
        fileName = f"roundtrip_flights_{departureId}_{arrivalId}.csv"
    else:
        fileName = f"oneway_flights_{departureId}_{arrivalId}.csv"

    # Dataframe to fill
    df = pd.DataFrame()

    # -------------------------------------------------------
    # Iterate departure dates
    # -------------------------------------------------------
    count_departure_day = 1

    while True:

        departureDate = datetime.strptime(departureDateStart, "%Y-%m-%d") + timedelta(days=count_departure_day)

        # Stop if beyond last allowed departure date
        if departureDate >= datetime.strptime(departureDateEnd, "%Y-%m-%d"):
            break

        departureDateStr = departureDate.strftime("%Y-%m-%d")
        count_departure_day += 1

        # Earliest return date
        dt_return_min = departureDate + timedelta(days=minDurationDays)

        # Latest possible return date
        maxReturnDate_dt = departureDate + timedelta(days=maxDurationDays)

        # Iterate return dates
        count_return_day = 0

        while True:

            returnDate = dt_return_min + timedelta(days=count_return_day)
            count_return_day += 1

            if returnDate >= maxReturnDate_dt:
                break

            returnDateStr = returnDate.strftime("%Y-%m-%d")

            print(f"Searching for flights departing on {departureDateStr} and returning on {returnDateStr}...")

            # -------------------------------------------------------
            # Outgoing flights
            # -------------------------------------------------------
            flights = get_outgoing_flight(
                departureId, arrivalId,
                departureDateStr,
                returnDateStr,
                maxDuration,
                maxPrice,
                base_url_google_flights,
                headers,
                isRoundtrip
            )

            if flights is None:
                continue

            flights_outgoing = []
            if flights['topFlights'] is not None:
                flights_outgoing += flights['topFlights']
            if flights['otherFlights'] is not None:
                flights_outgoing += flights['otherFlights']

            count_flights_outgoing = 0

            for flight_outgoing in flights_outgoing:

                count_flights_outgoing += 1
                if count_flights_outgoing > maxFlights:
                    break

                price = flight_outgoing.get('price', 0)
                returning_token = flight_outgoing.get('returningToken')

                # -------------------------------------------------------
                # Return Flights
                # -------------------------------------------------------
                if isRoundtrip:
                    request_path = (
                        f"/flights/roundtrip-returning?"
                        f"arrivalDate={returnDateStr}&adults={adults}"
                        f"&stops=0&maxPrice={maxPrice}&flightDuration={maxDuration}"
                    )

                    data_ret = get_request(
                        base_url_google_flights,
                        request_path,
                        headers,
                        retTok=returning_token
                    )
                else:
                    # one-way flight: reverse airports
                    data_ret = get_outgoing_flight(
                        arrivalId, departureId,
                        returnDateStr, returnDateStr,
                        maxDuration, maxPrice,
                        base_url_google_flights,
                        headers,
                        isRoundtrip
                    )

                flights_return = data_ret.get('topFlights', []) + data_ret.get('otherFlights', [])

                count_return_flights = 0

                if isRoundtrip and flights_return == []:
                    # No multiple return flights → single roundtrip
                    df = pd.concat([
                        df, add_entry_table(flights_return, flight_outgoing, returnDateStr)
                    ], ignore_index=True)
                else:
                    for flight_return in flights_return:

                        count_return_flights += 1
                        if count_return_flights > maxFlights:
                            break

                        # For one-way case check price total
                        if not isRoundtrip:
                            total_price = price + flight_return.get('price', 0)
                            if total_price > int(maxPrice):
                                continue

                        df = pd.concat([
                            df, add_entry_table(flight_return, flight_outgoing, returnDateStr)
                        ], ignore_index=True)

                # Write CSV continuously to keep progress saved
                df.to_csv(fileName, index=False)

    return df

if __name__ == "__main__":
    # Example run
    df = run_flight_search(
        departureId="BER",
        arrivalId="BKK",
        departureDateStart="2026-01-05",
        departureDateEnd="2026-02-15",
        minDurationDays=15,
        maxDurationDays=23,
        maxPrice="850",
        adults="1",
        maxDuration=30,
        maxFlights=6,
        isRoundtrip=True
    )

    print("Search complete. Results:")
    print(df)