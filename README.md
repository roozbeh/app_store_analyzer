# 🔍 App Store Competitor Intelligence Agent

An agentic tool that searches the Apple App Store, reads user reviews, and uses Claude AI to extract competitive intelligence — what users love, what they wish existed, and where the gaps are.

---

## How It Works

```
Keywords  ──►  App Store Search  ──►  Fetch Reviews  ──►  Claude Analysis  ──►  Report
```

1. **Search** — Uses Apple's free iTunes Search API to find apps matching your keywords
2. **Fetch Reviews** — Pulls up to 500 reviews per app via Apple's RSS feed (no auth needed)
3. **Analyze** — Sends reviews to Claude to extract praised features and missing features
4. **Synthesize** — Claude writes a full competitive intelligence report with differentiation opportunities
5. **Save** — Outputs both a structured JSON file and a readable Markdown report

---

## Setup

```bash
pip install -r requirements.txt
```

No API keys needed for the App Store data — it uses Apple's public iTunes Search API and RSS feeds.

The Claude analysis uses the Anthropic API (already configured in this environment).

---

## Usage

### Basic
```bash
python main.py --keywords "habit tracker"
```

### Multiple keywords (deduplicates overlapping results)
```bash
python main.py --keywords "todo list" "task manager" "productivity planner"
```

### Full options
```bash
python main.py \
  --keywords "meditation" "mindfulness" \
  --limit 8 \          # apps per keyword (default: 5)
  --pages 5 \          # review pages per app (50 reviews/page, max: 10)
  --country us \       # App Store region (default: us)
  --output ./results   # output folder (default: output/)
```

---

## Output

Both files are saved in `output/` (or your `--output` dir):

- **`{keyword}_{timestamp}.json`** — Full structured data: app metadata, per-app analysis, final report
- **`{keyword}_{timestamp}.md`** — Human-readable Markdown report

### JSON structure
```json
{
  "keywords": ["habit tracker"],
  "apps_analyzed": 5,
  "apps": [
    {
      "name": "Streaks",
      "rating": 4.8,
      "praised_features": ["clean UI", "Apple Watch sync", ...],
      "missing_features": ["Android version", "collaboration", ...],
      "sentiment_summary": "...",
      "competitive_notes": "..."
    }
  ],
  "competitive_report": "# Competitive Report\n..."
}
```

---

## Extending the Tool

### Add Google Play support
Drop in a `google_play_client.py` with the same interface as `AppStoreClient` and import it in `main.py`.

### Change the AI model
In `src/analyzer.py`, update `CLAUDE_MODEL`.

### Add webhook / Slack notifications
After `run_agent()` completes, post `results["competitive_report"]` to any webhook.

### Schedule recurring runs
```bash
# Daily cron job
0 9 * * * cd /path/to/tool && python main.py --keywords "your app category"
```

---

## Rate Limits & Politeness

- **iTunes Search API**: ~20 req/min (enforced by the 0.4s delay in `AppStoreClient`)
- **Reviews RSS**: No official limit but respects 0.4s delay; use `--pages 3` for safety
- **Claude API**: Subject to your plan's rate limits

---

## Limitations

- Apple's RSS review feed only returns up to **500 reviews** per app per country
- Reviews older than ~2 years may not be included
- App Store search ranking varies by country; use `--country` to target specific markets
