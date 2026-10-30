"""
Run this ONCE on your own computer (it opens a browser window).
It prints the three values you paste into GitHub as secrets.

    pip install google-auth-oauthlib
    python get_youtube_token.py client_secret.json
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
path = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"

flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

with open(path) as f:
    raw = json.load(f)
info = raw.get("installed") or raw.get("web")

print("\n=== Add these 3 as GitHub repository secrets ===")
print("YT_CLIENT_ID     =", info["client_id"])
print("YT_CLIENT_SECRET =", info["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)
