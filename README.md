# Strava Event Finder

Browse upcoming events from your Strava clubs, filtered by location and distance.

## Features

- Authenticate with your Strava account via OAuth 2.0
- View group events from all clubs you're a member of
- Filter events by proximity to a location (geocoded via Nominatim)

## Stack

- **Backend**: Python FastAPI + uvicorn
- **Frontend**: Plain HTML / Vanilla JS
- **Auth**: Strava OAuth 2.0, session stored in signed cookies (itsdangerous)
- **Geocoding**: OpenStreetMap Nominatim

## Prerequisites

- Python 3.9+
- A [Strava API application](https://www.strava.com/settings/api)

## Setup

1. Clone the repo and install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your Strava credentials:

   ```bash
   cp .env.example .env
   ```

   | Variable | Description |
   |---|---|
   | `STRAVA_CLIENT_ID` | Your Strava app Client ID |
   | `STRAVA_CLIENT_SECRET` | Your Strava app Client Secret |
   | `STRAVA_REDIRECT_URI` | Must match the callback URL in your Strava app settings |
   | `SECRET_KEY` | Random secret string for signing session cookies |

3. In your Strava app settings, set the **Authorization Callback Domain** to `localhost`.

4. Run the server:

   ```bash
   uvicorn main:app --reload
   ```

5. Open [http://localhost:8000](http://localhost:8000) in your browser.

## Strava API Notes

- Events are fetched only from clubs the authenticated user belongs to — there is no geographic club search in the Strava API.
- Rate limits: 100 requests / 15 min, 1 000 requests / day (per user token).

## License

See [LICENSE](LICENSE).
