import urllib.request
import json
import ssl

ctx = ssl.create_default_context()

def get_sheet_data(webapp_url):
    req = urllib.request.Request(webapp_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data
    except Exception as e:
        print(f'Error fetching sheet data: {e}')
        return None

def log_rows_to_sheet(webapp_url, rows, auto_split='YES'):
    if not rows:
        return True
    payload = {
        'action': 'log',
        'auto_split': auto_split,
        'rows': rows
    }
    data_bytes = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(webapp_url, data=data_bytes, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('status') == 'success'
    except Exception as e:
        print(f'Error logging rows to sheet: {e}')
        return False

def update_sheet_heartbeat(webapp_url, message='Healthy'):
    payload = {
        'action': 'heartbeat',
        'message': message
    }
    data_bytes = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(webapp_url, data=data_bytes, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
            return True
    except Exception as e:
        print(f'Error updating heartbeat: {e}')
        return False
