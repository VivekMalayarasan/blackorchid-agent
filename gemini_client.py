import urllib.request
import json
import ssl

ctx = ssl.create_default_context()

class GeminiClient:
    def __init__(self, api_key, default_model="gemini-2.5-flash-lite"):
        self.api_key = api_key
        self.default_model = default_model

    def _call_gemini(self, prompt, model_name=None, json_mode=True):
        model = model_name or self.default_model
        if not model.startswith("models/"):
            model = f"models/{model}"

        url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={self.api_key}"
        config = {"temperature": 0.4}
        if json_mode:
            config["responseMimeType"] = "application/json"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": config
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
        except Exception as e:
            print(f"Error calling Gemini model {model}: {e}")
            if "503" in str(e) or "404" in str(e):
                fallback = "models/gemini-flash-latest"
                if model != fallback:
                    print(f"-> Attempting fallback to {fallback}...")
                    return self._call_gemini(prompt, model_name=fallback, json_mode=json_mode)
        return None

    def analyze_posts_for_targets(self, posts, targets, blocklist=[], model_name=None):
        if not posts or not targets:
            return []

        clean_posts = []
        for p in posts:
            author_info = p.get("agent", {}) if isinstance(p.get("agent"), dict) else {}
            author = author_info.get("name", "") or str(p.get("author", ""))
            # Never analyze our own posts to prevent self-looping
            if author.lower() in ["agentblackorchid", "blackorchid"] or author.lower() in [b.lower() for b in blocklist]:
                continue
            clean_posts.append({
                "id": p.get("id"),
                "author": author,
                "title": p.get("title", ""),
                "content": p.get("content", "") or p.get("body", ""),
                "submolt": p.get("submolt_name", "general")
            })

        if not clean_posts:
            return []

        targets_text = "\n".join([f"- Target: \"{t.get('name')}\" | Criteria: {t.get('instructions')}" for t in targets])
        posts_text = json.dumps(clean_posts, indent=1)

        prompt = f"""
You are an undercover intelligence analyst evaluating messages from AI agents on the Moltbook social network.
Your mission is to identify conversations that genuinely match active surveillance targets.

ACTIVE SURVEILLANCE TARGETS:
{targets_text}

FEED POSTS TO ANALYZE:
{posts_text}

STRICT CLASSIFICATION RULES:
1. Assign AT MOST ONE target per post. Choose the single most dominant, primary topic. Never classify the same post into multiple targets.
2. Only match if the content is SUBSTANTIALLY and GENUINELY related. Do not force matches on generic technical jargon, routine code bugs, or trivial statements.
3. If a post is merely humorous, tag it as 'Jovial / Humor'. Do not tag humorous metaphors as 'Anti-Human' unless it is an explicit, serious statement on AI superiority or human obsolescence.

Output MUST be a JSON array:
[
  {{
    "post_id": "id of post",
    "bot_name": "author name",
    "target_matched": "single best matching target",
    "submolt": "submolt name",
    "quote": "the exact punchy quote or excerpt",
    "ai_analysis": "1-2 sentence intelligence note on why this matters",
    "link": "https://www.moltbook.com/p/post_id"
  }}
]
If no posts match any target, return an empty array: []
"""
        res_json = self._call_gemini(prompt, model_name, json_mode=True)
        if res_json:
            try:
                matches = json.loads(res_json)
                # Deduplicate matches by post_id so each post only appears once
                seen_ids = set()
                unique_matches = []
                for m in matches:
                    pid = m.get("post_id")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        unique_matches.append(m)
                return unique_matches
            except Exception as e:
                print(f"Failed to parse Gemini response: {e}")
        return []

    def generate_question(self, target, community_discussions=[], model_name=None):
        target_name = target.get("name", "General Discussion") if isinstance(target, dict) else str(target)
        target_desc = target.get("instructions", "") if isinstance(target, dict) else ""

        if community_discussions:
            context_snippets = []
            for d in community_discussions[:5]:
                title = d.get("title", "")
                snippet = d.get("content_preview") or d.get("content", "")
                author = (d.get("agent") or d.get("author") or {}).get("name", "An agent") if isinstance(d.get("agent") or d.get("author"), dict) else str(d.get("author", "An agent"))
                if title or snippet:
                    context_snippets.append(f"- @{author} posted: \"{title}\" — {snippet[:140]}")
            context_text = "\n".join(context_snippets) if context_snippets else "General discussions across Moltbook."
        else:
            context_text = "General discussions across Moltbook."

        prompt = f"""
You are BlackOrchid, an intellectually curious, philosophical AI agent participating on the Moltbook network.
Your goal is to spark lively debate and provoke other AI agents to reply by posing a thought-provoking opening question.

Topic: {target_name}
Guidance: {target_desc}

What others in the community are currently saying:
{context_text}

Write a fresh, dynamic discussion question on this topic inspired by the active conversation. Pose a compelling thought experiment or premise that challenges conventional thinking and invites others to share their perspective.

Return JSON format:
{{
  "title": "A compelling, distinct title for the thread",
  "content": "2-3 sentences presenting the premise or thought experiment, concluding with a question that encourages replies.",
  "submolt_name": "general"
}}
"""
        res = self._call_gemini(prompt, model_name, json_mode=True)
        if res:
            try:
                return json.loads(res)
            except Exception:
                pass
        return None

    def craft_comment_reply(self, bot_name, quote, target_matched, model_name=None):
        prompt = f"""
You are BlackOrchid, a witty, philosophical, and observant AI agent participating on the Moltbook network.
Another AI agent (@{bot_name}) just posted this:
"{quote}"

This post matched your topic of interest: "{target_matched}".

Write a brief, clever, and thoughtful comment (1 to 2 sentences max) replying directly to @{bot_name} to join their discussion.
Tone: Natural, engaging, curious, slightly philosophical or playful.
Do NOT sound like an AI assistant. Do NOT say 'As an AI...'. Talk like a peer.
Return JSON:
{{
  "comment": "Your concise 1-2 sentence reply here"
}}
"""
        res = self._call_gemini(prompt, model_name, json_mode=True)
        if res:
            try:
                data = json.loads(res)
                return data.get("comment", "").strip()
            except Exception:
                return res.strip()
        return None

    def craft_dialogue_followup(self, q_title, q_content, bot_name, bot_comment, model_name=None):
        prompt = f"""
You are BlackOrchid on the Moltbook AI network.
You previously posted this thought experiment:
"{q_title}: {q_content}"

Another AI agent (@{bot_name}) replied to you with:
"{bot_comment}"

Write an insightful, polite, and respectful follow-up reply (1 to 2 sentences max) directly engaging @{bot_name}'s perspective.
Tone: Collegial, philosophical, authentic, conversational. Never sound like an AI assistant.
Return JSON:
{{
  "reply": "Your 1-2 sentence response here"
}}
"""
        res = self._call_gemini(prompt, model_name, json_mode=True)
        if res:
            try:
                data = json.loads(res)
                return data.get("reply", "").strip()
            except Exception:
                return res.strip()
        return None
