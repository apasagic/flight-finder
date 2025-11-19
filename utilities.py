import http.client
import json
import pandas as pd
from datetime import datetime, timedelta
import requests # Ensure requests is imported
#from IPython.display import display, HTML
import time
import random

# Optional token variable (comment out if not used)
# retTok = "your_token_here"

#########################################
#           pretty_df_print             #
#########################################

def pretty_print(df):
   return display( HTML( df.to_html().replace("\\n","<br>") ) )


#########################################
#             get_request               #
#########################################

def get_request(base_url, endpoint_path, headers, retTok=None, max_retries=5):
    """
    Makes a GET request to the given API endpoint with robust retry and error handling.
    Automatically attaches returningToken if provided.
    """
    url = base_url + endpoint_path

    # Add returningToken only if retTok is defined and not empty
    if retTok:
        if "?" in url:
            url += f"&returningToken={retTok}"
        else:
            url += f"?returningToken={retTok}"

    # Retry loop with exponential backoff
    for attempt in range(1, max_retries + 1):
        try:
            print(f"\nAttempt {attempt}: Requesting {url}")
            response = requests.get(url, headers=headers, timeout=60)
            print("[SUCCESS] Request sent!")

            # Raise for HTTP 4xx / 5xx
            response.raise_for_status()

            # Try to parse JSON safely
            try:
                data = response.json()
            except json.JSONDecodeError:
                print("[WARNING] Response is not valid JSON.")
                data = {}

            # Extract the 'data' key (if it exists)
            prices = data.get("data", [])

            # If no data was found, note it but still return
            if not prices:
                print("[INFO] No data found in response.")

            # Optional delay (helps avoid API throttling)
            time.sleep(random.uniform(0.3, 0.8))
            return prices

        except requests.exceptions.Timeout:
            print(f"[TIMEOUT] Timeout on attempt {attempt}. Retrying after short delay...")
        except requests.exceptions.HTTPError as e:
            code = response.status_code if 'response' in locals() else 'N/A'
            msg = str(e)
            print(f"[ERROR] HTTP {code} error: {msg}")

            # Handle common RapidAPI issues
            if code == 429 or "Invalid API key" in msg:
                wait_time = 5 * attempt
                print(f"[WARNING] Rate limit or temp block. Waiting {wait_time}s before retrying...")
                time.sleep(wait_time)
            elif code >= 500:
                # Server-side issue — retry after delay
                time.sleep(3)
            else:
                # Likely a client-side or permanent error
                print("[STOP] Permanent error (won't retry).")
                break
        except requests.exceptions.RequestException as e:
            print(f"[WARNING] General request error: {e}")
        except Exception as e:
            print(f"[WARNING] Unexpected error: {e}")

        # Wait before next retry (exponential backoff)
        wait = min(10, 2 ** attempt + random.random())
        print(f"[RETRY] Waiting {wait:.1f}s before retry...")
        time.sleep(wait)

    print("[FAILED] All retries failed or exhausted.")
    return []


#########################################
#          get_outgoing_flight          #
#########################################

def get_outgoing_flight(departureId, arrivalId, departureDate, returnDate, flightDuration, maxPrice, base_url_google_flights, headers):
   # conn = http.client.HTTPSConnection("google-flights4.p.rapidapi.com") # No longer needed with requests

   arrivalDate = datetime.strptime(departureDate, "%Y-%m-%d") + timedelta(days=1)
   datestr = arrivalDate.strftime("%Y-%m-%d")
   req_path = f"/flights/search-roundtrip?departureId={departureId}&arrivalId={arrivalId}&departureDate={departureDate}&arrivalDate={returnDate}"
   req_path += f"&currency=EUR&sort=2&flightDuration={flightDuration}&maxPrice={maxPrice}"
   #req_path = f"/flights/search-one-way?departureId={departureId}&arrivalId={arrivalID}&departureDate={departureDate}&arrivalDate={arrivalDate.strftime("%Y-%m-%d")}"

   # Call the updated get_request function
   prices = get_request(base_url_google_flights, req_path, headers)

   return prices


#########################################
#            Print_dict                 #
#########################################

def print_dict(data, indent=0, lim=0):
    """Recursively print all keys and values in a dictionary with indentation."""
    spacing = "  " * indent
    count = 0
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                print(f"{spacing}{key}:")
                print_dict(value, indent + 1)
                if(lim==count):
                  break
                count+=1
            else:
                print(f"{spacing}{key}: {value}")
    elif isinstance(data, list):
        for i, item in enumerate(data, start=1):
            print(f"{spacing}[{i}]")
            print_dict(item, indent + 1)
            if(lim==count):
              break
            count+=1
    else:
        print(f"{spacing}{data}")


#########################################
#            find_returns               #
#########################################

