from http.server import BaseHTTPRequestHandler
import json
import os
import sys

# Ensure local imports work in Vercel serverless environment
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from agent import run_agent_cycle

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            summary = run_agent_cycle()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(summary, indent=2).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            err_data = {"status": "error", "error": str(e)}
            self.wfile.write(json.dumps(err_data).encode('utf-8'))
