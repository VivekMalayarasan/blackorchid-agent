import urllib.request
import urllib.error
import json
import ssl
import os
import time

ctx = ssl.create_default_context()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SHEET_CACHE_FILE = os.path.join(CURRENT_DIR, "sheet_cache.json")
PENDING_ROWS_FILE = os.path.join(CURRENT_DIR, "pending_sheet_rows.json")

def _load_json_file(filepath, default_val=None):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_val

def _save_json_file(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save {filepath}: {e}")

def get_sheet_data(webapp_url, max_retries=1):
    req = urllib.request.Request(webapp_url, headers={'User-Agent': 'BlackOrchid-Agent/2.0'})
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data and "settings" in data:
                    _save_json_file(SHEET_CACHE_FILE, data)
                    return data
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2)
                continue
            print(f'Error fetching sheet data (attempt {attempt+1}): {e}')

    # Fallback to local cache if Google Apps Script is down or cold-starting
    cached = _load_json_file(SHEET_CACHE_FILE)
    if cached:
        print("-> Using cached Google Sheet configuration (offline mode).")
        cached["_from_cache"] = True
        return cached
    return None

def log_rows_to_sheet(webapp_url, rows, auto_split='YES', max_retries=1):
    pending_rows = _load_json_file(PENDING_ROWS_FILE, []) or []
    all_rows = pending_rows + (rows or [])

    if not all_rows:
        return True

    payload = {
        'action': 'log',
        'auto_split': auto_split,
        'rows': all_rows
    }
    data_bytes = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        webapp_url,
        data=data_bytes,
        headers={'Content-Type': 'application/json', 'User-Agent': 'BlackOrchid-Agent/2.0'},
        method='POST'
    )

    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=35, context=ctx) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('status') == 'success':
                    # Clear pending queue on success
                    if pending_rows and os.path.exists(PENDING_ROWS_FILE):
                        _save_json_file(PENDING_ROWS_FILE, [])
                    return True
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2)
                continue
            print(f'Error logging rows to sheet: {e}')

    # Queue failed rows to pending buffer
    print(f"-> Queuing {len(all_rows)} rows to local pending queue for later synchronization.")
    _save_json_file(PENDING_ROWS_FILE, all_rows)
    return False

def update_sheet_heartbeat(webapp_url, message='Healthy'):
    payload = {
        'action': 'heartbeat',
        'message': message
    }
    data_bytes = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        webapp_url,
        data=data_bytes,
        headers={'Content-Type': 'application/json', 'User-Agent': 'BlackOrchid-Agent/2.0'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            return True
    except Exception as e:
        print(f'Error updating heartbeat: {e}')
        return False
