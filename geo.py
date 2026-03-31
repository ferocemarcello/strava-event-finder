import asyncio
import math

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "StravaEventFinder/1.0"}

# Allow at most 2 concurrent Nominatim requests to avoid rate-limiting
_sem = asyncio.Semaphore(2)
_geocode_cache: dict[str, tuple[float, float] | None] = {}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in km between two lat/lon points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def geocode(query: str) -> tuple[float, float] | None:
    """Return (lat, lon) for a full place name using Nominatim, or None if not found."""
    if query in _geocode_cache:
        return _geocode_cache[query]
    async with _sem:
        # Check again after acquiring semaphore (another coroutine may have populated it)
        if query in _geocode_cache:
            return _geocode_cache[query]
        async with httpx.AsyncClient(headers=NOMINATIM_HEADERS) as client:
            resp = await client.get(
                NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
                timeout=10,
            )
            resp.raise_for_status()
            results = resp.json()
            coords = (float(results[0]["lat"]), float(results[0]["lon"])) if results else None
            _geocode_cache[query] = coords
            return coords


def club_query(club: dict) -> str:
    """Build a geocode query string from club location fields."""
    parts = [p for p in (club.get("city"), club.get("state"), club.get("country")) if p]
    return ", ".join(parts)
