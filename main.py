import http.client
import json
import pandas as pd
from datetime import datetime, timedelta
import requests
from utilities import get_request, pretty_print, get_outgoing_flight, find_returns, print_dict, add_entry_table

# Load configuration from JSON file
def load_config(config_file='config.json'):
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {config_file} not found. Please copy config.example.json to config.json and add your API keys.")
        exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {config_file}")
        exit(1)

# Load API configuration
config = load_config()
api_config = config['api']

### Consider also making a params structs
departureDateStart = "2025-12-18"
departureDateEnd = "2026-01-25"
departureId = "VIE"
arrivalId =  "DMK"
maxPrice = "850"
flightDuration = "16h00"

# How many cheapest flights to consider for each day
maxFlights = 7;


# Define parameters in a dictionary to be passed around functions
params = {
  "adults" : "1",
  "maxPrice" : "850",
  "maxDuration" : "14h00",
  "maxReturnDate" : "2026-01-15",
  "minDurationDays" : 15,
  "maxDurationDays" : 23
}

# Extract parameters from the params dictionary, no longer used in the function
# change later to have only one type definition
adults = params['adults']
maxPrice = params['maxPrice']
maxDuration = params['maxDuration']
#maxReturnDate = datetime.strptime(params['maxReturnDate'], "%Y-%m-%d")
minDurationDays = params['minDurationDays']
maxDurationDays = params['maxDurationDays']


base_url_google_flights = api_config['base_url']
headers = api_config['headers']

### The section above requries tidying up ###

df  = pd.DataFrame()

count_departure_day = 1

# itterate over a range of departure days (starting from the earliest day)
while(1):

  # Calculate departure date - add i days, convert back to string
  departureDate = datetime.strptime(departureDateStart, "%Y-%m-%d") + timedelta(days=count_departure_day)

  # If later then latest departure date - break
  if(departureDate>=datetime.strptime(departureDateEnd, "%Y-%m-%d")):
    break

  # Convert departure date to a string
  departureDateStr = (departureDate).strftime("%Y-%m-%d")

  #increment a counter  
  count_departure_day += 1

  # Add min duration stay to calculate earliest return date
  dt_return_min = departureDate + timedelta(days=minDurationDays)

  # Initialize return date itterator
  count_return_day = 0

  # Calculate latest return date by adding max duration days to departure date
  maxReturnDate = departureDate + timedelta(days=maxDurationDays)
  
  # itterate over a range of return days (starting from the earliest return day)
  while(1):

    # Calculate return date - add i days, convert back to string
    returnDate = dt_return_min + timedelta(days=count_return_day)

    # Increment counter
    count_return_day += 1

    # If later then latest return date - break
    if(returnDate >= maxReturnDate):
      break

    # Convert return date to a string
    returnDateStr = returnDate.strftime("%Y-%m-%d")
    
    print(f"Searching for flights departing on {departureDateStr} and returning on {returnDateStr}...")

    # Get a sorted, filtered list of available outgoing flights for departureDate
    flights = get_outgoing_flight(departureId, arrivalId, departureDateStr,  returnDateStr, flightDuration, maxPrice, base_url_google_flights, headers)

    if(not(flights['topFlights']==[]) or not(flights['otherFlights']==[])):
      # Sum up both categories
      flights_outgoing = flights['topFlights'] + flights['otherFlights']
    else:
      flights_outgoing = []

    # Initialize a counter for the number of outgoing flights considered
    count_flights_outgoing = 0

    # For each outgoing flight found
    for flight_outgoing in flights_outgoing:

      # Extract data for the first flight option
      # Check if 'segments' key exists and handle it gracefully
      num_flights = len(flight_outgoing.get('segments', [])) # Use .get() to avoid KeyError if not present
      stops = flight_outgoing.get('stops', 0)
      price = flight_outgoing.get('price', 0)
      duration = flight_outgoing.get('duration', 0)
      returning_token = flight_outgoing.get('returningToken') # This is crucial for the API call
      departureDate = flight_outgoing.get('departureDate')
    
      # Consider only first 5
      count_flights_outgoing += 1

      # If we have reached the max number of flights to consider - break, otherwise...
      if(count_flights_outgoing >= maxFlights):
        break

      # Construct the endpoint path for the return flight search
      request_path = f"/flights/roundtrip-returning?arrivalDate={returnDateStr}&adults={adults}&stops=0&maxPrice={maxPrice}&flightDuration={maxDuration}"
      #request_path = f"/flights/roundtrip-returning?arrivalDate={date.strftime("%Y-%m-%d")}"

      # Call the modified get_request function with the base_url and the extracted returning_token
      data_ret = get_request(base_url_google_flights, request_path, headers, retTok=returning_token)
      #print(date.strftime("%Y-%m-%d"))

      #if data_ret['topFlights']:
      #  flights_return = data_ret['topFlights']
      #  print("found return flights!")
      #elif data_ret['otherFlights']:
      #  flights_return = data_ret['otherFlights']
      #  print("found return flights!")
      #else:
      #  flights_return = []

      flights_return = data_ret['topFlights'] + data_ret['otherFlights']

      if(flights_return==[]):
        df = pd.concat([df, add_entry_table(flights_return,flight_outgoing,returnDateStr)], ignore_index=True)
      else:
       for flight_return in flights_return:
         df = pd.concat([df, add_entry_table(flights_return,flight_outgoing,returnDateStr)], ignore_index=True)

      df.to_csv(f"flights_{departureId}_{arrivalId}.csv", index=False)