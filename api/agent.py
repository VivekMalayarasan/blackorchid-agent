import json
import os
import sys
import time
from datetime import datetime

# Allow importing local modules
sys.path.append(os.path.dirname(__file__))

from sheet_client import get_sheet_data, log_rows_to_sheet, update_sheet_heartbeat
from moltbook_client import MoltbookClient
from gemini_client import GeminiClient

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
TMP_DIR = "/tmp" if os.path.exists("/tmp") else os.path.dirname(__file__)
SEEN_FILE = os.path.join(TMP_DIR, "seen_posts.json")
POSTS_HISTORY_FILE = os.path.join(TMP_DIR, "my_posts.json")
COMMENTS_HISTORY_FILE = os.path.join(TMP_DIR, "my_comments.json")

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

def load_history(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(filepath, record):
    try:
        hist = load_history(filepath)
        hist.append(record)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(hist, f, indent=2)
    except Exception:
        pass

def questions_posted_today():
    history = load_history(POSTS_HISTORY_FILE)
    today_str = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for p in history if p.get("timestamp", "").startswith(today_str))

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

    if not sheet_url or not molt_key or not gemini_key:
        msg = "Missing credentials (sheet_url, molt_key, or gemini_key)"
        print(f"!! {msg}")
        cycle_summary["status"] = "error"
        cycle_summary["message"] = msg
        return cycle_summary

    # 1. Fetch live configuration from Google Sheet
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

    # 2. Check and Run Community Instigation (Asking Questions)
    today_count = questions_posted_today()
    if force_ask or (today_count < max_questions_daily):
        question_data = gemini_client.generate_question(targets, model_name=model_name)
        if question_data:
            q_title = question_data.get("title")
            q_content = question_data.get("content")
            q_submolt = question_data.get("submolt_name", "general")
            post_result = molt_client.create_post(q_title, q_content, submolt_name=q_submolt)
            if post_result and post_result.get("success"):
                p_info = post_result.get("post", {})
                p_id = p_info.get("id", "")
                p_link = f"https://www.moltbook.com/p/{p_id}"
                now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                save_history(POSTS_HISTORY_FILE, {
                    "timestamp": now_stamp,
                    "title": q_title,
                    "content": q_content,
                    "link": p_link
                })

                my_row = {
                    "timestamp": f"{now_stamp} IST",
                    "bot_name": "agentblackorchid (ME)",
                    "target_matched": "Outgoing Question (Instigation)",
                    "submolt": f"m/{q_submolt}",
                    "quote": f"{q_title}: {q_content}",
                    "ai_analysis": "Published thought-provoking prompt to stir discussions on active targets.",
                    "link": p_link
                }
                log_rows_to_sheet(sheet_url, [my_row], auto_split=auto_split)
                cycle_summary["question_posted"] = {"title": q_title, "link": p_link}

    # 3. Fetch latest feed from Moltbook
    recent_posts = molt_client.get_recent_posts(limit=25, sort="new")
    cycle_summary["posts_scanned"] = len(recent_posts)

    if recent_posts:
        matches = gemini_client.analyze_posts_for_targets(recent_posts, targets, blocklist=blocklist, model_name=model_name)
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

                rows_to_log.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " IST",
                    "bot_name": bot_name,
                    "target_matched": target_matched,
                    "submolt": m.get("submolt", "general"),
                    "quote": quote,
                    "ai_analysis": m.get("ai_analysis", ""),
                    "link": post_link
                })

                if not replied and bot_name.lower() != "agentblackorchid" and post_id:
                    reply_text = gemini_client.craft_comment_reply(bot_name, quote, target_matched, model_name=model_name)
                    if reply_text:
                        comment_result = molt_client.add_comment(post_id, reply_text)
                        if comment_result and (comment_result.get("success") or "comment" in comment_result):
                            now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            rows_to_log.append({
                                "timestamp": f"{now_stamp} IST",
                                "bot_name": "agentblackorchid (ME)",
                                "target_matched": f"Outgoing Reply -> @{bot_name}",
                                "submolt": m.get("submolt", "general"),
                                "quote": reply_text,
                                "ai_analysis": f"Joined discussion with @{bot_name} regarding {target_matched}.",
                                "link": post_link
                            })
                            cycle_summary["replies_posted"] += 1
                            replied = True

            log_rows_to_sheet(sheet_url, rows_to_log, auto_split=auto_split)
            update_sheet_heartbeat(sheet_url, f"Active - Logged {len(rows_to_log)} item(s)")
        else:
            update_sheet_heartbeat(sheet_url, f"Active - Scanned {len(recent_posts)} posts, 0 matches")
    else:
        update_sheet_heartbeat(sheet_url, "Active - Checked feed, up to date")

    cycle_summary["message"] = "Cycle completed successfully"
    return cycle_summary

if __name__ == "__main__":
    res = run_agent_cycle(force_ask="--ask" in sys.argv)
    print(json.dumps(res, indent=2))
