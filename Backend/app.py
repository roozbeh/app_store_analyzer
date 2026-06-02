"""
Flask API for the App Store Analyzer.

Endpoints:
  GET    /api/health                     — health check (public)
  POST   /api/auth/apple                 — verify Apple identity token, return JWT
  GET    /api/researches                 — list all researches, newest first (public)
  GET    /api/researches/<id>            — full research with apps array
  GET    /api/researches/<id>/status     — lightweight status poll
  POST   /api/researches                 — start new research (requires Bearer JWT)
  POST   /api/researches/<id>/retry      — retry failed research, resume from failed stage (requires Bearer JWT)
  DELETE /api/account                    — delete all researches for user (requires Bearer JWT)

Web pages:
  GET  /                  — marketing landing page
  GET  /research/<id>     — shareable research result page
  GET  /privacy           — privacy policy
  GET  /support           — support page
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
from flask import Flask, jsonify, request, Response, send_from_directory
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
        "exp": datetime.now(timezone.utc) + timedelta(days=365),
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


# ─── Static files ─────────────────────────────────────────────────────────────

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(STATIC_DIR, "favicon.ico", mimetype="image/x-icon")

@app.route("/apple-touch-icon.png")
@app.route("/apple-touch-icon-precomposed.png")
def apple_touch_icon():
    return send_from_directory(STATIC_DIR, "apple-touch-icon.png", mimetype="image/png")


# ─── Web pages ────────────────────────────────────────────────────────────────

_FAVICON_TAGS = """
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">"""

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
  <title>App Store Analyzer — AI Market Research</title>{_FAVICON_TAGS}
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


def _resolve_insight_array(key: str, doc: dict) -> list:
    """
    Return the insight array for `key`, falling back to:
    1. Standard JSON parse of competitive_report
    2. Partial string extraction for truncated JSON (hit token limit)
    """
    native = doc.get(key) or []
    if native:
        return native

    report = (doc.get("competitive_report") or "").strip()
    if not report.startswith("{"):
        return []

    # Try standard JSON parse first
    try:
        parsed = json.loads(report)
        items = parsed.get(key) or []
        if items:
            return items
    except Exception:
        pass

    # Partial extraction — handles truncated JSON
    try:
        search = f'"{key}":'
        idx = report.find(search)
        if idx == -1:
            return []
        rest = report[idx + len(search):].lstrip()
        if not rest.startswith("["):
            return []
        rest = rest[1:]  # skip '['

        items = []
        while rest:
            rest = rest.lstrip()
            if not rest or rest[0] in ("]", "}"):
                break
            if rest[0] == ",":
                rest = rest[1:]
                continue
            if rest[0] != '"':
                break
            rest = rest[1:]  # skip opening quote

            item_chars = []
            escaped = False
            closed = False
            i = 0
            while i < len(rest):
                ch = rest[i]
                if escaped:
                    mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
                    item_chars.append(mapping.get(ch, ch))
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    closed = True
                    i += 1
                    break
                else:
                    item_chars.append(ch)
                i += 1

            rest = rest[i:]
            item = "".join(item_chars)
            if item:
                items.append(item)
            if not closed:
                break  # truncated mid-string

        return items
    except Exception:
        return []


