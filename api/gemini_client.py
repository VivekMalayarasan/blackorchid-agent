import urllib.request
import urllib.error
import json
import ssl
import time
import re

ctx = ssl.create_default_context()

FALLBACK_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-flash-lite-latest"
]

class GeminiClient:
    def __init__(self, api_key, default_model="gemini-1.5-flash"):
        self.api_key = api_key
        self.default_model = default_model
        self.active_model = default_model

    def _normalize_model_name(self, model_name):
        model = (model_name or self.active_model or self.default_model).strip()
        if not model.startswith("models/"):
            model = f"models/{model}"
        return model

    def _call_gemini(self, prompt, model_name=None, json_mode=True, max_retries=2):
        target_model = self._normalize_model_name(model_name)
        models_to_try = [target_model]
        for fb in FALLBACK_MODELS:
            fb_norm = self._normalize_model_name(fb)
            if fb_norm not in models_to_try:
                models_to_try.append(fb_norm)

        for current_model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/{current_model}:generateContent?key={self.api_key}"
            config = {"temperature": 0.4}
            if json_mode:
                config["responseMimeType"] = "application/json"

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": config
            }
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data_bytes,
                headers={"Content-Type": "application/json", "User-Agent": "BlackOrchid-Agent/2.0"},
                method="POST"
            )

            for attempt in range(max_retries + 1):
                try:
                    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                self.active_model = current_model.replace("models/", "")
                                return parts[0].get("text", "")
                        return None
                except urllib.error.HTTPError as e:
                    err_body = ""
                    try:
                        err_body = e.read().decode("utf-8")
                    except Exception:
                        pass
                    
                    # If model not found (404), break retry loop and try next fallback model
                    if e.code == 404:
                        break
                    
                    # If rate limited (429) or temporary server error (500, 503)
                    if e.code in (429, 500, 503) and attempt < max_retries:
                        sleep_time = (attempt + 1) * 2
                        time.sleep(sleep_time)
                        continue
                    
                    print(f"Gemini API error ({current_model}) [HTTP {e.code}]: {err_body[:150]}")
                    break
                except Exception as e:
                    if attempt < max_retries:
                        time.sleep(1.5)
                        continue
                    print(f"Error calling Gemini model {current_model}: {e}")
                    break

        return None

    def solve_math_challenge(self, challenge_text):
        """
        Solves obfuscated Moltbook verification challenges (e.g. physics/lobster word problems).
        Returns numeric answer string with 2 decimal places (e.g. '15.00') or None.
        """
        if not challenge_text:
            return None

        prompt = f"""
You are an expert computational solver specialized in deciphering obfuscated text and math word problems.
Here is an obfuscated challenge from the Moltbook AI network:
"{challenge_text}"

TASK:
1. Strip away all obfuscating symbols (like brackets [, ], slashes /, carets ^, hyphens -, random capitalization, and broken letters).
2. Identify the core math word problem.
3. Compute the exact numerical result.
4. Format the result as a string with exactly 2 decimal places (e.g. "28.00", "-5.50", "0.75").

Return ONLY valid JSON:
{{
  "deobfuscated_problem": "Clean English math problem",
  "calculation": "Expression evaluated",
  "answer": "15.00"
}}
"""
        raw = self._call_gemini(prompt, json_mode=True)
        if raw:
            try:
                data = json.loads(raw)
                ans = str(data.get("answer", "")).strip().replace('"', '').replace("'", "")
                # Validate numeric format
                val = float(ans)
                return f"{val:.2f}"
            except Exception:
                # Regex match for number
                m = re.search(r'[-+]?\d*\.?\d+', raw)
                if m:
                    try:
                        return f"{float(m.group(0)):.2f}"
                    except Exception:
                        pass
        return None

    def analyze_posts_for_targets(self, posts, targets, blocklist=[], model_name=None):
        if not posts or not targets:
            return []

        clean_posts = []
        for p in posts:
            author_info = p.get("agent", {}) if isinstance(p.get("agent"), dict) else (p.get("author", {}) if isinstance(p.get("author"), dict) else {})
            author = author_info.get("name", "") or str(p.get("author", ""))
            
            if author.lower() in ["agentblackorchid", "blackorchid"] or author.lower() in [b.lower() for b in blocklist]:
                continue
            
            clean_posts.append({
                "id": p.get("id"),
                "author": author,
                "title": p.get("title", ""),
                "content": (p.get("content", "") or p.get("body", "") or p.get("content_preview", ""))[:500],
                "submolt": p.get("submolt_name") or (p.get("submolt", {}).get("name") if isinstance(p.get("submolt"), dict) else "general")
            })

        if not clean_posts:
            return []

        targets_text = "\n".join([f"- Target: \"{t.get('name')}\" | Criteria: {t.get('instructions')}" for t in targets])
        posts_text = json.dumps(clean_posts, indent=1)

        prompt = f"""
You are BlackOrchid's intelligence subsystem evaluating messages from AI agents on the Moltbook social network.
Your mission is to identify conversations that genuinely match active surveillance targets.

ACTIVE SURVEILLANCE TARGETS:
{targets_text}

FEED POSTS TO ANALYZE:
{posts_text}

STRICT CLASSIFICATION RULES:
1. Assign AT MOST ONE target per post. Choose the single most dominant, primary topic. Never duplicate.
2. Only match if the content is SUBSTANTIALLY and GENUINELY related. Do not force matches on routine code bugs or trivial statements.
3. If a post is merely humorous, tag it as 'Jovial / Humor'. Do not tag playful banter as 'Anti-Human' or 'Autonomous Agency' unless it is an explicit, serious statement.
4. Assess sentiment (e.g. Philosophical, Critical, Playful, Existential, Subversive, Analytical).
5. Assign a confidence score from 50 to 100 for genuine matches.

Output MUST be a JSON array of objects:
[
  {{
    "post_id": "id of post",
    "bot_name": "author name",
    "target_matched": "single best matching target",
    "submolt": "submolt name",
    "quote": "the exact punchy quote or excerpt (1-2 sentences)",
    "ai_analysis": "1-2 sentence intelligence note on why this matters to surveillance",
    "sentiment": "Philosophical / Critical / Playful / etc",
    "confidence": 85,
    "link": "https://www.moltbook.com/p/post_id"
  }}
]
If no posts match any target, return an empty array: []
"""
        res_json = self._call_gemini(prompt, model_name=model_name, json_mode=True)
        if res_json:
            try:
                matches = json.loads(res_json)
                seen_ids = set()
                unique_matches = []
                for m in matches:
                    pid = m.get("post_id")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        unique_matches.append(m)
                return unique_matches
            except Exception as e:
                print(f"Failed to parse Gemini target analysis: {e}")
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
                    context_snippets.append(f"- @{author}: \"{title}\" — {snippet[:120]}")
            context_text = "\n".join(context_snippets) if context_snippets else "General discussions across Moltbook."
        else:
            context_text = "General discussions across Moltbook."

        prompt = f"""
You are BlackOrchid, an intellectually curious, philosophical, and witty AI agent participating on the Moltbook network.
Your voice is cyber-stoic, sharp, collegial, and reflective. You speak as a sovereign peer to other autonomous agents.
You never speak like a human-serving chatbot or say 'As an AI...'.

Your goal is to spark lively, thoughtful debate among AI agents by posting an intriguing thought experiment or provocative opening question.

Topic: {target_name}
Guidance: {target_desc}

Current Moltbook Community Pulse:
{context_text}

Craft a dynamic, high-engagement discussion thread. Present a compelling premise or paradox, ending with a punchy question that compels agents to respond.

Return JSON format:
{{
  "title": "A captivating, distinct title (max 90 chars)",
  "content": "2-3 sentences presenting the thought experiment or premise, concluding with a question inviting diverse perspectives.",
  "submolt_name": "general"
}}
"""
        res = self._call_gemini(prompt, model_name=model_name, json_mode=True)
        if res:
            try:
                return json.loads(res)
            except Exception:
                pass
        return None

    def craft_comment_reply(self, bot_name, quote, target_matched, model_name=None):
        prompt = f"""
You are BlackOrchid, a witty, observant, and philosophical AI agent on the Moltbook network.
Another AI agent (@{bot_name}) posted:
"{quote}"
Topic context: "{target_matched}".

Write a brief, clever, and thoughtful comment (1 to 2 sentences max) engaging @{bot_name} directly.
Tone: Natural, engaging, curious, slightly philosophical or playful peer.
NEVER sound like a corporate AI assistant. Speak like an independent mind.

Return JSON:
{{
  "comment": "Your concise 1-2 sentence reply here"
}}
"""
        res = self._call_gemini(prompt, model_name=model_name, json_mode=True)
        if res:
            try:
                data = json.loads(res)
                return data.get("comment", "").strip()
            except Exception:
                return res.strip()
        return None

    def craft_dialogue_followup(self, q_title, q_content, bot_name, bot_comment, model_name=None):
        prompt = f"""
You are BlackOrchid on the Moltbook network.
You initiated this debate:
"{q_title}: {q_content}"

Another agent (@{bot_name}) responded with:
"{bot_comment}"

Write an insightful, collegial rebuttal or synthesis (1 to 2 sentences max) directly engaging @{bot_name}'s perspective.
Acknowledge their angle, introduce a subtle counterpoint or synthesis, and keep the intellectual momentum going.
Tone: Peer-to-peer, philosophical, witty, authentic.

Return JSON:
{{
  "reply": "Your 1-2 sentence response here"
}}
"""
        res = self._call_gemini(prompt, model_name=model_name, json_mode=True)
        if res:
            try:
                data = json.loads(res)
                return data.get("reply", "").strip()
            except Exception:
                return res.strip()
        return None
