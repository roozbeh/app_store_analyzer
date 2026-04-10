"""
Uses the Anthropic API to analyze App Store reviews and extract:
  1. Praised features (what users love)
  2. Requested missing features / pain points
  3. Overall competitive intelligence summary
"""

import asyncio
import json
import os
import urllib.request
from dataclasses import dataclass, field


@dataclass
class AppAnalysis:
    app_id: str
    app_name: str
    developer: str
    rating: float
    rating_count: int
    price: str
    category: str
    url: str
    icon_url: str
    review_count_analyzed: int
    praised_features: list = field(default_factory=list)
    missing_features: list = field(default_factory=list)
    sentiment_summary: str = ""
    competitive_notes: str = ""
    # Market size estimates
    estimated_downloads: int = 0
    estimated_mau: int = 0
    revenue_low: float = 0.0
    revenue_mid: float = 0.0
    revenue_high: float = 0.0
    monetization_note: str = ""


# Annual ARPU (USD) by App Store category: (low, mid, high)
# Sources: Sensor Tower / AppAnnie industry benchmarks
_CATEGORY_ARPU = {
    "Finance":           (3.0,  10.0, 25.0),
    "Business":          (2.0,   6.0, 18.0),
    "Productivity":      (2.0,   5.0, 12.0),
    "Health & Fitness":  (2.0,   6.0, 15.0),
    "Medical":           (3.0,   8.0, 20.0),
    "Education":         (1.5,   4.0, 10.0),
    "Navigation":        (1.0,   3.0,  8.0),
    "Travel":            (1.0,   3.0,  8.0),
    "Lifestyle":         (0.5,   2.0,  5.0),
    "Real Estate":       (0.5,   2.0,  6.0),
    "Shopping":          (0.5,   1.5,  4.0),
    "Entertainment":     (1.0,   3.0,  8.0),
    "Social Networking": (1.0,   3.0,  7.0),
    "Games":             (1.0,   3.5,  8.0),
    "default":           (0.5,   2.0,  5.0),
}


def estimate_market_metrics(rating_count: int, category: str, price: str) -> dict:
    """
    Estimate downloads, MAU, and annual revenue range from App Store rating count.

    Rules of thumb:
    - ~1% of users leave a rating  →  downloads ≈ rating_count × 100
    - ~25% of downloaders are monthly active  →  MAU ≈ downloads × 0.25
    - Revenue = MAU × annual ARPU (varies by category & monetization model)
    - Paid apps: also factor in upfront price (assumed ~40% of downloads still paying)
    """
    estimated_downloads = rating_count * 100
    estimated_mau = int(estimated_downloads * 0.25)

    arpu_low, arpu_mid, arpu_high = _CATEGORY_ARPU.get(category, _CATEGORY_ARPU["default"])

    is_paid = price not in ("Free", "$0.00", "")
    if is_paid:
        try:
            unit_price = float(price.replace("$", ""))
        except ValueError:
            unit_price = 0.0
        paid_revenue = estimated_downloads * unit_price * 0.4  # ~40% convert
        revenue_low  = paid_revenue + estimated_mau * arpu_low
        revenue_mid  = paid_revenue + estimated_mau * arpu_mid
        revenue_high = paid_revenue + estimated_mau * arpu_high
        monetization_note = f"Paid app ({price} upfront) + in-app purchases/subscriptions."
    else:
        revenue_low  = estimated_mau * arpu_low
        revenue_mid  = estimated_mau * arpu_mid
        revenue_high = estimated_mau * arpu_high
        monetization_note = (
            "Free app — revenue typically from ads, lead generation, or subscriptions. "
            "Estimates assume blended ARPU for the category."
        )

    return {
        "estimated_downloads": estimated_downloads,
        "estimated_mau": estimated_mau,
        "revenue_low": revenue_low,
        "revenue_mid": revenue_mid,
        "revenue_high": revenue_high,
        "monetization_note": monetization_note,
    }


CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-6"


def _call_claude(prompt: str, max_tokens: int = 1000) -> str:
    """Synchronous call to the Anthropic API using urllib."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        CLAUDE_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]
            return text.strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Claude API error {e.code}: {body}") from e
    except Exception as e:
        raise RuntimeError(f"Claude API call failed: {e}") from e


async def analyze_reviews_with_claude(
    app_name: str,
    app_id: str,
    reviews: list,
    max_reviews_to_send: int = 80,
) -> dict:
    """
    Send a batch of reviews to Claude and ask for feature analysis.
    Returns: {praised_features, missing_features, sentiment_summary, competitive_notes}
    """
    if not reviews:
        return {
            "praised_features": [],
            "missing_features": [],
            "sentiment_summary": "No reviews available for analysis.",
            "competitive_notes": "",
        }

    review_texts = []
    for r in reviews[:max_reviews_to_send]:
        stars = "⭐" * r.rating
        review_texts.append(f"[{stars} — {r.title}]\n{r.body}")

    reviews_block = "\n\n---\n\n".join(review_texts)

    prompt = f"""You are a product analyst. Below are App Store reviews for "{app_name}".

Analyze these reviews and return a JSON object (no markdown fences, no preamble) with exactly these keys:
{{
  "praised_features": ["list of specific features or aspects users praise"],
  "missing_features": ["list of features users explicitly request or complain are missing"],
  "sentiment_summary": "2-3 sentence overall sentiment summary",
  "competitive_notes": "1-2 sentence note on what makes this app stand out or what unique angle it has"
}}

Be specific — extract actual feature names, not vague generalities.

REVIEWS:
{reviews_block}"""

    text = await asyncio.to_thread(_call_claude, prompt, 1000)

    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        return {
            "praised_features": [],
            "missing_features": [],
            "sentiment_summary": f"Could not parse analysis.",
            "competitive_notes": "",
        }


async def generate_competitive_report(keyword: str, analyses: list) -> str:
    """Synthesize all individual app analyses into a final competitive report."""
    if not analyses:
        return "No apps were analyzed."

    apps_summary = [
        {
            "name": a.app_name,
            "developer": a.developer,
            "rating": a.rating,
            "price": a.price,
            "praised_features": a.praised_features,
            "missing_features": a.missing_features,
            "sentiment_summary": a.sentiment_summary,
            "competitive_notes": a.competitive_notes,
        }
        for a in analyses
    ]

    prompt = f"""You are a senior product strategist helping a team building an app in the "{keyword}" space.

Below is competitive intelligence from real App Store reviews across {len(analyses)} competing apps.

DATA:
{json.dumps(apps_summary, indent=2)}

Write a concise Competitive Intelligence Report with these sections:
1. **Top Valued Features** — what do users love most across all competitors?
2. **Common Pain Points & Gaps** — what are users consistently missing or complaining about?
3. **Differentiation Opportunities** — what could a new or improved app do to stand out?
4. **Quick Wins** — 3-5 specific, actionable feature ideas to prioritize.

Keep it sharp and actionable. Use bullet points inside each section."""

    return await asyncio.to_thread(_call_claude, prompt, 1500)
