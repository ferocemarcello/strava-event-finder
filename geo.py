import asyncio
import math

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "StravaEventFinder/1.0"}

_sem = asyncio.Semaphore(3)
_geocode_cache: dict[str, tuple[float, float] | None] = {}

# Approximate bounding boxes per country ISO code (min_lat, max_lat, min_lon, max_lon)
_COUNTRY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "no": (57.0, 71.5,  4.0, 31.5),
    "se": (55.0, 69.5, 10.5, 24.5),
    "dk": (54.5, 58.0,  7.5, 15.5),
    "fi": (59.0, 70.5, 19.5, 31.5),
    "it": (36.0, 47.5,  6.5, 18.5),
    "de": (47.0, 55.5,  5.5, 15.5),
    "fr": (42.0, 51.5, -5.5,  8.5),
    "gb": (49.5, 61.5, -8.5,  2.0),
    "es": (35.5, 44.0, -9.5,  4.5),
    "pt": (36.5, 42.5, -9.5, -6.0),
    "nl": (50.5, 53.5,  3.0,  7.5),
    "be": (49.5, 51.5,  2.5,  6.5),
    "ch": (45.5, 48.0,  5.5, 10.5),
    "at": (46.0, 49.0,  9.5, 17.5),
    "gr": (34.5, 42.0, 19.5, 29.0),
    "pl": (49.0, 55.0, 14.0, 24.5),
    "us": (24.0, 49.5,-125.0,-66.5),
    "ca": (41.5, 83.0,-141.0,-52.5),
    "au": (-44.0,-10.0, 112.5,154.0),
    "et": ( 3.0, 15.5, 32.5, 48.5),
    "ke": ( -5.0, 5.5, 33.5, 42.5),
    "za": (-35.0,-22.0, 16.5, 33.0),
    "jp": (24.0, 45.5,122.5,146.0),
    "cn": (15.0, 55.0, 73.5,135.5),
    "br": (-33.5, 5.5,-73.0,-28.5),
}

# Known country name variants → ISO code
_COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "norway": "no", "norge": "no",
    "sweden": "se", "sverige": "se",
    "denmark": "dk", "danmark": "dk",
    "finland": "fi", "suomi": "fi",
    "italy": "it", "italia": "it",
    "germany": "de", "deutschland": "de",
    "france": "fr",
    "united kingdom": "gb", "england": "gb", "scotland": "gb", "wales": "gb",
    "spain": "es", "españa": "es",
    "portugal": "pt",
    "netherlands": "nl", "nederland": "nl",
    "belgium": "be", "belgique": "be", "belgië": "be",
    "switzerland": "ch", "schweiz": "ch", "suisse": "ch", "svizzera": "ch",
    "austria": "at", "österreich": "at",
    "greece": "gr",
    "poland": "pl", "polska": "pl",
    "united states": "us", "usa": "us",
    "canada": "ca",
    "australia": "au",
    "ethiopia": "et",
    "kenya": "ke",
    "south africa": "za",
    "japan": "jp",
    "china": "cn",
    "brazil": "br", "brasil": "br",
}


def country_name_to_code(name: str) -> str | None:
    """Convert a country display name to its ISO-2 code, or None if unknown."""
    return _COUNTRY_NAME_TO_CODE.get(name.strip().lower())


def get_country_codes_in_range(lat: float, lon: float, radius_km: float) -> set[str]:
    """Return ISO codes of all countries whose bounding box overlaps the search circle."""
    buf = radius_km / 111.0  # 1 degree ≈ 111 km (rough)
    result = set()
    for code, (min_lat, max_lat, min_lon, max_lon) in _COUNTRY_BBOX.items():
        if (lat - buf <= max_lat and lat + buf >= min_lat and
                lon - buf <= max_lon and lon + buf >= min_lon):
            result.add(code)
    return result


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
        if query in _geocode_cache:
            return _geocode_cache[query]
        async with httpx.AsyncClient(headers=NOMINATIM_HEADERS) as client:
            resp = await client.get(
                NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
                timeout=8,
            )
            resp.raise_for_status()
            results = resp.json()
            coords = (float(results[0]["lat"]), float(results[0]["lon"])) if results else None
            _geocode_cache[query] = coords
            return coords


def club_query(club: dict) -> str | None:
    """Build a geocode query from club location fields.
    Returns None if location is too coarse (country-only) or empty."""
    city = (club.get("city") or "").strip()
    state = (club.get("state") or "").strip()
    country = (club.get("country") or "").strip()
    if not city and not state:
        return None  # Only country known — can't pinpoint location
    parts = [p for p in (city, state, country) if p]
    return ", ".join(parts)