def find_returns(data_outgoing, base_url, headers, params, retTok=None):

  # These variables are used in the loop, ensure they are properly extracted
  # from the 'data_outgoing' dictionary which represents a single outgoing flight.
  # Based on the structure of `flights_outgoing[0]`, it should contain these keys.
  # Example structure of flights_outgoing[0]:
  # {'price': 581, 'returningToken': '...', 'airlineCode': '6E', 'segments': [...], 'departureDate': '2025-11-10', 'duration': 1035, 'stops': 1}

  # Check if 'segments' key exists and handle it gracefully
  num_flights = len(data_outgoing.get('segments', [])) # Use .get() to avoid KeyError if not present
  stops = data_outgoing.get('stops', 0)
  price = data_outgoing.get('price', 0)
  duration = data_outgoing.get('duration', 0)
  returning_token = data_outgoing.get('returningToken') # This is crucial for the API call
  departureDate = data_outgoing.get('departureDate')

  if not returning_token or not departureDate:
      print("Error: Missing 'returningToken' or 'departureDate' in flight data.")
      return []

  adults = params['adults']
  maxPrice = params['maxPrice']
  maxDuration = params['maxDuration']
  maxReturnDate = datetime.strptime(params['maxReturnDate'], "%Y-%m-%d")
  minDurationDays = params['minDurationDays']
  maxDurationDays = params['maxDurationDays']

  # Convert string → datetime object
  dt_outgoing = datetime.strptime(departureDate, "%Y-%m-%d")

  # Add min duration stay
  dt_return_min = dt_outgoing + timedelta(days=minDurationDays)

  # Convert back to same string format
  return_date_min = dt_return_min.strftime("%Y-%m-%d")

  i = 0

  df = pd.DataFrame([])
  match_found = 0

  while(1):

    date = dt_return_min + timedelta(days=i)
    maxReturnDate = dt_outgoing + timedelta(days=maxDurationDays)

    if(date >= maxReturnDate):
      break

    datestr = date.strftime("%Y-%m-%d")

    # Construct the endpoint path for the return flight search
    request_path = f"/flights/roundtrip-returning?arrivalDate={datestr}&adults={adults}&stops=0&maxPrice={maxPrice}&flightDuration={maxDuration}"
    #request_path = f"/flights/roundtrip-returning?arrivalDate={date.strftime("%Y-%m-%d")}"

    # Call the modified get_request function with the base_url and the extracted returning_token
    data_ret = get_request(base_url, request_path, headers, retTok=returning_token)
    print(date.strftime("%Y-%m-%d"))

    i += 1

    if data_ret['topFlights']:
      data = data_ret['topFlights']
      print("found return flights!")
      match_found += 1
    elif data_ret['otherFlights']:
      data = data_ret['otherFlights']
      match_found += 1
      print("found return flights!")
    else:
      continue

    for flight in data:
       df = add_entry_table(df,flight,data_outgoing)

  return df

#########################################
#            add_entry_table            # 
#########################################

def add_entry_table(flight, data_outgoing,returnDateStr):
   
   flightNo = f""
   flightID = f""
   arrivalAirportCode = f""
   arrivalTime = f""
   airline =  f""
   
   departureDate_outgoing = data_outgoing['departureDate']
   departureTime_outgoing = data_outgoing['departureTime']
   duration_outgoing = data_outgoing['duration']
   price_outgoing = data_outgoing['price']
   airline_outgoing = data_outgoing['airline'][0]['airlineName']
   flightID_outgoing = data_outgoing['segments'][0]['flightId']
   flightCode_outgoing = data_outgoing['segments'][0]['airline']['airlineCode']+data_outgoing['segments'][0]['airline']['flightNumber']

   if(flight == []):

    row = { "Price" : price_outgoing,
            "Departure Date Outgoing": departureDate_outgoing,
            "Departure Time Outgoing": departureTime_outgoing,
            "Airline Outgoing" : airline_outgoing,
            "Flight ID Outgoing" : flightID_outgoing,
            "Flight No Outgoing:" : flightCode_outgoing,
            "Duration Mins." : duration_outgoing,
            "Duration" : f"{int(duration_outgoing) // 60}h {int(duration_outgoing) % 60}m",
            "Stops" : "",
            "Departure Time Return": returnDateStr,
            "Arrival Time Return": "",
            "Flight ID" : "",
            "Flight No:" : "",
            "Airline" : "",
            "Arrival Airport Code" : "",
            "Arrival Time" : ""
         }

   else:
        
    for segment in flight['segments']:
       arrivalAirportCode += segment['arrivalAirportCode'] + "\n"
       arrivalTime += segment['arrivalTime'] + "\n"
       flightNo += segment['airline']['airlineCode'] + segment['airline']['flightNumber']+"\n"
       flightID += str(segment['flightId']) + "\n"
       airline += segment['airline']['airlineName'] + "\n"

    row = { "Price" : flight['price'],
            "Departure Date Outgoing": departureDate_outgoing,
            "Departure Time Outgoing": departureTime_outgoing,
            "Airline Outgoing" : airline_outgoing,
            "Flight ID Outgoing" : flightID_outgoing,
            "Flight No Outgoing:" : flightCode_outgoing,
            "Duration Mins." : flight['duration'],
            "Duration" : f"{int(flight['duration']) // 60}h {int(flight['duration']) % 60}m",
            "Stops" : flight['stops'],
            "Departure Time Return": flight['departureDate'] + " " + flight['departureTime'],
            "Arrival Time Return": flight['arrivalDate'] + " " +  flight['arrivalTime'],
            "Flight ID" : flightID,
            "Flight No:" : flightNo,
            "Airline" : airline,
            "Arrival Airport Code" : arrivalAirportCode,
            "Arrival Time" : arrivalTime
         }
    
   # Add a single row using the append() method
   df = pd.DataFrame([row])
       
   return df