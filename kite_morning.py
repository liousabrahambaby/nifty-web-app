"""
Morning GIFT Nifty forecast from your own PC (alternative to the GitHub route).

Usage:  set KITE_API_KEY and KITE_API_SECRET as environment variables, then run
        python kite_morning.py
It opens the Kite login page; after logging in, paste the address of the page
Kite sends you to. The script runs the pre-market forecast and pushes it.
"""
import os
import subprocess
import sys
import webbrowser
from urllib.parse import parse_qs, urlparse

key = os.environ.get("KITE_API_KEY")
if not key or not os.environ.get("KITE_API_SECRET"):
    sys.exit("Set KITE_API_KEY and KITE_API_SECRET environment variables first.")
url = f"https://kite.zerodha.com/connect/login?v=3&api_key={key}"
print("Opening Kite login:", url)
webbrowser.open(url)
back = input("After logging in, paste the full address you were sent to (or just the request_token): ").strip()
token = parse_qs(urlparse(back).query).get("request_token", [back])[0]
env = dict(os.environ, KITE_REQUEST_TOKEN=token)
subprocess.run(["git", "pull", "-q"], check=False)
subprocess.run([sys.executable, "analyze.py", "--premarket"], env=env, check=True)
subprocess.run(["git", "add", "data.json", "gap_track.json"], check=False)
subprocess.run(["git", "commit", "-qm", "Pre-market update with GIFT Nifty"], check=False)
subprocess.run(["git", "push", "-q"], check=False)
print("Done. Reload the cockpit.")
