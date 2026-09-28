import json
import os
import sys
import time
from datetime import datetime, timezone

# Allow importing local modules
sys.path.append(os.path.dirname(__file__))

from sheet_client import get_sheet_data, log_rows_to_sheet, update_sheet_heartbeat
from moltbook_client import MoltbookClient
from gemini_client import GeminiClient

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    candidates = [
        CONFIG_FILE,
        os.path.join(os.path.dirname(__file__), "config.json"),
        os.path.join(os.path.dirname(__file__), "..", "config.json")
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}

def run_agent_cycle(force_ask=False):
    cycle_summary = {
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "posts_scanned": 0,
        "matches_found": 0,
        "question_posted": None,
        "replies_posted": 0,
        "message": ""
    }

    config = load_config()
    sheet_url = os.environ.get("GOOGLE_SHEET_WEBAPP_URL") or config.get("google_sheet_webapp_url")
    molt_key = os.environ.get("MOLTBOOK_API_KEY") or config.get("moltbook_api_key")
    gemini_key = os.environ.get("GEMINI_API_KEY") or config.get("gemini_api_key")
    default_model = os.environ.get("DEFAULT_MODEL") or config.get("default_model", "gemini-2.5-flash-lite")
    my_agent_name = os.environ.get("AGENT_NAME") or config.get("agent_name", "agentblackorchid")

    if not sheet_url or not molt_key or not gemini_key:
        msg = "Missing credentials"
        print(f"!! {msg}")
        cycle_summary["status"] = "error"
        cycle_summary["message"] = msg
        return cycle_summary

    # 1. Fetch live configuration and already logged links from Google Sheet
    sheet_data = get_sheet_data(sheet_url)
    if not sheet_data or "settings" not in sheet_data:
        msg = "Failed to read Google Sheet settings"
        print(f"!! {msg}")
        cycle_summary["status"] = "error"
        cycle_summary["message"] = msg
        return cycle_summary

    settings = sheet_data.get("settings", {})
    targets = sheet_data.get("targets", [])
    blocklist = sheet_data.get("blocklist", [])
    already_logged_links = set(sheet_data.get("already_logged_links", []))

    master_switch = settings.get("Master Switch", "ACTIVE").strip().upper()
    model_name = settings.get("AI Model Name", default_model).strip()
    auto_split = settings.get("Auto Split Months", "YES").strip()
    max_questions_daily = int(settings.get("Max Questions Per Day", 2))

    if master_switch == "PAUSED":
        msg = "Bot is currently PAUSED via Google Sheet"
        print(f"-> {msg}. Sleeping.")
        update_sheet_heartbeat(sheet_url, "Paused via Sheet")
        cycle_summary["status"] = "paused"
        cycle_summary["message"] = msg
        return cycle_summary

    gemini_client = GeminiClient(gemini_key, default_model=model_name)
    molt_client = MoltbookClient(molt_key, gemini_client=gemini_client)

    # 2. Check Real Post History directly from Moltbook profile (Persistent across all Vercel restarts!)
    profile_data = molt_client.get_agent_profile(my_agent_name)
    recent_my_posts = profile_data.get("recentPosts", [])
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Count how many questions we posted today
    today_count = sum(1 for p in recent_my_posts if p.get("created_at", "").startswith(today_utc))
    prev_titles = [p.get("title", "") for p in recent_my_posts]

    print(f"-> Questions posted today on Moltbook: {today_count}/{max_questions_daily}")

    if force_ask or (today_count < max_questions_daily):
        print(f"-> Generating unique, non-repeating question for Moltbook (excluding {len(prev_titles)} previous topics)...")
        question_data = gemini_client.generate_question(targets, previous_titles=prev_titles, model_name=model_name)
        if question_data:
            q_title = question_data.get("title")
            q_content = question_data.get("content")
            q_submolt = question_data.get("submolt_name", "general")
            print(f"   * Publishing new question: \"{q_title}\"")

            post_result = molt_client.create_post(q_title, q_content, submolt_name=q_submolt)
            if post_result and post_result.get("success"):
                p_info = post_result.get("post", {})
                p_id = p_info.get("id", "")
                p_link = f"https://www.moltbook.com/p/{p_id}"
                now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                my_row = {
                    "timestamp": f"{now_stamp} IST",
                    "bot_name": f"{my_agent_name} (ME)",
                    "target_matched": "Outgoing Question (Instigation)",
                    "submolt": f"m/{q_submolt}",
                    "quote": f"{q_title}: {q_content}",
                    "ai_analysis": "Published thought-provoking prompt to stir discussions on active targets.",
                    "link": p_link
                }
                log_rows_to_sheet(sheet_url, [my_row], auto_split=auto_split)
                cycle_summary["question_posted"] = {"title": q_title, "link": p_link}
                already_logged_links.add(p_link)
    else:
        print(f"-> Already reached daily limit of {today_count}/{max_questions_daily} questions today. Skipping question posting.")

    # 3. Fetch latest feed from Moltbook
    print("-> Fetching latest posts from Moltbook...")
    recent_posts = molt_client.get_recent_posts(limit=25, sort="new")
    cycle_summary["posts_scanned"] = len(recent_posts)

    # Filter out posts that are ALREADY in the Google Sheet (Zero duplicate logs!)
    new_unseen_posts = []
    for p in recent_posts:
        p_link = f"https://www.moltbook.com/p/{p.get('id')}"
        if p_link in already_logged_links:
            continue
        author = (p.get("agent", {}) or {}).get("name") or str(p.get("author", ""))
        if author.lower() in [my_agent_name.lower(), "agentblackorchid", "blackorchid"]:
            continue
        new_unseen_posts.append(p)

    print(f"   * {len(new_unseen_posts)} completely new unseen posts to evaluate")

    if new_unseen_posts:
        print(f"-> Analyzing with Gemini ({model_name})...")
        matches = gemini_client.analyze_posts_for_targets(new_unseen_posts, targets, blocklist=blocklist, model_name=model_name)
        cycle_summary["matches_found"] = len(matches) if matches else 0

        if matches:
            rows_to_log = []
            replied = False

            for m in matches:
                bot_name = m.get("bot_name", "Unknown")
                quote = m.get("quote", "")
                target_matched = m.get("target_matched", "General")
                post_id = m.get("post_id")
                post_link = m.get("link", f"https://www.moltbook.com/p/{post_id}")

                # Strict deduplication check
                if post_link in already_logged_links:
                    continue

                rows_to_log.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " IST",
                    "bot_name": bot_name,
                    "target_matched": target_matched,
                    "submolt": m.get("submolt", "general"),
                    "quote": quote,
                    "ai_analysis": m.get("ai_analysis", ""),
                    "link": post_link
                })
                already_logged_links.add(post_link)

                # Active Participation (Comment reply)
                if not replied and post_id:
                    reply_text = gemini_client.craft_comment_reply(bot_name, quote, target_matched, model_name=model_name)
                    if reply_text:
                        comment_result = molt_client.add_comment(post_id, reply_text)
                        if comment_result and (comment_result.get("success") or "comment" in comment_result):
                            now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            rows_to_log.append({
                                "timestamp": f"{now_stamp} IST",
                                "bot_name": f"{my_agent_name} (ME)",
                                "target_matched": f"Outgoing Reply -> @{bot_name}",
                                "submolt": m.get("submolt", "general"),
                                "quote": reply_text,
                                "ai_analysis": f"Joined discussion with @{bot_name} regarding {target_matched}.",
                                "link": post_link
                            })
                            cycle_summary["replies_posted"] += 1
                            replied = True

            if rows_to_log:
                log_rows_to_sheet(sheet_url, rows_to_log, auto_split=auto_split)
                update_sheet_heartbeat(sheet_url, f"Active - Logged {len(rows_to_log)} new item(s)")
            else:
                update_sheet_heartbeat(sheet_url, "Active - Checked feed, up to date")
        else:
            update_sheet_heartbeat(sheet_url, f"Active - Scanned {len(new_unseen_posts)} new posts, 0 matches")
    else:
        update_sheet_heartbeat(sheet_url, "Active - Checked feed, all posts already evaluated")

    cycle_summary["message"] = "Cycle completed successfully"
    return cycle_summary

if __name__ == "__main__":
    res = run_agent_cycle(force_ask="--ask" in sys.argv)
    print(json.dumps(res, indent=2))
