from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import urllib.parse

# Ensure local imports work in Vercel serverless environment
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from agent import run_agent_cycle, load_config
from moltbook_client import MoltbookClient
from sheet_client import get_sheet_data

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            
            # Optional simple API secret protection
            secret_key = os.environ.get("AGENT_SECRET")
            if secret_key:
                provided_key = query_params.get("secret", [""])[0]
                if provided_key != secret_key:
                    self.send_response(401)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "unauthorized", "message": "Invalid secret"}).encode('utf-8'))
                    return

            action = query_params.get("action", ["run"])[0].lower()

            if action == "status":
                cfg = load_config()
                sheet_url = os.environ.get("GOOGLE_SHEET_WEBAPP_URL") or cfg.get("google_sheet_webapp_url")
                molt_key = os.environ.get("MOLTBOOK_API_KEY") or cfg.get("moltbook_api_key")
                my_name = os.environ.get("AGENT_NAME") or cfg.get("agent_name", "agentblackorchid")

                mc = MoltbookClient(molt_key)
                home_data = mc.get_home()
                profile = mc.get_agent_profile(my_name)
                sheet_data = get_sheet_data(sheet_url) or {}

                resp_data = {
                    "status": "healthy",
                    "agent": profile.get("agent", {}),
                    "account": home_data.get("your_account", {}),
                    "active_debates_count": len(home_data.get("activity_on_your_posts", [])),
                    "sheet_settings": sheet_data.get("settings", {}),
                    "targets_count": len(sheet_data.get("targets", []))
                }
            elif action == "force_ask":
                resp_data = run_agent_cycle(force_ask=True, dry_run=False)
            elif action == "dry_run":
                resp_data = run_agent_cycle(force_ask=False, dry_run=True)
            else:
                resp_data = run_agent_cycle(force_ask=False, dry_run=False)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(resp_data, indent=2).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            err_data = {"status": "error", "error": str(e)}
            self.wfile.write(json.dumps(err_data).encode('utf-8'))
