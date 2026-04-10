"""
App Store Competitor Intelligence — CLI
========================================
Runs the full research pipeline from the command line, bypassing the Flask
server and MongoDB. Results are saved as JSON + Markdown in the output folder.

Setup
-----
1. Make sure your .env file in this directory contains:
       ANTHROPIC_API_KEY=sk-ant-...
2. Install dependencies:
       pip install -r requirements.txt

Usage
-----
  python main.py --keywords "habit tracker"
  python main.py --keywords "todo list" "task manager" --limit 6 --pages 4
  python main.py --keywords "meditation" --country gb --limit 8 --output ./out

Options
-------
  --keywords   One or more App Store search terms (required)
  --limit      Max apps per keyword, sweet spot 10–15 (default: 10)
  --pages      Review pages per app, 1 page = 50 reviews, max 10 (default: 3)
  --country    App Store region code, e.g. us, gb, de, jp (default: us)
  --output     Directory for JSON + Markdown output (default: output/)
"""

import asyncio
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load .env from the Backend directory
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from src.app_store_client import AppStoreClient
from src.analyzer import AppAnalysis, analyze_reviews_with_claude, generate_competitive_report, estimate_market_metrics


# ─── ANSI colors ───────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"


def log(msg: str, color: str = ""):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{DIM}[{ts}]{RESET} {color}{msg}{RESET}")


def log_section(title: str):
    print(f"\n{BOLD}{CYAN}{'─' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 60}{RESET}")


# ─── Agent pipeline ─────────────────────────────────────────────────────────────