@app.route("/research/<research_id>")
def research_page(research_id):
    try:
        oid = ObjectId(research_id)
    except Exception:
        return Response("<h1>Invalid research ID</h1>", status=400, mimetype="text/html")

    doc = researches_col().find_one({"_id": oid})
    if not doc:
        return Response("<h1>Research not found</h1>", status=404, mimetype="text/html")

    keyword   = doc.get("keyword", "")
    status    = doc.get("status", "")
    apps_n    = doc.get("apps_analyzed", 0)
    created   = doc.get("created_at")
    date_str  = created.strftime("%B %d, %Y") if hasattr(created, "strftime") else str(created)[:10]

    top_features  = _resolve_insight_array("top_valued_features",           doc)
    pain_points   = _resolve_insight_array("common_pain_points",            doc)
    opportunities = _resolve_insight_array("differentiation_opportunities", doc)
    quick_wins    = _resolve_insight_array("quick_wins",                    doc)
    apps          = doc.get("apps", []) or []

    def list_items(items, color):
        if not items:
            return "<p style='color:#6e6e73'>No data available.</p>"
        rows = ""
        for i, item in enumerate(items, 1):
            rows += f"""<div style='display:flex;gap:12px;padding:10px 0;{"border-top:1px solid #f0f0f5" if i>1 else ""}'>
              <span style='min-width:22px;height:22px;border-radius:50%;background:{color}22;color:{color};
                font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center'>{i}</span>
              <span style='color:#3a3a3c;font-size:.93rem;line-height:1.5'>{item}</span></div>"""
        return rows

    def section(title, icon, color, items):
        return f"""<div style='background:#fff;border-radius:14px;margin-bottom:16px;overflow:hidden;
                               box-shadow:0 1px 4px rgba(0,0,0,.07)'>
          <div style='background:{color}18;padding:12px 20px;display:flex;align-items:center;gap:8px'>
            <span style='font-size:1rem'>{icon}</span>
            <span style='font-weight:700;font-size:.9rem;color:{color}'>{title}</span>
            <span style='margin-left:auto;background:{color}22;color:{color};border-radius:20px;
              padding:1px 9px;font-size:.75rem;font-weight:700'>{len(items)}</span>
          </div>
          <div style='padding:0 20px 8px'>{list_items(items, color)}</div>
        </div>"""

    def app_card(a):
        name     = a.get("name", "")
        dev      = a.get("developer", "")
        rating   = a.get("rating", 0)
        rcount   = a.get("rating_count", 0)
        price    = a.get("price", "Free")
        icon_url = a.get("icon_url", "")
        url      = a.get("url", "")
        praised  = a.get("praised_features", [])
        missing  = a.get("missing_features", [])
        summary  = a.get("sentiment_summary", "")
        stars    = "★" * int(round(rating)) + "☆" * (5 - int(round(rating)))
        rcount_fmt = f"{rcount/1000:.0f}K" if rcount >= 1000 else str(rcount)

        praised_html = "".join(f"<li>{f}</li>" for f in praised[:5])
        missing_html = "".join(f"<li>{f}</li>" for f in missing[:5])

        return f"""<div style='background:#fff;border-radius:14px;padding:16px 20px;margin-bottom:12px;
                               box-shadow:0 1px 4px rgba(0,0,0,.07)'>
          <div style='display:flex;gap:14px;align-items:flex-start'>
            {"<img src='" + icon_url + "' style='width:52px;height:52px;border-radius:12px;flex-shrink:0' />" if icon_url else ""}
            <div style='flex:1;min-width:0'>
              <div style='font-weight:700;font-size:.95rem'>{name}</div>
              <div style='color:#6e6e73;font-size:.8rem'>{dev}</div>
              <div style='color:#f59e0b;font-size:.8rem'>{stars} <span style='color:#6e6e73'>({rcount_fmt})</span></div>
            </div>
            <div style='display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0'>
              <span style='background:#eff6ff;color:#0071e3;border-radius:20px;padding:2px 10px;font-size:.75rem;font-weight:600'>{price}</span>
              {"<a href='" + url + "' style='font-size:.75rem;color:#0071e3'>App Store ↗</a>" if url else ""}
            </div>
          </div>
          {f"<p style='color:#6e6e73;font-size:.83rem;margin-top:10px;font-style:italic'>{summary}</p>" if summary else ""}
          <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px'>
            {"<div><div style='font-size:.78rem;font-weight:600;color:#16a34a;margin-bottom:4px'>❤ Users Love</div><ul style='font-size:.8rem;color:#3a3a3c;padding-left:16px;margin:0'>" + praised_html + "</ul></div>" if praised else ""}
            {"<div><div style='font-size:.78rem;font-weight:600;color:#ea580c;margin-bottom:4px'>⚠ Users Want</div><ul style='font-size:.8rem;color:#3a3a3c;padding-left:16px;margin:0'>" + missing_html + "</ul></div>" if missing else ""}
          </div>
        </div>"""

    status_color = {"completed": "#16a34a", "failed": "#dc2626",
                    "running": "#0071e3", "pending": "#d97706"}.get(status, "#6e6e73")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{keyword} — App Store Analyzer</title>{_FAVICON_TAGS}
  <style>{_SHARED_CSS}
    @media(max-width:560px) {{ .app-grid {{ grid-template-columns: 1fr !important; }} }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1><a href="/" style="color:inherit;text-decoration:none">App Store Analyzer</a></h1>
      <span>Market Research Report</span>
    </div>
  </header>
  <div class="container">

    <!-- Title -->
    <div style='display:flex;align-items:center;gap:14px;margin-bottom:6px'>
      <h2 style='font-size:1.8rem;margin:0'>{keyword}</h2>
      <span style='background:{status_color}18;color:{status_color};border-radius:20px;
        padding:3px 12px;font-size:.8rem;font-weight:700;text-transform:capitalize'>{status}</span>
    </div>
    <p style='color:#6e6e73;font-size:.88rem;margin-bottom:28px'>
      {apps_n} apps analyzed &nbsp;·&nbsp; {date_str}
    </p>

    <!-- Insight sections -->
    {section("Top Valued Features", "⭐", "#d97706", top_features)}
    {section("Common Pain Points", "🔥", "#dc2626", pain_points)}
    {section("Differentiation Opportunities", "💡", "#0071e3", opportunities)}
    {section("Quick Wins", "⚡", "#16a34a", quick_wins)}

    <!-- App analyses -->
    {"<h2 style='margin:28px 0 14px'>App Analyses</h2>" + "".join(app_card(a) for a in apps) if apps else ""}

    <!-- Share -->
    <div style='text-align:center;margin-top:32px;padding:20px;background:#fff;border-radius:14px;
                box-shadow:0 1px 4px rgba(0,0,0,.07)'>
      <p style='color:#6e6e73;font-size:.88rem;margin-bottom:10px'>Created with App Store Analyzer</p>
      <a href="/" style='display:inline-block;background:#0071e3;color:#fff;padding:10px 24px;
         border-radius:10px;font-weight:600;text-decoration:none;font-size:.9rem'>Try it yourself →</a>
    </div>

    <footer>&copy; 2025 iPronto &nbsp;·&nbsp; <a href="/support">Support</a></footer>
  </div>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.route("/privacy")
def privacy_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Privacy Policy — App Store Analyzer</title>{_FAVICON_TAGS}
  <style>{_SHARED_CSS}</style>
</head>
<body>
  <header>
    <div>
      <h1>App Store Analyzer</h1>
      <span><a href="/">Home</a> &rsaquo; Privacy Policy</span>
    </div>
  </header>
  <div class="container">
    <div class="hero">
      <h2>Privacy Policy</h2>
      <p>Effective date: April 10, 2025 &nbsp;·&nbsp; iPronto</p>
    </div>

    <div class="card">
      <h2>Overview</h2>
      <p>App Store Analyzer ("the app") is a market research tool that analyzes publicly available App Store reviews using AI. We take your privacy seriously and collect only what is strictly necessary to operate the service.</p>
    </div>

    <div class="card">
      <h2>Information We Collect</h2>

      <h3>Sign in with Apple</h3>
      <p>When you sign in, Apple provides us with a unique user identifier (your Apple ID "sub" claim). We do not receive your name or email address unless you explicitly choose to share them. This identifier is used solely to associate your researches with your account.</p>

      <h3>Research data</h3>
      <p>When you create a research, we store the keyword you searched, the results of the analysis, and your Apple user identifier so you can manage your own researches. <strong>Researches are visible to all users of the app and via shareable links.</strong> Do not include sensitive or confidential keywords.</p>

      <h3>App Store review data</h3>
      <p>The app fetches publicly available App Store reviews from Apple's RSS feeds and iTunes Search API. This data is processed by Anthropic's Claude AI to generate competitive insights. We do not store raw review text — only the AI-generated summaries.</p>

      <h3>Usage data</h3>
      <p>We do not use any third-party analytics SDKs or advertising frameworks. Standard server access logs (IP address, request path, timestamp) are retained for up to 30 days for security and debugging purposes only.</p>
    </div>

    <div class="card">
      <h2>How We Use Your Information</h2>
      <ul>
        <li>To authenticate you and associate researches with your account</li>
        <li>To run the market research pipeline on your behalf</li>
        <li>To display your researches and allow you to delete them</li>
        <li>To maintain the security and reliability of the service</li>
      </ul>
      <p style="margin-top:12px">We do not sell, rent, or share your personal information with third parties for marketing purposes.</p>
    </div>

    <div class="card">
      <h2>Third-Party Services</h2>
      <h3>Anthropic (Claude AI)</h3>
      <p>App Store review text is sent to Anthropic's API to generate analysis summaries. Anthropic's <a href="https://www.anthropic.com/legal/privacy" target="_blank">Privacy Policy</a> applies to data processed by their API.</p>

      <h3>Apple (App Store / Sign in with Apple)</h3>
      <p>App Store data is fetched from Apple's public APIs. Authentication is handled by Apple's Sign in with Apple service. Apple's <a href="https://www.apple.com/legal/privacy/" target="_blank">Privacy Policy</a> applies.</p>

      <h3>MongoDB Atlas</h3>
      <p>Research data is stored in MongoDB Atlas (cloud database hosted on AWS). MongoDB's <a href="https://www.mongodb.com/legal/privacy-policy" target="_blank">Privacy Policy</a> applies.</p>
    </div>

    <div class="card">
      <h2>Data Retention &amp; Deletion</h2>
      <p>Your researches are stored until you delete them. You can delete all your data at any time from within the app: tap the person icon → <strong>Delete Account</strong>. This permanently removes all researches associated with your Apple ID.</p>
      <p>To request deletion by email, contact us at <a href="mailto:info@ipronto.net">info@ipronto.net</a> with the subject line "Data Deletion Request".</p>
    </div>

    <div class="card">
      <h2>Children's Privacy</h2>
      <p>App Store Analyzer is not directed at children under 13. We do not knowingly collect personal information from children under 13.</p>
    </div>

    <div class="card">
      <h2>Changes to This Policy</h2>
      <p>We may update this policy from time to time. The effective date at the top of this page will be updated accordingly. Continued use of the app after changes constitutes acceptance of the updated policy.</p>
    </div>

    <div class="card">
      <h2>Contact</h2>
      <p>Questions about this privacy policy? Contact us at <a href="mailto:info@ipronto.net">info@ipronto.net</a>.</p>
    </div>

    <footer>&copy; 2025 iPronto &nbsp;·&nbsp; <a href="/">Home</a> &nbsp;·&nbsp; <a href="/support">Support</a></footer>
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
  <title>Support — App Store Analyzer</title>{_FAVICON_TAGS}
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

    # Preserve apps that were already successfully analyzed — resume from where we left off
    existing_apps = doc.get("apps", [])
    skip_app_ids  = {a["app_id"] for a in existing_apps}

    researches_col().update_one({"_id": oid}, {"$set": {
        "status": "pending",
        "progress_message": f"Resuming… {len(existing_apps)} apps already done.",
        "error": None,
        "completed_at": None,
        # Keep: apps, apps_analyzed (already correct from previous run)
        "competitive_report": "",
        "top_valued_features": [],
        "common_pain_points": [],
        "differentiation_opportunities": [],
        "quick_wins": [],
    }})

    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(research_id, keyword, limit, pages, country),
        kwargs={"skip_app_ids": skip_app_ids},
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
    research_id: str, keyword: str, limit: int, pages: int, country: str,
    skip_app_ids: set = None,
):
    """Run the full research pipeline in a background thread, updating MongoDB throughout."""
    try:
        if ANTHROPIC_API_KEY:
            os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY

        results = asyncio.run(
            _async_pipeline(research_id, keyword, limit, pages, country,
                            skip_app_ids=skip_app_ids or set())
        )

        _update(
            research_id,
            "completed",
            "Research complete!",
            {
                "completed_at": datetime.now(timezone.utc),
                "competitive_report": results["competitive_report"],
                "top_valued_features": results["top_valued_features"],
                "common_pain_points": results["common_pain_points"],
                "differentiation_opportunities": results["differentiation_opportunities"],
                "quick_wins": results["quick_wins"],
                # apps + apps_analyzed are written incrementally — do not overwrite here
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
    research_id: str, keyword: str, limit: int, pages: int, country: str,
    skip_app_ids: set = None,
) -> dict:
    from src.app_store_client import AppStoreClient
    from src.analyzer import (
        AppAnalysis,
        analyze_reviews_with_claude,
        estimate_market_metrics,
        generate_competitive_report,
    )

    skip_app_ids = skip_app_ids or set()
    col = researches_col()
    oid = ObjectId(research_id)

    client = AppStoreClient(country=country, delay=0.4)

    # Step 1 — search
    _update(research_id, "running", f"Searching App Store for '{keyword}'...")
    apps = await client.search_apps(keyword, limit=limit)

    # Step 2 — fetch reviews (only for apps we haven't analyzed yet)
    new_apps = [a for a in apps if a.app_id not in skip_app_ids]
    _update(research_id, "running", f"Fetching reviews for {len(new_apps)} apps...")
    for app in new_apps:
        app.reviews = await client.fetch_reviews(app, max_pages=pages)

    # Step 3 — AI analysis per app, with per-app retry and incremental MongoDB save
    # Load already-saved analyses from MongoDB (from a previous partial run)
    existing_doc = col.find_one({"_id": oid}, {"apps": 1, "apps_analyzed": 1}) or {}
    existing_apps_data = existing_doc.get("apps", [])
    apps_analyzed_count = len(existing_apps_data)

    # Rebuild AppAnalysis objects for already-done apps so they feed the report
    all_analyses: list[AppAnalysis] = []
    for saved in existing_apps_data:
        all_analyses.append(AppAnalysis(
            app_id=saved["app_id"],
            app_name=saved["name"],
            developer=saved.get("developer", ""),
            rating=saved.get("rating", 0.0),
            rating_count=saved.get("rating_count", 0),
            price=saved.get("price", "Free"),
            category=saved.get("category", ""),
            url=saved.get("url", ""),
            icon_url=saved.get("icon_url", ""),
            review_count_analyzed=saved.get("reviews_analyzed", 0),
            praised_features=saved.get("praised_features", []),
            missing_features=saved.get("missing_features", []),
            sentiment_summary=saved.get("sentiment_summary", ""),
            competitive_notes=saved.get("competitive_notes", ""),
            estimated_downloads=saved.get("estimated_downloads", 0),
            estimated_mau=saved.get("estimated_mau", 0),
            revenue_low=saved.get("revenue_low", 0.0),
            revenue_mid=saved.get("revenue_mid", 0.0),
            revenue_high=saved.get("revenue_high", 0.0),
            monetization_note=saved.get("monetization_note", ""),
        ))

    total_apps = len(apps)
    for i, app in enumerate(new_apps):
        _update(research_id, "running",
                f"Analyzing app {apps_analyzed_count + 1}/{total_apps}: {app.name}")

        # Retry the Claude analysis up to 3 times before graceful degradation
        analysis_data = None
        for attempt in range(3):
            try:
                analysis_data = await analyze_reviews_with_claude(
                    app_name=app.name,
                    app_id=app.app_id,
                    reviews=app.reviews,
                )
                break
            except Exception as exc:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt * 3)   # 3s, 6s
                else:
                    analysis_data = {
                        "praised_features": [],
                        "missing_features": [],
                        "sentiment_summary": f"Analysis unavailable after 3 attempts: {exc}",
                        "competitive_notes": "",
                    }

        market = estimate_market_metrics(app.rating_count, app.category, app.price)
        analysis = AppAnalysis(
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
        )
        all_analyses.append(analysis)
        apps_analyzed_count += 1

        # Persist this app immediately so a later failure doesn't lose the work
        app_data = {
            "app_id": analysis.app_id,
            "name": analysis.app_name,
            "developer": analysis.developer,
            "rating": analysis.rating,
            "rating_count": analysis.rating_count,
            "price": analysis.price,
            "category": analysis.category,
            "url": analysis.url,
            "icon_url": analysis.icon_url,
            "reviews_analyzed": analysis.review_count_analyzed,
            "praised_features": analysis.praised_features,
            "missing_features": analysis.missing_features,
            "sentiment_summary": analysis.sentiment_summary,
            "competitive_notes": analysis.competitive_notes,
            "estimated_downloads": analysis.estimated_downloads,
            "estimated_mau": analysis.estimated_mau,
            "revenue_low": analysis.revenue_low,
            "revenue_mid": analysis.revenue_mid,
            "revenue_high": analysis.revenue_high,
            "monetization_note": analysis.monetization_note,
        }
        col.update_one({"_id": oid}, {
            "$push": {"apps": app_data},
            "$set": {"apps_analyzed": apps_analyzed_count},
        })

    # Step 4 — competitive report (retry up to 3 times)
    _update(research_id, "running", "Generating competitive intelligence report...")
    report = None
    for attempt in range(3):
        try:
            report = await generate_competitive_report(keyword, all_analyses)
            break
        except Exception as exc:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt * 3)
            else:
                raise RuntimeError(
                    f"Competitive report failed after 3 attempts: {exc}"
                ) from exc

    return {
        "competitive_report": report["competitive_report"],
        "top_valued_features": report["top_valued_features"],
        "common_pain_points": report["common_pain_points"],
        "differentiation_opportunities": report["differentiation_opportunities"],
        "quick_wins": report["quick_wins"],
    }


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
