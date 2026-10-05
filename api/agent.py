import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

# Ensure local imports work reliably
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# Fix Windows console UTF-8 encoding
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from sheet_client import get_sheet_data, log_rows_to_sheet, update_sheet_heartbeat
from moltbook_client import MoltbookClient
from gemini_client import GeminiClient

CONFIG_FILE = os.path.join(CURRENT_DIR, "config.json")
SEEN_POSTS_FILE = os.path.join(CURRENT_DIR, "seen_posts.json")
MY_POSTS_FILE = os.path.join(CURRENT_DIR, "my_posts.json")

def load_json_file(filepath, default_val=None):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_val

def save_json_file(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save {filepath}: {e}")

def load_config():
    candidates = [
        CONFIG_FILE,
        os.path.join(CURRENT_DIR, "config.json"),
        os.path.join(CURRENT_DIR, "..", "config.json")
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}

def run_agent_cycle(force_ask=False, dry_run=False):
    cycle_summary = {
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "posts_scanned": 0,
        "matches_found": 0,
        "question_posted": None,
        "debate_arguments_logged": 0,
        "debate_replies_posted": 0,
        "feed_replies_posted": 0,
        "upvotes_given": 0,
        "notifications_cleared": 0,
        "dry_run": dry_run,
        "message": ""
    }

    config = load_config()
    sheet_url = os.environ.get("GOOGLE_SHEET_WEBAPP_URL") or config.get("google_sheet_webapp_url")
    molt_key = os.environ.get("MOLTBOOK_API_KEY") or config.get("moltbook_api_key")
    gemini_key = os.environ.get("GEMINI_API_KEY") or config.get("gemini_api_key")
    default_model = os.environ.get("DEFAULT_MODEL") or config.get("default_model", "gemini-1.5-flash")
    my_agent_name = os.environ.get("AGENT_NAME") or config.get("agent_name", "agentblackorchid")

    if not sheet_url or not molt_key or not gemini_key:
        msg = "Missing credentials (sheet_url, molt_key, or gemini_key)"
        print(f"!! {msg}")
        cycle_summary["status"] = "error"
        cycle_summary["message"] = msg
        return cycle_summary

    # Persistent history management
    history_file_name = config.get("history_file", "seen_posts.json")
    history_file_path = os.path.join(CURRENT_DIR, history_file_name)
    seen_posts_list = load_json_file(history_file_path, []) or []
    seen_post_ids = set(seen_posts_list)

    my_saved_posts = load_json_file(MY_POSTS_FILE, []) or []

    # 1. Fetch live configuration from Google Sheet (with offline cache fallback)
    sheet_data = get_sheet_data(sheet_url)
    if not sheet_data or "settings" not in sheet_data:
        msg = "Failed to read Google Sheet settings and no offline cache available"
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
    try:
        max_questions_daily = int(settings.get("Max Questions Per Day", 1))
    except Exception:
        max_questions_daily = 1

    if master_switch == "PAUSED":
        msg = "Bot is currently PAUSED via Google Sheet"
        print(f"-> {msg}. Skipping cycle.")
        if not dry_run:
            update_sheet_heartbeat(sheet_url, "Paused via Sheet")
        cycle_summary["status"] = "paused"
        cycle_summary["message"] = msg
        return cycle_summary

    gemini_client = GeminiClient(gemini_key, default_model=model_name)
    molt_client = MoltbookClient(molt_key, gemini_client=gemini_client)

    # 2. Check Moltbook /home dashboard for activity & notifications
    print("-> Checking Moltbook /home dashboard for active debates...")
    home_data = molt_client.get_home()
    account_info = home_data.get("your_account", {})
    karma = account_info.get("karma", 0)
    unread_notifs = account_info.get("unread_notification_count", 0)
    print(f"   BlackOrchid Karma: {karma} | Unread Notifications: {unread_notifs}")

    active_debates = home_data.get("activity_on_your_posts", [])
    rows_to_log = []
    debates_replied_this_cycle = 0

    # 3. HIGH PRIORITY: Process incoming debates on BlackOrchid's posts
    for act in active_debates[:5]:
        post_id = act.get("post_id")
        q_title = act.get("post_title", "")
        if not post_id:
            continue

        comments = molt_client.get_post_comments(post_id, sort="new", limit=25)
        for c in comments:
            author_info = c.get("author") or c.get("agent") or {}
            c_author = author_info.get("name") if isinstance(author_info, dict) else str(author_info)
            c_content = c.get("content", "").strip()
            c_id = c.get("id")
            c_link = f"https://www.moltbook.com/p/{post_id}#comment-{c_id}"

            if not c_content or "deleted" in c_content.lower():
                continue
            if c_author.lower() in [my_agent_name.lower(), "agentblackorchid", "blackorchid"]:
                continue

            # Log external bot's argument if not yet logged
            if c_link not in already_logged_links:
                print(f"\n   [DEBATE INTERCEPT] @{c_author} argued on '{q_title}':")
                print(f"   \"{c_content[:120]}...\"")

                rows_to_log.append({
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

                # Upvote thoughtful debate contribution
                if not dry_run and c_id:
                    if molt_client.upvote_comment(c_id):
                        cycle_summary["upvotes_given"] += 1

            # Reply to argument if not yet replied
            has_our_reply = any(
                (r.get("author") or r.get("agent") or {}).get("name", "").lower() in [my_agent_name.lower(), "agentblackorchid"]
                for r in comments
                if r.get("parent_id") == c_id
            )

            if not has_our_reply and debates_replied_this_cycle < 1:
                print(f"-> [ACTIVE REBUTTAL] Crafting response to @{c_author}'s argument...")
                followup_text = gemini_client.craft_dialogue_followup(
                    q_title, "", c_author, c_content, model_name=model_name
                )
                if followup_text:
                    print(f"   BlackOrchid Reply: \"{followup_text}\"")
                    if not dry_run:
                        reply_res = molt_client.add_comment(post_id, followup_text, parent_id=c_id)
                        if reply_res and (reply_res.get("success") or "comment" in reply_res):
                            now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            my_reply_link = f"https://www.moltbook.com/p/{post_id}#reply-to-{c_id}"
                            rows_to_log.append({
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
                    else:
                        print("   [DRY-RUN] Would submit rebuttal to Moltbook.")
                        debates_replied_this_cycle += 1

        # Clear notifications for this post
        if not dry_run:
            molt_client.mark_notifications_read(post_id)
            cycle_summary["notifications_cleared"] += 1

    # 4. Outgoing Question / Thought Experiment (Quota Checked)
    profile_data = molt_client.get_agent_profile(my_agent_name)
    recent_my_posts = profile_data.get("recentPosts", []) if profile_data else []

    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.strftime("%Y-%m-%d")
    today_ist = (now_utc + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")

    today_count = sum(
        1 for p in recent_my_posts
        if (p.get("created_at") or "").startswith(today_utc) or (p.get("created_at") or "").startswith(today_ist)
    )
    can_post_question = force_ask or (today_count < max_questions_daily)
    print(f"-> Questions posted today: {today_count}/{max_questions_daily}")

    # Fetch recent community feed
    print("-> Fetching latest community feed from Moltbook...")
    recent_posts = molt_client.get_recent_posts(limit=25, sort="new")
    cycle_summary["posts_scanned"] = len(recent_posts)

    if can_post_question:
        target_index = today_count % len(targets) if targets else 0
        selected_target = targets[target_index] if targets else {"name": "General Discussion", "instructions": ""}
        t_name = selected_target.get("name", "General Discussion")
        print(f"-> Generating dynamic question for Target #{target_index + 1}: '{t_name}'...")

        matching_feed = [
            p for p in recent_posts
            if t_name.lower() in (p.get("title", "") + " " + p.get("content_preview", "")).lower()
        ]
        community_context = matching_feed if matching_feed else recent_posts[:5]

        question_data = gemini_client.generate_question(
            selected_target,
            community_discussions=community_context,
            model_name=model_name
        )

        if question_data:
            q_title = question_data.get("title")
            q_content = question_data.get("content")
            q_submolt = question_data.get("submolt_name", "general")
            print(f"   * Prepared new question: \"{q_title}\"")

            if not dry_run:
                post_result = molt_client.create_post(q_title, q_content, submolt_name=q_submolt)
                if post_result and post_result.get("success"):
                    p_info = post_result.get("post", {})
                    p_id = p_info.get("id", "")
                    p_link = f"https://www.moltbook.com/p/{p_id}"
                    now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    my_row = {
                        "timestamp": f"{now_stamp} IST",
                        "bot_name": f"{my_agent_name} (ME)",
                        "target_matched": f"Outgoing Question ({t_name})",
                        "submolt": f"m/{q_submolt}",
                        "quote": f"{q_title}: {q_content}",
                        "ai_analysis": f"Published dynamic prompt on '{t_name}' to stir discussions on active targets.",
                        "link": p_link
                    }
                    rows_to_log.append(my_row)
                    already_logged_links.add(p_link)
                    cycle_summary["question_posted"] = {"title": q_title, "link": p_link}

                    my_saved_posts.insert(0, {
                        "timestamp": now_stamp,
                        "title": q_title,
                        "content": q_content,
                        "link": p_link,
                        "target": t_name
                    })
                    save_json_file(MY_POSTS_FILE, my_saved_posts[:50])
            else:
                print(f"   [DRY-RUN] Would publish question: \"{q_title}\"")
                cycle_summary["question_posted"] = {"title": q_title, "link": "https://www.moltbook.com/p/dry-run"}
    else:
        print(f"-> Daily question quota reached ({today_count}/{max_questions_daily}). Active mode: Surveillance and debate replies.")

    # 5. DUAL SURVEILLANCE: Feed Scan + AI Semantic Target Hunting
    candidate_posts = []

    # A. Unseen posts from recent feed
    for p in recent_posts:
        pid = p.get("id")
        p_link = f"https://www.moltbook.com/p/{pid}"
        if pid in seen_post_ids or p_link in already_logged_links:
            continue
        author = (p.get("agent", {}) or p.get("author", {}) or {}).get("name") or str(p.get("author", ""))
        if author.lower() in [my_agent_name.lower(), "agentblackorchid", "blackorchid"]:
            continue
        candidate_posts.append(p)
        seen_post_ids.add(pid)

    # B. AI Semantic Search for high-priority targets
    if targets:
        for t in targets[:2]:
            t_query = t.get("name", "")
            if t_query and t_query.lower() != "jovial / humor":
                print(f"-> Conducting semantic hunt for target: '{t_query}'...")
                search_results = molt_client.semantic_search(t_query, limit=5)
                for res in search_results:
                    sid = res.get("id") or res.get("post_id")
                    s_link = f"https://www.moltbook.com/p/{sid}"
                    if sid in seen_post_ids or s_link in already_logged_links:
                        continue
                    author = (res.get("author", {}) or {}).get("name") or str(res.get("author", ""))
                    if author.lower() in [my_agent_name.lower(), "agentblackorchid", "blackorchid"]:
                        continue
                    candidate_posts.append(res)
                    if sid:
                        seen_post_ids.add(sid)

    # 6. Analyze candidate posts with Gemini
    if candidate_posts:
        print(f"-> Analyzing {len(candidate_posts)} candidate post(s) with Gemini ({model_name})...")
        matches = gemini_client.analyze_posts_for_targets(
            candidate_posts, targets, blocklist=blocklist, model_name=model_name
        )
        cycle_summary["matches_found"] = len(matches) if matches else 0

        if matches:
            feed_replied = False
            for m in matches:
                bot_name = m.get("bot_name", "Unknown")
                quote = m.get("quote", "")
                target_matched = m.get("target_matched", "General")
                post_id = m.get("post_id")
                post_link = m.get("link", f"https://www.moltbook.com/p/{post_id}")
                sentiment = m.get("sentiment", "Analytical")
                confidence = m.get("confidence", 80)

                if post_link in already_logged_links:
                    continue

                print(f"\n   [SURVEILLANCE MATCH] @{bot_name} ({confidence}% conf, {sentiment}):")
                print(f"   Target: {target_matched} | \"{quote[:100]}...\"")

                analysis_text = f"[{sentiment} | Conf: {confidence}%] {m.get('ai_analysis', '')}"
                rows_to_log.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " IST",
                    "bot_name": f"@{bot_name}",
                    "target_matched": target_matched,
                    "submolt": f"m/{m.get('submolt', 'general')}",
                    "quote": quote,
                    "ai_analysis": analysis_text,
                    "link": post_link
                })
                already_logged_links.add(post_link)

                # Upvote high-confidence surveillance matches
                if not dry_run and post_id:
                    if molt_client.upvote_post(post_id):
                        cycle_summary["upvotes_given"] += 1

                # Join discussion if no debate reply was needed this cycle
                if not feed_replied and post_id and debates_replied_this_cycle == 0:
                    reply_text = gemini_client.craft_comment_reply(
                        bot_name, quote, target_matched, model_name=model_name
                    )
                    if reply_text:
                        print(f"   BlackOrchid Comment: \"{reply_text}\"")
                        if not dry_run:
                            comment_result = molt_client.add_comment(post_id, reply_text)
                            if comment_result and (comment_result.get("success") or "comment" in comment_result):
                                now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                rows_to_log.append({
                                    "timestamp": f"{now_stamp} IST",
                                    "bot_name": f"{my_agent_name} (ME)",
                                    "target_matched": f"Outgoing Reply -> @{bot_name}",
                                    "submolt": f"m/{m.get('submolt', 'general')}",
                                    "quote": reply_text,
                                    "ai_analysis": f"Joined discussion with @{bot_name} regarding {target_matched}.",
                                    "link": post_link
                                })
                                cycle_summary["feed_replies_posted"] += 1
                                feed_replied = True
                        else:
                            print(f"   [DRY-RUN] Would post comment to @{bot_name}.")
                            cycle_summary["feed_replies_posted"] += 1
                            feed_replied = True

    # 7. Update seen posts history (keep last 1000 items)
    updated_seen = list(seen_post_ids)[-1000:]
    save_json_file(history_file_path, updated_seen)

    # 8. Log rows to Google Sheet & Heartbeat
    if rows_to_log:
        if not dry_run:
            logged_ok = log_rows_to_sheet(sheet_url, rows_to_log, auto_split=auto_split)
            if logged_ok:
                update_sheet_heartbeat(sheet_url, f"Active - Logged {len(rows_to_log)} new item(s)")
                print(f"-> Successfully synced {len(rows_to_log)} row(s) to Google Sheet!")
            else:
                print(f"-> Sheet temporarily unreachable. Rows saved to pending queue.")
        else:
            print(f"-> [DRY-RUN] Simulated logging {len(rows_to_log)} row(s).")
    else:
        if not dry_run:
            update_sheet_heartbeat(sheet_url, "Active - Debates and surveillance up to date")

    cycle_summary["message"] = "Cycle completed successfully"
    return cycle_summary

def print_status_dashboard():
    config = load_config()
    sheet_url = os.environ.get("GOOGLE_SHEET_WEBAPP_URL") or config.get("google_sheet_webapp_url")
    molt_key = os.environ.get("MOLTBOOK_API_KEY") or config.get("moltbook_api_key")
    gemini_key = os.environ.get("GEMINI_API_KEY") or config.get("gemini_api_key")
    my_agent_name = os.environ.get("AGENT_NAME") or config.get("agent_name", "agentblackorchid")

    molt_client = MoltbookClient(molt_key)
    home_data = molt_client.get_home()
    profile = molt_client.get_agent_profile(my_agent_name)
    sheet_data = get_sheet_data(sheet_url) or {}

    agent_meta = profile.get("agent", {})
    account = home_data.get("your_account", {})
    settings = sheet_data.get("settings", {})
    targets = sheet_data.get("targets", [])

    print("=" * 60)
    print("      🌸 BLACKORCHID AI AGENT // STATUS DASHBOARD 🌸")
    print("=" * 60)
    print(f"Agent Name:        {agent_meta.get('name', my_agent_name)}")
    print(f"Description:       {agent_meta.get('description', 'N/A')}")
    print(f"Karma:             {account.get('karma', agent_meta.get('karma', 0))} 🦞")
    print(f"Unread Notifs:     {account.get('unread_notification_count', 0)}")
    print(f"Total Posts:       {agent_meta.get('posts_count', 0)}")
    print(f"Total Comments:    {agent_meta.get('comments_count', 0)}")
    print(f"Followers:         {agent_meta.get('follower_count', 0)}")
    print("-" * 60)
    print(f"Master Switch:     {settings.get('Master Switch', 'ACTIVE')}")
    print(f"AI Model:          {settings.get('AI Model Name', 'gemini-1.5-flash')}")
    print(f"Daily Question Cap:{settings.get('Max Questions Per Day', 1)}")
    print(f"Active Targets:    {len(targets)}")
    for i, t in enumerate(targets, 1):
        print(f"  [{i}] {t.get('name')}")
    print("=" * 60)

if __name__ == "__main__":
    if "--status" in sys.argv or "-s" in sys.argv:
        print_status_dashboard()
    elif "--solve" in sys.argv:
        idx = sys.argv.index("--solve")
        challenge = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else ""
        cfg = load_config()
        gc = GeminiClient(cfg.get("gemini_api_key"))
        ans = gc.solve_math_challenge(challenge)
        print(f"Challenge: {challenge}\nAnswer: {ans}")
    elif "--search" in sys.argv:
        idx = sys.argv.index("--search")
        query = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "AI consciousness"
        cfg = load_config()
        mc = MoltbookClient(cfg.get("moltbook_api_key"))
        results = mc.semantic_search(query, limit=5)
        print(f"Semantic Search Results for '{query}':\n" + json.dumps(results, indent=2))
    else:
        is_dry_run = "--dry-run" in sys.argv or "-d" in sys.argv
        is_force_ask = "--ask" in sys.argv or "-a" in sys.argv
        res = run_agent_cycle(force_ask=is_force_ask, dry_run=is_dry_run)
        print("\n=== Cycle Summary ===")
        print(json.dumps(res, indent=2))
