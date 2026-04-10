"""
Flask API for the App Store Analyzer.

Endpoints:
  GET  /api/health                     — health check (public)
  POST /api/auth/apple                 — verify Apple identity token, return JWT
  GET  /api/researches                 — list all researches, newest first (public)
  GET  /api/researches/<id>            — full research with apps array
  GET  /api/researches/<id>/status     — lightweight status poll
  POST /api/researches                 — start new research (requires Bearer JWT)
"""

import asyncio
import base64
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
import requests
from bson import ObjectId
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from flask import Flask, jsonify, request, Response
from pymongo import MongoClient, DESCENDING

# ─── Configuration ────────────────────────────────────────────────────────────

MONGO_URI = os.environ.get("MONGO_URI", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-this-secret")
APPLE_BUNDLE_ID = os.environ.get("APPLE_BUNDLE_ID", "com.ipronto.appstoreanalyzer")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PORT = int(os.environ.get("PORT", 5001))
# DEV_MODE=true accepts a hardcoded simulator token — never enable in production
DEV_MODE = os.environ.get("DEV_MODE", "false").lower() == "true"

# ─── Flask & MongoDB setup ────────────────────────────────────────────────────

app = Flask(__name__)

_mongo_client = None
_db = None


def get_db():
    global _mongo_client, _db
    if _db is None:
        _mongo_client = MongoClient(MONGO_URI, connect=False, maxPoolSize=10)
        try:
            _db = _mongo_client.get_default_database()
        except Exception:
            _db = _mongo_client["app_store_analyzer"]
    return _db


def researches_col():
    return get_db()["researches"]


# ─── Apple Sign In ────────────────────────────────────────────────────────────

_apple_keys_cache: dict = {"keys": None, "fetched_at": 0.0}


def _get_apple_public_keys() -> list:
    import time
    now = time.time()
    if _apple_keys_cache["keys"] and now - _apple_keys_cache["fetched_at"] < 3600:
        return _apple_keys_cache["keys"]
    resp = requests.get("https://appleid.apple.com/auth/keys", timeout=10)
    resp.raise_for_status()
    _apple_keys_cache["keys"] = resp.json()["keys"]
    _apple_keys_cache["fetched_at"] = now
    return _apple_keys_cache["keys"]


def _b64url_to_int(b64: str) -> int:
    padded = b64 + "=" * (4 - len(b64) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


def _verify_apple_token(identity_token: str) -> dict:
    """Verify Apple Sign In identity token. Returns the JWT claims on success."""
    header = jwt.get_unverified_header(identity_token)
    kid = header.get("kid")

    apple_keys = _get_apple_public_keys()
    key_data = next((k for k in apple_keys if k["kid"] == kid), None)
    if not key_data:
        raise ValueError(f"Apple public key '{kid}' not found")

    pub_numbers = RSAPublicNumbers(_b64url_to_int(key_data["e"]), _b64url_to_int(key_data["n"]))
    public_key = pub_numbers.public_key(default_backend())

    claims = jwt.decode(
        identity_token,
        public_key,
        algorithms=["RS256"],
        audience=APPLE_BUNDLE_ID,
        issuer="https://appleid.apple.com",
    )
    return claims


# ─── App JWT helpers ──────────────────────────────────────────────────────────

def _make_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token = auth_header[7:]
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            request.user_id = payload["sub"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Serialization ────────────────────────────────────────────────────────────

def _serialize(doc: dict) -> dict:
    """Convert MongoDB document to JSON-safe dict."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    for key in ("created_at", "completed_at"):
        if isinstance(doc.get(key), datetime):
            doc[key] = doc[key].isoformat()
    return doc


# ─── Web pages ────────────────────────────────────────────────────────────────

_SHARED_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f5f7; color: #1d1d1f; line-height: 1.6; }
  header { background: #fff; border-bottom: 1px solid #e0e0e5; padding: 18px 24px;
           display: flex; align-items: center; gap: 14px; }
  header h1 { font-size: 1.15rem; font-weight: 700; }
  header span { font-size: .85rem; color: #6e6e73; }
  .container { max-width: 760px; margin: 40px auto; padding: 0 24px 60px; }
  h2 { font-size: 1.5rem; font-weight: 700; margin-bottom: 10px; }
  h3 { font-size: 1rem; font-weight: 600; margin: 22px 0 6px; }
  p  { color: #3a3a3c; margin-bottom: 12px; }
  .hero { background: linear-gradient(135deg, #0071e3 0%, #34aadc 100%);
          color: #fff; border-radius: 18px; padding: 40px 36px; margin-bottom: 36px; }
  .hero p { color: rgba(255,255,255,.85); font-size: 1.05rem; margin-top: 10px; }
  .card { background: #fff; border-radius: 14px; padding: 24px 28px;
          margin-bottom: 18px; box-shadow: 0 1px 4px rgba(0,0,0,.07); }
  .badge { display: inline-block; background: #0071e3; color: #fff;
           border-radius: 6px; padding: 2px 10px; font-size: .78rem;
           font-weight: 600; margin-bottom: 8px; }
  ul { padding-left: 20px; color: #3a3a3c; }
  li { margin-bottom: 6px; }
  a  { color: #0071e3; text-decoration: none; }
  a:hover { text-decoration: underline; }
  footer { text-align: center; font-size: .8rem; color: #6e6e73; margin-top: 40px; }
"""

@app.route("/")
def marketing_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>App Store Analyzer — AI Market Research</title>
  <style>{_SHARED_CSS}
    .features {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    @media(max-width:560px) {{ .features {{ grid-template-columns: 1fr; }} }}
    .feature {{ background:#fff; border-radius:14px; padding:20px 22px;
                box-shadow:0 1px 4px rgba(0,0,0,.07); }}
    .feature .icon {{ font-size:1.6rem; margin-bottom:8px; }}
    .feature h3 {{ margin:0 0 4px; font-size:.95rem; }}
    .feature p {{ font-size:.85rem; color:#6e6e73; margin:0; }}
    .cta {{ display:inline-block; background:#0071e3; color:#fff; padding:14px 28px;
            border-radius:10px; font-weight:600; font-size:1rem; margin-top:8px; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>App Store Analyzer</h1>
      <span>AI-Powered Competitive Intelligence</span>
    </div>
  </header>
  <div class="container">
    <div class="hero">
      <h2>Know your market before you build.</h2>
      <p>Enter a keyword. Get instant AI analysis of real App Store reviews across your competition — top features users love, pain points they hate, and the gaps nobody has filled yet.</p>
      <a class="cta" href="https://apps.apple.com/app/id6745741527">Download on the App Store</a>
    </div>

    <h2>What you get</h2>
    <div class="features">
      <div class="feature"><div class="icon">⭐</div><h3>Top Valued Features</h3><p>What users consistently praise across competing apps in your category.</p></div>
      <div class="feature"><div class="icon">🔥</div><h3>Common Pain Points</h3><p>Frustrations users keep complaining about — your opportunity to do better.</p></div>
      <div class="feature"><div class="icon">💡</div><h3>Differentiation Opportunities</h3><p>Gaps in the market that no competitor has solved yet.</p></div>
      <div class="feature"><div class="icon">⚡</div><h3>Quick Wins</h3><p>The highest-impact improvements to ship first, based on real review data.</p></div>
    </div>

    <div class="card" style="margin-top:28px;">
      <h2>How it works</h2>
      <h3>1. Enter a keyword</h3><p>Search any App Store category — "habit tracker", "invoice app", "meditation".</p>
      <h3>2. AI reads the reviews</h3><p>Claude AI analyzes hundreds of real user reviews across the top competing apps.</p>
      <h3>3. Get your report</h3><p>Receive a structured competitive intelligence report with per-app breakdowns and market size estimates.</p>
    </div>

    <div class="card">
      <span class="badge">Built for</span>
      <h2>Indie devs &amp; product teams</h2>
      <p>Stop spending days on manual App Store research. App Store Analyzer delivers the insight that used to take hours — in minutes. No guesswork, no surveys. Just real data from real users.</p>
    </div>

    <footer>
      &copy; 2025 iPronto &nbsp;·&nbsp; <a href="/support">Support</a> &nbsp;·&nbsp; <a href="https://apps.apple.com/app/id6745741527">App Store</a>
    </footer>
  </div>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.route("/support")
def support_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Support — App Store Analyzer</title>
  <style>{_SHARED_CSS}</style>
</head>
<body>
  <header>
    <div>
      <h1>App Store Analyzer</h1>
      <span><a href="/">Home</a> &rsaquo; Support</span>
    </div>
  </header>
  <div class="container">
    <div class="hero">
      <h2>Support</h2>
      <p>We're here to help. Reach us at <a href="mailto:info@ipronto.net" style="color:#fff;font-weight:600;">info@ipronto.net</a> and we'll get back to you within one business day.</p>
    </div>

    <div class="card">
      <h2>Frequently Asked Questions</h2>

      <h3>How do I start a new research?</h3>
      <p>Tap the <strong>+</strong> button on the main screen. You'll be prompted to sign in with Apple if you haven't already, then enter a keyword and configure the search parameters.</p>

      <h3>Why does analysis take a few minutes?</h3>
      <p>The app fetches hundreds of real App Store reviews across multiple apps, then sends them to Claude AI for analysis. Depending on how many apps and review pages you've requested, this typically takes 2–5 minutes.</p>

      <h3>Can I see other people's researches?</h3>
      <p>Yes — the main screen shows all researches from all users, newest first. This lets the community learn from each other's market analysis.</p>

      <h3>What does "Sign in with Apple" give me?</h3>
      <p>Signing in lets you create new researches and access your own history via the profile icon. It requires a real device (not a simulator) and an iCloud-connected Apple ID.</p>

      <h3>How is market size estimated?</h3>
      <p>Downloads are estimated as rating count × 100 (roughly 1% of users rate an app). Monthly active users are estimated at 25% of downloads. Revenue is estimated using industry ARPU benchmarks by App Store category. These are approximations for planning purposes, not official figures.</p>

      <h3>How do I delete my account?</h3>
      <p>Sign in, tap the person icon (top-left), scroll to the bottom, and tap <strong>Delete Account</strong>. This permanently removes all researches you created.</p>

      <h3>Can I change the backend URL?</h3>
      <p>Yes. Go to iPhone Settings → App Store Analyzer → Backend URL. This is intended for developers running the backend locally.</p>
    </div>

    <div class="card">
      <h2>Contact</h2>
      <p>Email: <a href="mailto:info@ipronto.net">info@ipronto.net</a></p>
      <p>For bug reports, please include your iOS version, the keyword you searched, and a description of what happened.</p>
    </div>

    <footer>&copy; 2025 iPronto &nbsp;·&nbsp; <a href="/">Home</a></footer>
  </div>
</body>
</html>"""
    return Response(html, mimetype="text/html")


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/auth/apple", methods=["POST"])
def auth_apple():
    data = request.get_json(silent=True) or {}
    identity_token = data.get("identity_token", "")
    if not identity_token:
        return jsonify({"error": "identity_token is required"}), 400

    # Simulator bypass — only active when DEV_MODE=true in .env
    if DEV_MODE and identity_token == "dev-simulator-token":
        user_id = "simulator-user-001"
        return jsonify({"token": _make_token(user_id), "user_id": user_id})

    try:
        claims = _verify_apple_token(identity_token)
    except Exception as e:
        return jsonify({"error": f"Token verification failed: {e}"}), 401

    user_id = claims["sub"]
    token = _make_token(user_id)
    return jsonify({"token": token, "user_id": user_id})


@app.route("/api/researches", methods=["GET"])
def list_researches():
    docs = list(
        researches_col()
        .find({}, {"apps": 0})  # exclude heavy apps array from list view
        .sort("created_at", DESCENDING)
        .limit(100)
    )
    return jsonify([_serialize(d) for d in docs])


@app.route("/api/researches/<research_id>", methods=["GET"])
def get_research(research_id):
    try:
        oid = ObjectId(research_id)
    except Exception:
        return jsonify({"error": "Invalid ID"}), 400
    doc = researches_col().find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_serialize(doc))


@app.route("/api/researches/<research_id>/status", methods=["GET"])
def get_research_status(research_id):
    try:
        oid = ObjectId(research_id)
    except Exception:
        return jsonify({"error": "Invalid ID"}), 400
    doc = researches_col().find_one(
        {"_id": oid},
        {"status": 1, "progress_message": 1, "apps_analyzed": 1},
    )
    if not doc:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_serialize(doc))


@app.route("/api/researches/<research_id>/retry", methods=["POST"])
@require_auth
def retry_research(research_id):
    try:
        oid = ObjectId(research_id)
    except Exception:
        return jsonify({"error": "Invalid ID"}), 400

    doc = researches_col().find_one({"_id": oid})
    if not doc:
        return jsonify({"error": "Not found"}), 404
    if doc.get("user_id") != request.user_id:
        return jsonify({"error": "Forbidden"}), 403
    if doc.get("status") not in ("failed",):
        return jsonify({"error": "Only failed researches can be retried"}), 400

    keyword = doc["keyword"]
    limit   = doc.get("limit", 10)
    pages   = doc.get("pages", 3)
    country = doc.get("country", "us")

    researches_col().update_one({"_id": oid}, {"$set": {
        "status": "pending",
        "progress_message": "Retrying...",
        "error": None,
        "completed_at": None,
        "apps_analyzed": 0,
        "competitive_report": "",
        "top_valued_features": [],
        "common_pain_points": [],
        "differentiation_opportunities": [],
        "quick_wins": [],
        "apps": [],
    }})

    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(research_id, keyword, limit, pages, country),
        daemon=True,
    )
    thread.start()

    return jsonify({"id": research_id, "status": "pending"}), 202


@app.route("/api/account", methods=["DELETE"])
@require_auth
def delete_account():
    """Delete all researches belonging to the authenticated user."""
    result = researches_col().delete_many({"user_id": request.user_id})
    return jsonify({"message": f"Deleted {result.deleted_count} researches."})


@app.route("/api/researches", methods=["POST"])
@require_auth
def create_research():
    data = request.get_json(silent=True) or {}
    keyword = str(data.get("keyword", "")).strip()
    if not keyword:
        return jsonify({"error": "keyword is required"}), 400

    limit = min(int(data.get("limit", 10)), 15)
    pages = min(int(data.get("pages", 3)), 10)
    country = str(data.get("country", "us"))

    doc = {
        "keyword": keyword,
        "status": "pending",
        "progress_message": "Starting research...",
        "created_at": datetime.now(timezone.utc),
        "completed_at": None,
        "user_id": request.user_id,
        "apps_analyzed": 0,
        "competitive_report": "",
        "apps": [],
        "error": None,
        "limit": limit,
        "pages": pages,
        "country": country,
    }
    result = researches_col().insert_one(doc)
    research_id = str(result.inserted_id)

    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(research_id, keyword, limit, pages, country),
        daemon=True,
    )
    thread.start()

    return jsonify({"id": research_id, "status": "pending"}), 202


# ─── Background pipeline ──────────────────────────────────────────────────────

def _update(research_id: str, status: str, message: str, extra: dict = None):
    update_doc = {"status": status, "progress_message": message}
    if extra:
        update_doc.update(extra)
    researches_col().update_one({"_id": ObjectId(research_id)}, {"$set": update_doc})


def _run_pipeline_background(
    research_id: str, keyword: str, limit: int, pages: int, country: str
):
    """Run the full research pipeline in a background thread, updating MongoDB throughout."""
    try:
        # Ensure API key is available in this thread's environment
        if ANTHROPIC_API_KEY:
            os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY

        results = asyncio.run(_async_pipeline(research_id, keyword, limit, pages, country))

        _update(
            research_id,
            "completed",
            "Research complete!",
            {
                "completed_at": datetime.now(timezone.utc),
                "apps_analyzed": results["apps_analyzed"],
                "competitive_report": results["competitive_report"],
                "top_valued_features": results["top_valued_features"],
                "common_pain_points": results["common_pain_points"],
                "differentiation_opportunities": results["differentiation_opportunities"],
                "quick_wins": results["quick_wins"],
                "apps": results["apps"],
            },
        )
    except Exception as e:
        _update(
            research_id,
            "failed",
            f"Error: {e}",
            {"error": str(e), "completed_at": datetime.now(timezone.utc)},
        )


async def _async_pipeline(
    research_id: str, keyword: str, limit: int, pages: int, country: str
) -> dict:
    from src.app_store_client import AppStoreClient
    from src.analyzer import (
        AppAnalysis,
        analyze_reviews_with_claude,
        estimate_market_metrics,
        generate_competitive_report,
    )

    client = AppStoreClient(country=country, delay=0.4)

    # Step 1 — search
    _update(research_id, "running", f"Searching App Store for '{keyword}'...")
    apps = await client.search_apps(keyword, limit=limit)

    # Step 2 — fetch reviews
    _update(research_id, "running", f"Fetching reviews for {len(apps)} apps...")
    for app in apps:
        app.reviews = await client.fetch_reviews(app, max_pages=pages)

    # Step 3 — AI analysis
    all_analyses = []
    for i, app in enumerate(apps):
        _update(research_id, "running", f"Analyzing app {i + 1}/{len(apps)}: {app.name}")
        analysis_data = await analyze_reviews_with_claude(
            app_name=app.name,
            app_id=app.app_id,
            reviews=app.reviews,
        )
        market = estimate_market_metrics(app.rating_count, app.category, app.price)
        all_analyses.append(AppAnalysis(
            app_id=app.app_id,
            app_name=app.name,
            developer=app.developer,
            rating=app.rating,
            rating_count=app.rating_count,
            price=app.price,
            category=app.category,
            url=app.url,
            icon_url=app.icon_url,
            review_count_analyzed=len(app.reviews),
            praised_features=analysis_data.get("praised_features", []),
            missing_features=analysis_data.get("missing_features", []),
            sentiment_summary=analysis_data.get("sentiment_summary", ""),
            competitive_notes=analysis_data.get("competitive_notes", ""),
            **market,
        ))

    # Step 4 — competitive report
    _update(research_id, "running", "Generating competitive intelligence report...")
    report = await generate_competitive_report(keyword, all_analyses)

    apps_data = [
        {
            "app_id": a.app_id,
            "name": a.app_name,
            "developer": a.developer,
            "rating": a.rating,
            "rating_count": a.rating_count,
            "price": a.price,
            "category": a.category,
            "url": a.url,
            "icon_url": a.icon_url,
            "reviews_analyzed": a.review_count_analyzed,
            "praised_features": a.praised_features,
            "missing_features": a.missing_features,
            "sentiment_summary": a.sentiment_summary,
            "competitive_notes": a.competitive_notes,
            "estimated_downloads": a.estimated_downloads,
            "estimated_mau": a.estimated_mau,
            "revenue_low": a.revenue_low,
            "revenue_mid": a.revenue_mid,
            "revenue_high": a.revenue_high,
            "monetization_note": a.monetization_note,
        }
        for a in all_analyses
    ]

    return {
        "apps_analyzed": len(all_analyses),
        "competitive_report": report["competitive_report"],
        "top_valued_features": report["top_valued_features"],
        "common_pain_points": report["common_pain_points"],
        "differentiation_opportunities": report["differentiation_opportunities"],
        "quick_wins": report["quick_wins"],
        "apps": apps_data,
    }


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
