from datetime import date
from urllib.parse import quote_plus

ORIGIN = "YYZ"
DESTINATION = "JED"


def build_google_flights_link(depart_date: date, return_date: date) -> str:
    query = (
        f"Flights from {ORIGIN} to {DESTINATION} "
        f"departing {depart_date.isoformat()} returning {return_date.isoformat()}"
    )
    return f"https://www.google.com/travel/flights?q={quote_plus(query)}"
