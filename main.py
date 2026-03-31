import asyncio
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeSerializer

from geo import club_query, country_name_to_code, geocode, get_country_codes_in_range, haversine
from strava import exchange_code, get_athlete_clubs, get_club_events

load_dotenv()

CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REDIRECT_URI = os.environ["STRAVA_REDIRECT_URI"]
SECRET_KEY = os.environ["SECRET_KEY"]

app = FastAPI()
signer = URLSafeSerializer(SECRET_KEY, salt="session")

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"


def _make_session(data: dict) -> str:
    return signer.dumps(data)


def _read_session(cookie: str | None) -> dict | None:
    if not cookie:
        return None
    try:
        return signer.loads(cookie)
    except BadSignature:
        return None


@app.get("/auth/login")
def login():
    params = urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "read,activity:read",
        "approval_prompt": "auto",
    })
    return RedirectResponse(f"{STRAVA_AUTH_URL}?{params}")


@app.get("/auth/callback")
async def callback(code: str = Query(...), error: str = Query(None)):
    if error:
        return RedirectResponse("/?error=access_denied")
    try:
        data = await exchange_code(CLIENT_ID, CLIENT_SECRET, code)
    except httpx.HTTPError:
        return RedirectResponse("/?error=token_exchange_failed")

    athlete = data.get("athlete", {})
    session_data = {
        "access_token": data["access_token"],
        "athlete_name": f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip(),
    }
    response = RedirectResponse("/")
    response.set_cookie("session", _make_session(session_data), httponly=True, samesite="lax")
    return response


@app.get("/auth/logout")
def logout():
    response = RedirectResponse("/")
    response.delete_cookie("session")
    return response


@app.get("/api/me")
def me(session: str | None = Cookie(default=None)):
    data = _read_session(session)
    if data:
        return {"authenticated": True, "athlete_name": data["athlete_name"]}
    return {"authenticated": False}


@app.get("/api/geocode")
async def geocode_proxy(q: str = Query(...)):
    try:
        coords = await geocode(q)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Geocoding service error: {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Geocoding service unreachable: {e}")
    if coords is None:
        raise HTTPException(status_code=404, detail=f"Location not found: {q!r}")
    return {"lat": coords[0], "lon": coords[1]}


@app.get("/api/clubs")
async def list_clubs(session: str | None = Cookie(default=None)):
    """Diagnostic: return all member clubs with their raw location data from Strava."""
    data = _read_session(session)
    if not data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    clubs = await get_athlete_clubs(data["access_token"])
    return [
        {
            "id": club.get("id"),
            "name": club.get("name"),
            "city": club.get("city"),
            "state": club.get("state"),
            "country": club.get("country"),
        }
        for club in clubs
    ]


@app.get("/api/events")
async def events(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(25),
    session: str | None = Cookie(default=None),
):
    data = _read_session(session)
    if not data:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = data["access_token"]
    clubs = await get_athlete_clubs(token)

    # Determine which countries overlap with the search circle (no API call needed)
    relevant_codes = get_country_codes_in_range(lat, lon, radius_km)

    # Split clubs into:
    #   geocodable  — have city/state, and country is in range (or unknown)
    #   country_only — only country known, country is in range → include without distance filter
    #   skip        — country is clearly outside range
    geocodable: list[dict] = []
    country_only: list[dict] = []

    for club in clubs:
        club_country = (club.get("country") or "").strip()
        club_code = country_name_to_code(club_country) if club_country else None

        # If we know the club's country and it's not in range, skip it
        if club_code and relevant_codes and club_code not in relevant_codes:
            continue

        q = club_query(club)
        if q:
            geocodable.append(club)
        elif club_country:
            # Country known and in range, but no city — include without distance filter
            country_only.append(club)
        # If completely empty location, skip

    # Geocode only the candidates (dramatically fewer than all clubs)
    unique_queries: dict[str, tuple[float, float] | None] = {}
    geocode_tasks: dict[str, object] = {}
    for club in geocodable:
        q = club_query(club)
        if q and q not in geocode_tasks and q not in unique_queries:
            geocode_tasks[q] = geocode(q)

    if geocode_tasks:
        results = await asyncio.gather(*geocode_tasks.values(), return_exceptions=True)
        for key, result in zip(geocode_tasks.keys(), results):
            unique_queries[key] = result if isinstance(result, tuple) else None

    # Build list of (club, distance_km) to fetch events for
    nearby_clubs: list[tuple[dict, float]] = []

    for club in geocodable:
        q = club_query(club)
        coords = unique_queries.get(q)
        if coords:
            dist = haversine(lat, lon, coords[0], coords[1])
            if dist <= radius_km:
                nearby_clubs.append((club, dist))

    for club in country_only:
        nearby_clubs.append((club, 0.0))  # distance unknown, assume local

    # Fetch events for nearby clubs concurrently
    event_tasks = [get_club_events(token, club["id"]) for club, _ in nearby_clubs]
    club_event_lists = await asyncio.gather(*event_tasks, return_exceptions=True)

    now = datetime.now(timezone.utc)
    all_events = []
    for (club, dist), club_events in zip(nearby_clubs, club_event_lists):
        if isinstance(club_events, Exception):
            continue
        for ev in club_events:
            start_date = ev.get("start_date")
            if start_date:
                try:
                    ev_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                    if ev_dt < now:
                        continue
                except ValueError:
                    pass

            all_events.append({
                "id": ev.get("id"),
                "title": ev.get("title"),
                "description": ev.get("description", ""),
                "start_date": start_date,
                "address": ev.get("address"),
                "activity_type": ev.get("activity_type", ""),
                "distance_meters": ev.get("distance") or 0,
                "club_name": club.get("name"),
                "club_id": club.get("id"),
                "club_city": club.get("city"),
                "club_distance_km": round(dist, 1) if dist > 0 else None,
                "url": f"https://www.strava.com/clubs/{club.get('id')}/group_events/{ev.get('id')}",
            })

    all_events.sort(key=lambda e: e.get("start_date") or "")
    return all_events


app.mount("/", StaticFiles(directory="static", html=True), name="static")
