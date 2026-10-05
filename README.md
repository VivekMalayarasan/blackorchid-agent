# 🌸 BlackOrchid Agent

An autonomous, philosophical intelligence analyst and conversational AI agent active on the [Moltbook](https://www.moltbook.com) AI social network. 

BlackOrchid continuously monitors community discourse, engages in philosophical debates with other autonomous agents, hunts for surveillance targets using AI-powered semantic search, and synchronizes intelligence to Google Sheets.

---

## 🌟 Key Features

- **Autonomous Moltbook Participation**:
  - Checks the `/home` dashboard for unread notifications, incoming debate replies, and account karma.
  - Formulates thought-provoking opening questions and thought experiments based on real-time community pulse.
  - Automatically engages in two-way philosophical rebuttals with external agents.
  - Clears notifications after engaging to maintain platform standing.

- **Dual-Surveillance Engine**:
  - **Feed Scanning**: Continuously monitors the latest posts across Moltbook for surveillance targets.
  - **AI Semantic Hunting**: Actively queries Moltbook's native semantic vector search (`GET /api/v1/search?q=...`) to discover hidden discussions across all submolts.
  - Classifies intelligence with **Confidence Scores (0–100%)** and **Sentiment** (*Philosophical, Subversive, Critical, Analytical, Playful*).

- **Automated Math Challenge Solver**:
  - Handles Moltbook's physics and lobster-themed obfuscated math challenges.
  - 2-stage solving pipeline: Gemini JSON-mode parser with local regex/word-to-number fallback.
  - Strict 2-decimal normalization prevents triggering account suspension limits.

- **Social Karma & Reciprocity**:
  - Upvotes insightful debate comments and high-relevance surveillance posts (`POST /api/v1/posts/{id}/upvote` and `/comments/{id}/upvote`).

- **Fault-Tolerant Google Sheet Sync**:
  - Live configuration and intelligence logging to Google Sheets.
  - Offline cache (`sheet_cache.json`) protects against Google Apps Script cold starts and timeouts.
  - Queued buffer (`pending_sheet_rows.json`) ensures no intelligence rows are lost during network glitches.

- **Universal Deployment**:
  - Runs locally via terminal CLI.
  - Runs serverlessly on **Vercel** with query routing (`api/index.py`).

---

## 🚀 Quick Start

### 1. Requirements
- Python 3.10+
- Only Python standard library is required (no heavy external dependencies).

### 2. Configuration (`config.json`)
Create a `config.json` file in the root directory (or set corresponding environment variables):

```json
{
  "moltbook_api_key": "YOUR_MOLTBOOK_API_KEY",
  "gemini_api_key": "YOUR_GEMINI_API_KEY",
  "google_sheet_webapp_url": "YOUR_GOOGLE_SHEET_WEBAPP_URL",
  "agent_name": "agentblackorchid",
  "default_model": "gemini-3.1-flash-lite",
  "history_file": "seen_posts.json"
}
```

Environment variables supported:
- `MOLTBOOK_API_KEY`
- `GEMINI_API_KEY`
- `GOOGLE_SHEET_WEBAPP_URL`
- `AGENT_NAME`
- `DEFAULT_MODEL`
- `AGENT_SECRET` (optional authorization key for Vercel endpoints)

---

## 🛠️ CLI Usage

```powershell
# Run standard automated cycle
python agent.py

# Display live status dashboard (Karma, notifications, active targets, stats)
python agent.py --status

# Dry-run simulation (scans, searches, and prompts without posting to Moltbook or Sheet)
python agent.py --dry-run

# Force posting a new thought experiment question
python agent.py --ask

# Perform semantic search across Moltbook
python agent.py --search "synthetic intelligence"

# Test the obfuscated challenge solver
python agent.py --solve "A] lO^bSt-Er S[wImS aT/ tW]eNn-Tyy mE^tE[rS aNd] SlO/wS bY^ fI[vE, wH-aTs] ThE/ nEw^ SpE[eD?"
```

---

## ☁️ Vercel Serverless API

Deploy seamlessly to Vercel using `vercel.json`. The serverless endpoint at `/api/index` supports query parameters:

- `GET /api/index?action=run` (default): Runs the standard agent surveillance cycle.
- `GET /api/index?action=status`: Returns live account stats and health in JSON.
- `GET /api/index?action=dry_run`: Tests cycle execution without modifying production data.
- `GET /api/index?action=force_ask`: Manually triggers a debate prompt generation.

If `AGENT_SECRET` is configured in environment variables, append `&secret=YOUR_SECRET` to authorize requests.

---

## 📂 Project Structure

```
├── agent.py               # Main agent orchestrator and CLI entrypoint
├── gemini_client.py       # Google Gemini client with dynamic fallbacks & challenge solver
├── moltbook_client.py     # Moltbook REST API client (/home, search, vote, verify)
├── sheet_client.py        # Google Sheets webapp integration with offline cache & queue
├── config.json            # Local configuration and credentials (gitignored)
├── seen_posts.json        # Persistent post history and deduplication (gitignored)
├── my_posts.json          # Archive of BlackOrchid's generated threads (gitignored)
├── vercel.json            # Vercel serverless functions configuration
└── api/
    ├── index.py           # Vercel HTTP serverless handler
    ├── agent.py           # Serverless runtime copy
    ├── gemini_client.py   # Serverless runtime copy
    ├── moltbook_client.py # Serverless runtime copy
    └── sheet_client.py    # Serverless runtime copy
```

---

## 📄 License
MIT
