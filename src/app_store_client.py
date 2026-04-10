"""
Apple App Store client using the free iTunes Search API + RSS review feeds.
No API key required. Uses only Python stdlib (urllib) — no extra installs needed.
"""

import asyncio
import json
import urllib.request
import urllib.parse
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class AppInfo:
    app_id: str
    name: str
    developer: str
    description: str
    rating: float
    rating_count: int
    price: str
    category: str
    url: str
    icon_url: str
    version: str
    reviews: list = field(default_factory=list)


@dataclass
class Review:
    app_id: str
    app_name: str
    rating: int
    title: str
    body: str
    author: str
    version: str
    date: str


ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_REVIEWS_URL = "https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _http_get(url: str, params: dict = None) -> Optional[dict]:
    """Synchronous HTTP GET using stdlib urllib."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [error] {e} — {url[:80]}")
        return None


class AppStoreClient:
    def __init__(self, country: str = "us", delay: float = 0.5):
        self.country = country
        self.delay = delay  # polite rate limiting

    async def search_apps(self, keyword: str, limit: int = 10) -> list[AppInfo]:
        """Search App Store for apps matching a keyword."""
        params = {
            "term": keyword,
            "country": self.country,
            "media": "software",
            "entity": "software",
            "limit": limit,
        }
        data = await asyncio.to_thread(_http_get, ITUNES_SEARCH_URL, params)
        await asyncio.sleep(self.delay)

        if not data or "results" not in data:
            return []

        apps = []
        for r in data["results"]:
            apps.append(AppInfo(
                app_id=str(r.get("trackId", "")),
                name=r.get("trackName", ""),
                developer=r.get("artistName", ""),
                description=r.get("description", ""),
                rating=r.get("averageUserRating", 0),
                rating_count=r.get("userRatingCount", 0),
                price="Free" if r.get("price", 0) == 0 else f"${r.get('price', 0):.2f}",
                category=r.get("primaryGenreName", ""),
                url=r.get("trackViewUrl", ""),
                icon_url=r.get("artworkUrl100", ""),
                version=r.get("version", ""),
            ))
        return apps

    async def fetch_reviews(self, app: AppInfo, max_pages: int = 5) -> list[Review]:
        """Fetch up to max_pages * 50 reviews (Apple caps at 10 pages = 500 reviews)."""
        reviews = []
        for page in range(1, min(max_pages + 1, 11)):
            url = ITUNES_REVIEWS_URL.format(
                country=self.country, page=page, app_id=app.app_id
            )
            data = await asyncio.to_thread(_http_get, url)
            await asyncio.sleep(self.delay)

            if not data:
                break

            entries = data.get("feed", {}).get("entry", [])
            if not entries:
                break

            for entry in entries:
                if "im:rating" not in entry:
                    continue  # skip non-review entries (first entry is app metadata)
                try:
                    reviews.append(Review(
                        app_id=app.app_id,
                        app_name=app.name,
                        rating=int(entry.get("im:rating", {}).get("label", 0)),
                        title=entry.get("title", {}).get("label", ""),
                        body=entry.get("content", {}).get("label", ""),
                        author=entry.get("author", {}).get("name", {}).get("label", ""),
                        version=entry.get("im:version", {}).get("label", ""),
                        date=entry.get("updated", {}).get("label", "")[:10],
                    ))
                except Exception:
                    continue

            if len(entries) < 51:  # fewer than a full page → last page
                break

        return reviews
