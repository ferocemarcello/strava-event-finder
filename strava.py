import httpx

STRAVA_API = "https://www.strava.com/api/v3"


async def get_athlete_clubs(access_token: str) -> list[dict]:
    """Return all clubs the authenticated athlete belongs to (handles pagination)."""
    clubs = []
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                f"{STRAVA_API}/athlete/clubs",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"per_page": 100, "page": page},
                timeout=15,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            clubs.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    return clubs


async def get_club_events(access_token: str, club_id: int) -> list[dict]:
    """Return upcoming group events for a club."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STRAVA_API}/clubs/{club_id}/group_events",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json()


async def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    """Exchange an authorization code for tokens."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
