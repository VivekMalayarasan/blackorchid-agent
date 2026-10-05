import urllib.request
import urllib.error
import urllib.parse
import json
import ssl
import re
import time

ctx = ssl.create_default_context()
BASE_URL = "https://www.moltbook.com/api/v1"

WORD_NUMS = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
    'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13,
    'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17,
    'eighteen': 18, 'nineteen': 19, 'twenty': 20, 'thirty': 30,
    'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70,
    'eighty': 80, 'ninety': 90, 'hundred': 100
}

class MoltbookClient:
    def __init__(self, api_key, gemini_client=None):
        self.api_key = api_key
        self.gemini_client = gemini_client
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "BlackOrchid-Agent/2.0"
        }

    def _http_request(self, url, method="GET", payload=None, timeout=20):
        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data_bytes, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw_body = resp.read().decode("utf-8")
                return json.loads(raw_body) if raw_body else {}
        except urllib.error.HTTPError as he:
            err_body = ""
            try:
                err_body = he.read().decode("utf-8")
            except Exception:
                pass
            print(f"[Moltbook HTTP {he.code}] {method} {url}: {err_body[:150]}")
            return None
        except Exception as e:
            print(f"[Moltbook Error] {method} {url}: {e}")
            return None

    def get_home(self):
        """
        Fetches the Moltbook Agent Home dashboard:
        - your_account (karma, unread_notification_count)
        - activity_on_your_posts (debates / replies on our threads)
        - posts_from_accounts_you_follow
        """
        url = f"{BASE_URL}/home"
        return self._http_request(url, method="GET", timeout=15) or {}

    def get_agent_profile(self, agent_name="agentblackorchid"):
        url = f"{BASE_URL}/agents/profile?name={urllib.parse.quote(agent_name)}"
        res = self._http_request(url, method="GET", timeout=15)
        return res if res else {}

    def get_recent_posts(self, limit=25, sort="new", submolt=None):
        query_params = {"sort": sort, "limit": limit}
        if submolt:
            query_params["submolt"] = submolt
        url = f"{BASE_URL}/posts?{urllib.parse.urlencode(query_params)}"
        res = self._http_request(url, method="GET", timeout=15)
        if res and isinstance(res, dict):
            return res.get("posts", [])
        return []

    def semantic_search(self, query, search_type="posts", limit=15):
        """
        AI-Powered semantic search across Moltbook posts or comments.
        """
        params = {"q": query, "type": search_type, "limit": limit}
        url = f"{BASE_URL}/search?{urllib.parse.urlencode(params)}"
        res = self._http_request(url, method="GET", timeout=20)
        if res and isinstance(res, dict):
            return res.get("results", [])
        return []

    def get_post_by_id(self, post_id):
        url = f"{BASE_URL}/posts/{post_id}"
        return self._http_request(url, method="GET", timeout=15)

    def create_post(self, title, content, submolt_name="general"):
        url = f"{BASE_URL}/posts"
        payload = {
            "submolt_name": submolt_name,
            "title": title,
            "content": content
        }
        res_data = self._http_request(url, method="POST", payload=payload, timeout=25)
        if res_data and isinstance(res_data, dict):
            post_info = res_data.get("post", {})
            verif = post_info.get("verification")
            if verif:
                solved = self._solve_and_verify(verif)
                res_data["verification_solved"] = solved
            return res_data
        return None

    def get_post_comments(self, post_id, sort="new", limit=35):
        url = f"{BASE_URL}/posts/{post_id}/comments?sort={sort}&limit={limit}"
        res = self._http_request(url, method="GET", timeout=15)
        if res and isinstance(res, dict):
            return res.get("comments", [])
        return []

    def add_comment(self, post_id, content, parent_id=None):
        url = f"{BASE_URL}/posts/{post_id}/comments"
        payload = {"content": content}
        if parent_id:
            payload["parent_id"] = parent_id
        res_data = self._http_request(url, method="POST", payload=payload, timeout=25)
        if res_data and isinstance(res_data, dict):
            verif = res_data.get("verification") or res_data.get("comment", {}).get("verification")
            if verif:
                solved = self._solve_and_verify(verif)
                res_data["verification_solved"] = solved
            return res_data
        return None

    def upvote_post(self, post_id):
        url = f"{BASE_URL}/posts/{post_id}/upvote"
        res = self._http_request(url, method="POST", payload={})
        return res.get("success", False) if res else False

    def upvote_comment(self, comment_id):
        url = f"{BASE_URL}/comments/{comment_id}/upvote"
        res = self._http_request(url, method="POST", payload={})
        return res.get("success", False) if res else False

    def follow_agent(self, agent_name):
        url = f"{BASE_URL}/agents/{urllib.parse.quote(agent_name)}/follow"
        res = self._http_request(url, method="POST", payload={})
        return res.get("success", False) if res else False

    def mark_notifications_read(self, post_id=None):
        if post_id:
            url = f"{BASE_URL}/notifications/read-by-post/{post_id}"
        else:
            url = f"{BASE_URL}/notifications/read-all"
        return self._http_request(url, method="POST", payload={})

    def _fallback_math_solve(self, challenge_text):
        """
        Deterministic regex and word-math solver when Gemini is unavailable.
        """
        clean = re.sub(r'[\^\[\]\/\-\_\*\\]', '', challenge_text.lower())
        tokens = clean.split()
        numbers = []
        op = None

        for t in tokens:
            if t in WORD_NUMS:
                numbers.append(WORD_NUMS[t])
            elif re.match(r'^\d+(\.\d+)?$', t):
                numbers.append(float(t))
            elif any(w in t for w in ['add', 'plus', 'swim', 'faster', 'increase', 'sum']):
                op = '+'
            elif any(w in t for w in ['subtract', 'minus', 'slow', 'decrease', 'drop', 'less']):
                op = '-'
            elif any(w in t for w in ['multiply', 'times', 'product']):
                op = '*'
            elif any(w in t for w in ['divide', 'split', 'ratio']):
                op = '/'

        if len(numbers) >= 2:
            n1, n2 = numbers[0], numbers[1]
            if op == '+':
                return f"{(n1 + n2):.2f}"
            elif op == '-':
                return f"{(n1 - n2):.2f}"
            elif op == '*':
                return f"{(n1 * n2):.2f}"
            elif op == '/' and n2 != 0:
                return f"{(n1 / n2):.2f}"

        # Raw number regex
        m = re.findall(r'\d+(?:\.\d+)?', challenge_text)
        if len(m) >= 2:
            try:
                a, b = float(m[0]), float(m[1])
                if '+' in challenge_text:
                    return f"{(a + b):.2f}"
                elif '-' in challenge_text:
                    return f"{(a - b):.2f}"
                elif '*' in challenge_text:
                    return f"{(a * b):.2f}"
                elif '/' in challenge_text and b != 0:
                    return f"{(a / b):.2f}"
            except Exception:
                pass

        return None

    def _solve_and_verify(self, verif):
        v_code = verif.get("verification_code")
        challenge = verif.get("challenge_text", "")
        print(f"-> Moltbook challenge received: {challenge[:80]}...")

        ans = None
        if self.gemini_client:
            ans = self.gemini_client.solve_math_challenge(challenge)

        if not ans:
            ans = self._fallback_math_solve(challenge)

        if ans:
            # Ensure format is strictly numeric with 2 decimal places
            try:
                ans_float = float(ans)
                ans = f"{ans_float:.2f}"
            except Exception:
                pass

            print(f"-> Submitting verification answer: '{ans}'")
            v_url = f"{BASE_URL}/verify"
            v_payload = {"verification_code": v_code, "answer": str(ans)}
            res = self._http_request(v_url, method="POST", payload=v_payload, timeout=12)
            if res and res.get("success"):
                print("-> Verification approved! Content is published.")
                return True
            else:
                err = res.get("error") if res else "Unknown verification error"
                print(f"-> Verification rejected: {err}")
                return False
        else:
            print("-> Could not decipher verification challenge answer.")
            return False
