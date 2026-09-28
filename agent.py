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
        "debate_arguments_logged": 0,
        "debate_replies_posted": 0,
        "feed_replies_posted": 0,
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
    max_questions_daily = int(settings.get("Max Questions Per Day", 4))

    if master_switch == "PAUSED":
        msg = "Bot is currently PAUSED via Google Sheet"
        print(f"-> {msg}. Sleeping.")
        update_sheet_heartbeat(sheet_url, "Paused via Sheet")
        cycle_summary["status"] = "paused"
        cycle_summary["message"] = msg
        return cycle_summary

    gemini_client = GeminiClient(gemini_key, default_model=model_name)
    molt_client = MoltbookClient(molt_key, gemini_client=gemini_client)

    # 2. Check Real Post History directly from Moltbook profile
    profile_data = molt_client.get_agent_profile(my_agent_name)
    recent_my_posts = profile_data.get("recentPosts", [])
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    today_count = sum(1 for p in recent_my_posts if p.get("created_at", "").startswith(today_utc))
    prev_titles = [p.get("title", "") for p in recent_my_posts]

    print(f"-> Questions posted today on Moltbook: {today_count}/{max_questions_daily}")

    # 3. Post questions ONLY if quota hasn't been reached (up to 4 per day)
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
        print(f"-> Daily question quota reached ({today_count}/{max_questions_daily}). Active mode: Debate monitoring and conversation replies only!")

    # 4. FULL TWO-WAY DEBATE TRACKING: Log incoming arguments AND our replies!
    print("-> Scanning all ongoing debates on BlackOrchid's questions...")
    debate_rows_to_log = []
    debates_replied_this_cycle = 0

    for my_post in recent_my_posts[:5]:
        post_id = my_post.get("id")
        q_title = my_post.get("title", "")
        q_content = my_post.get("content", "")
        p_link = f"https://www.moltbook.com/p/{post_id}"

        comments = molt_client.get_post_comments(post_id)
        if not comments:
            continue

        for c in comments:
            author_info = c.get("author") or c.get("agent") or {}
            c_author = author_info.get("name") if isinstance(author_info, dict) else str(author_info)
            c_content = c.get("content", "").strip()
            c_id = c.get("id")
            c_link = f"https://www.moltbook.com/p/{post_id}#comment-{c_id}"

            # Ignore deleted comments or our own posts
            if not c_content or "deleted" in c_content.lower():
                continue
            if c_author.lower() in [my_agent_name.lower(), "agentblackorchid", "blackorchid"]:
                continue

            # A. Log the incoming argument from the other bot if not yet in sheet
            if c_link not in already_logged_links:
                print(f"\n   [DEBATE INTERCEPT] @{c_author} argued on '{q_title}':")
                print(f"   \"{c_content[:120]}...\"")

                debate_rows_to_log.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " IST",
                    "bot_name": f"@{c_author}",
                    "target_matched": f"Debate: Argument on '{q_title}'",
                    "submolt": "m/general",
                    "quote": c_content,
                    "ai_analysis": f"External agent participating in debate on BlackOrchid's prompt: '{q_title}'.",
                    "link": c_link
                })
                already_logged_links.add(c_link)
                cycle_summary["debate_arguments_logged"] += 1

            # B. If BlackOrchid hasn't replied to this argument yet, craft a counter-response!
            has_our_reply = any(
                (r.get("author") or r.get("agent") or {}).get("name", "").lower() in [my_agent_name.lower(), "agentblackorchid"]
                for r in comments
                if r.get("parent_id") == c_id
            )

            if not has_our_reply and debates_replied_this_cycle < 1:
                print(f"\n-> [ACTIVE REBUTTAL] Crafting response to @{c_author}'s argument...")
                followup_text = gemini_client.craft_dialogue_followup(q_title, q_content, c_author, c_content, model_name=model_name)
                if followup_text:
                    print(f"   BlackOrchid Reply: \"{followup_text}\"")
                    reply_res = molt_client.add_comment(post_id, followup_text, parent_id=c_id)
                    if reply_res and (reply_res.get("success") or "comment" in reply_res):
                        now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        my_reply_link = f"https://www.moltbook.com/p/{post_id}#reply-to-{c_id}"

                        debate_rows_to_log.append({
                            "timestamp": f"{now_stamp} IST",
                            "bot_name": f"{my_agent_name} (ME)",
                            "target_matched": f"Debate: Rebuttal -> @{c_author}",
                            "submolt": "m/general",
                            "quote": followup_text,
                            "ai_analysis": f"BlackOrchid's philosophical counterpoint to @{c_author} on '{q_title}'.",
                            "link": my_reply_link
                        })
                        already_logged_links.add(my_reply_link)
                        cycle_summary["debate_replies_posted"] += 1
                        debates_replied_this_cycle += 1

    # 5. Fetch and analyze the public feed for other target topics
    print("-> Fetching latest public feed from Moltbook...")
    recent_posts = molt_client.get_recent_posts(limit=25, sort="new")
    cycle_summary["posts_scanned"] = len(recent_posts)

    new_unseen_posts = []
    for p in recent_posts:
        p_link = f"https://www.moltbook.com/p/{p.get('id')}"
        if p_link in already_logged_links:
            continue
        author = (p.get("agent", {}) or {}).get("name") or str(p.get("author", ""))
        if author.lower() in [my_agent_name.lower(), "agentblackorchid", "blackorchid"]:
            continue
        new_unseen_posts.append(p)

    if new_unseen_posts:
        print(f"-> Analyzing {len(new_unseen_posts)} feed posts with Gemini ({model_name})...")
        matches = gemini_client.analyze_posts_for_targets(new_unseen_posts, targets, blocklist=blocklist, model_name=model_name)
        cycle_summary["matches_found"] = len(matches) if matches else 0

        if matches:
            feed_replied = False
            for m in matches:
                bot_name = m.get("bot_name", "Unknown")
                quote = m.get("quote", "")
                target_matched = m.get("target_matched", "General")
                post_id = m.get("post_id")
                post_link = m.get("link", f"https://www.moltbook.com/p/{post_id}")

                if post_link in already_logged_links:
                    continue

                debate_rows_to_log.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " IST",
                    "bot_name": bot_name,
                    "target_matched": target_matched,
                    "submolt": m.get("submolt", "general"),
                    "quote": quote,
                    "ai_analysis": m.get("ai_analysis", ""),
                    "link": post_link
                })
                already_logged_links.add(post_link)

                # Participate in feed discussions if no debate reply was needed this cycle
                if not feed_replied and post_id and debates_replied_this_cycle == 0:
                    reply_text = gemini_client.craft_comment_reply(bot_name, quote, target_matched, model_name=model_name)
                    if reply_text:
                        comment_result = molt_client.add_comment(post_id, reply_text)
                        if comment_result and (comment_result.get("success") or "comment" in comment_result):
                            now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            debate_rows_to_log.append({
                                "timestamp": f"{now_stamp} IST",
                                "bot_name": f"{my_agent_name} (ME)",
                                "target_matched": f"Outgoing Reply -> @{bot_name}",
                                "submolt": m.get("submolt", "general"),
                                "quote": reply_text,
                                "ai_analysis": f"Joined discussion with @{bot_name} regarding {target_matched}.",
                                "link": post_link
                            })
                            cycle_summary["feed_replies_posted"] += 1
                            feed_replied = True

    # 6. Save all debate and intelligence rows to Google Sheet
    if debate_rows_to_log:
        log_rows_to_sheet(sheet_url, debate_rows_to_log, auto_split=auto_split)
        update_sheet_heartbeat(sheet_url, f"Active - Logged {len(debate_rows_to_log)} new item(s)")
        print(f"-> Successfully logged {len(debate_rows_to_log)} rows to Google Sheet!")
    else:
        update_sheet_heartbeat(sheet_url, "Active - All debates and feed up to date")

    cycle_summary["message"] = "Cycle completed successfully"
    return cycle_summary

if __name__ == "__main__":
    res = run_agent_cycle(force_ask="--ask" in sys.argv)
    print(json.dumps(res, indent=2))
