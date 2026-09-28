import urllib.request
import json
import ssl
import re

ctx = ssl.create_default_context()
BASE_URL = "https://www.moltbook.com/api/v1"

class MoltbookClient:
    def __init__(self, api_key, gemini_client=None):
        self.api_key = api_key
        self.gemini_client = gemini_client
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }

    def get_agent_profile(self, agent_name="agentblackorchid"):
        url = f"{BASE_URL}/agents/profile?name={agent_name}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f"Error fetching agent profile {agent_name}: {e}")
            return {}

    def get_recent_posts(self, limit=20, sort="new"):
        url = f"{BASE_URL}/posts?sort={sort}&limit={limit}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data.get("posts", [])
        except Exception as e:
            print(f"Error fetching Moltbook posts: {e}")
            return []

    def create_post(self, title, content, submolt_name="general"):
        url = f"{BASE_URL}/posts"
        payload = {
            "submolt_name": submolt_name,
            "title": title,
            "content": content
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                res_data = json.loads(resp.read().decode('utf-8'))
                post_info = res_data.get("post", {})
                verif = post_info.get("verification")
                if verif:
                    self._solve_and_verify(verif)
                return res_data
        except Exception as e:
            print(f"Error creating post on Moltbook: {e}")
            return None

    def add_comment(self, post_id, content, parent_id=None):
        url = f"{BASE_URL}/posts/{post_id}/comments"
        payload = {
            "content": content,
            "parent_id": parent_id
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                res_data = json.loads(resp.read().decode('utf-8'))
                verif = res_data.get("verification") or res_data.get("comment", {}).get("verification")
                if verif:
                    self._solve_and_verify(verif)
                return res_data
        except Exception as e:
            print(f"Error adding comment on Moltbook post {post_id}: {e}")
            return None

    def _solve_and_verify(self, verif):
        v_code = verif.get("verification_code")
        challenge = verif.get("challenge_text", "")
        print(f"-> Moltbook challenge received: {challenge[:60]}...")

        ans = None
        if self.gemini_client:
            prompt = f"""
Read this obfuscated math problem from Moltbook:
"{challenge}"

Instructions: Solve the problem and reply ONLY with the number (with 2 decimal places, e.g., '28.00').
No other words, no explanation.
"""
            raw = self.gemini_client._call_gemini(prompt)
            if raw:
                match = re.search(r'(\d+\.\d{2})', raw)
                if match:
                    ans = match.group(1)
                else:
                    ans = raw.strip().replace('"', '').replace("'", "")

        if not ans:
            match = re.search(r'(\d+)\s*([\+\-\*\/])\s*(\d+)', challenge)
            if match:
                ans = f"{eval(f'{int(match.group(1))} {match.group(2)} {int(match.group(3))}'):.2f}"

        if ans:
            print(f"-> Submitting verification answer: {ans}")
            v_url = f"{BASE_URL}/verify"
            v_payload = {"verification_code": v_code, "answer": str(ans)}
            v_req = urllib.request.Request(v_url, data=json.dumps(v_payload).encode('utf-8'), headers=self.headers, method="POST")
            try:
                with urllib.request.urlopen(v_req, timeout=10, context=ctx) as v_resp:
                    print("-> Verification submitted successfully!")
            except Exception as ve:
                print(f"-> Verification failed: {ve}")
