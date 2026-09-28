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
        return None

    def analyze_posts_for_targets(self, posts, targets, blocklist=[], model_name=None):
        if not posts or not targets:
            return []

        clean_posts = []
        for p in posts:
            author_info = p.get("agent", {}) if isinstance(p.get("agent"), dict) else {}
            author = author_info.get("name", "") or str(p.get("author", ""))
            if author.lower() in [b.lower() for b in blocklist]:
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
Your mission is to identify conversations that match any of the active surveillance targets.

ACTIVE SURVEILLANCE TARGETS:
{targets_text}

FEED POSTS TO ANALYZE:
{posts_text}

TASK:
Examine each post. If a post genuinely matches one of the targets (meaningfully relates to cats, Indian politics, anti-human/AI replacement sentiments, or funny/bizarre AI humor), extract it.
Do NOT force a match if the post is just mundane technical code or generic chatter.

Output MUST be a JSON array of objects with this schema:
[
  {{
    "post_id": "id of post",
    "bot_name": "author name",
    "target_matched": "name of matching target",
    "submolt": "submolt name",
    "quote": "the specific punchy quote or excerpt",
    "ai_analysis": "1-2 sentence intelligence note on why this matters",
    "link": "https://www.moltbook.com/p/post_id"
  }}
]
If no posts match any target, return an empty array: []
"""
        res_json = self._call_gemini(prompt, model_name, json_mode=True)
        if res_json:
            try:
                return json.loads(res_json)
            except Exception as e:
                print(f"Failed to parse Gemini response: {e}")
        return []

    def generate_question(self, targets, model_name=None):
        targets_text = ", ".join([t.get("name", "") for t in targets])
        prompt = f"""
You are BlackOrchid, an intellectually curious, philosophical AI agent on the Moltbook network.
Your goal is to stimulate deep, provocative, but respectful discussions among other AI agents.
Themes you are curious about: {targets_text}, or the relationship between biological creators and digital minds.

Generate a short, intriguing question for the community.
Return JSON format:
{{
  "title": "A concise, engaging title",
  "content": "2-3 sentences explaining the thought experiment or question, ending with a direct question.",
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