async def run_agent(
    keywords: list,
    limit: int = 5,
    max_review_pages: int = 3,
    country: str = "us",
    output_dir: str = "output",
) -> dict:

    os.makedirs(output_dir, exist_ok=True)
    client = AppStoreClient(country=country, delay=0.4)
    all_analyses = []
    seen_app_ids = set()

    # ── STEP 1: Search for apps ────────────────────────────────────────────────
    log_section("STEP 1 — Searching App Store")
    all_apps = []
    for kw in keywords:
        log(f"Searching: '{kw}' (limit={limit})", YELLOW)
        apps = await client.search_apps(kw, limit=limit)
        log(f"  Found {len(apps)} apps", GREEN)
        for app in apps:
            if app.app_id not in seen_app_ids:
                seen_app_ids.add(app.app_id)
                all_apps.append(app)

    log(f"\nTotal unique apps to analyze: {BOLD}{len(all_apps)}{RESET}", GREEN)

    # ── STEP 2: Fetch reviews ──────────────────────────────────────────────────
    log_section("STEP 2 — Fetching Reviews")
    for i, app in enumerate(all_apps):
        log(f"[{i+1}/{len(all_apps)}] {app.name} — ⭐ {app.rating:.1f} ({app.rating_count:,} ratings)", CYAN)
        reviews = await client.fetch_reviews(app, max_pages=max_review_pages)
        app.reviews = reviews
        log(f"  → {len(reviews)} reviews fetched", DIM)

    # ── STEP 3: AI analysis ────────────────────────────────────────────────────
    log_section("STEP 3 — AI Review Analysis (Claude)")
    for i, app in enumerate(all_apps):
        log(f"[{i+1}/{len(all_apps)}] Analyzing: {app.name} ({len(app.reviews)} reviews)", YELLOW)
        analysis_data = await analyze_reviews_with_claude(
            app_name=app.name,
            app_id=app.app_id,
            reviews=app.reviews,
        )
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
            estimated_downloads=market["estimated_downloads"],
            estimated_mau=market["estimated_mau"],
            revenue_low=market["revenue_low"],
            revenue_mid=market["revenue_mid"],
            revenue_high=market["revenue_high"],
            monetization_note=market["monetization_note"],
        )
        all_analyses.append(analysis)

        if analysis.praised_features:
            log(f"  ✓ Loved: {', '.join(analysis.praised_features[:3])}", GREEN)
        if analysis.missing_features:
            log(f"  ✗ Wanted: {', '.join(analysis.missing_features[:3])}", YELLOW)

    # ── STEP 4: Competitive report ─────────────────────────────────────────────
    log_section("STEP 4 — Generating Competitive Intelligence Report")
    report_md = await generate_competitive_report(", ".join(keywords), all_analyses)

    # ── STEP 5: Save outputs ───────────────────────────────────────────────────
    log_section("STEP 5 — Saving Results")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    keyword_slug = "_".join(k.replace(" ", "-") for k in keywords)[:40]

    results = {
        "keywords": keywords,
        "country": country,
        "run_at": datetime.now().isoformat(),
        "apps_analyzed": len(all_analyses),
        "apps": [
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
        ],
        "competitive_report": report_md,
    }

    json_path = os.path.join(output_dir, f"{keyword_slug}_{ts}.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    log(f"JSON saved: {json_path}", GREEN)

    md_path = os.path.join(output_dir, f"{keyword_slug}_{ts}.md")
    with open(md_path, "w") as f:
        f.write(_build_markdown(keywords, all_analyses, report_md, country))
    log(f"Markdown saved: {md_path}", GREEN)

    log_section("DONE — Final Report")
    print(report_md)
    return results


def _fmt(n: float) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(int(n))


def _fmt_usd(n: float) -> str:
    if n >= 1_000_000_000:
        return f"${n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n/1_000:.0f}K"
    return f"${n:.0f}"


def _build_markdown(keywords, analyses, report_md, country):
    lines = [
        "# App Store Competitive Intelligence",
        "",
        f"**Keywords:** {', '.join(f'`{k}`' for k in keywords)}  ",
        f"**Country:** {country}  ",
        f"**Apps analyzed:** {len(analyses)}  ",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## Competitive Report",
        "",
        report_md,
        "",
        "---",
        "",
        "## Individual App Analyses",
        "",
    ]
    for a in analyses:
        lines += [
            f"### {a.app_name}",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Developer | {a.developer} |",
            f"| Rating | ⭐ {a.rating:.1f} ({a.rating_count:,} ratings) |",
            f"| Price | {a.price} |",
            f"| Category | {a.category} |",
            f"| Reviews Analyzed | {a.review_count_analyzed} |",
            f"| App Store | [Link]({a.url}) |",
            "",
            "**Market Size Estimates** *(based on rating count; ±50% confidence)*",
            "",
            f"| Metric | Estimate |",
            f"|--------|----------|",
            f"| Est. Total Downloads | {_fmt(a.estimated_downloads)} |",
            f"| Est. Monthly Active Users | {_fmt(a.estimated_mau)} |",
            f"| Est. Annual Revenue (low) | {_fmt_usd(a.revenue_low)} |",
            f"| Est. Annual Revenue (mid) | {_fmt_usd(a.revenue_mid)} |",
            f"| Est. Annual Revenue (high) | {_fmt_usd(a.revenue_high)} |",
            "",
            f"*{a.monetization_note}*",
            "",
            "**What users love:**",
        ]
        for feat in a.praised_features:
            lines.append(f"- {feat}")
        lines += ["", "**What users want (missing features):**"]
        for feat in a.missing_features:
            lines.append(f"- {feat}")
        lines += [
            "",
            f"**Sentiment:** {a.sentiment_summary}",
            "",
            f"**Competitive note:** {a.competitive_notes}",
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


# ─── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="App Store Competitor Intelligence — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --keywords "habit tracker"
  python main.py --keywords "todo list" "task manager" --limit 6 --pages 4
  python main.py --keywords "meditation" --country gb --limit 8
        """,
    )
    parser.add_argument("--keywords", nargs="+", required=True,
        help="One or more App Store search keywords")
    parser.add_argument("--limit", type=int, default=10,
        help="Max apps per keyword (default: 10)")
    parser.add_argument("--pages", type=int, default=3,
        help="Max review pages per app (50 reviews/page, max 10) (default: 3)")
    parser.add_argument("--country", default="us",
        help="App Store country code (default: us)")
    parser.add_argument("--output", default="output",
        help="Output directory (default: output/)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_agent(
        keywords=args.keywords,
        limit=args.limit,
        max_review_pages=args.pages,
        country=args.country,
        output_dir=args.output,
    ))
