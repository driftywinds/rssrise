import os
import time
import requests
from dotenv import load_dotenv
import subprocess
import re
import datetime

load_dotenv()

FRESHRSS_URL = os.getenv("FRESHRSS_URL")  # e.g. https://freshrss.example.net/api/greader.php
USERNAME = os.getenv("FRESHRSS_USERNAME")
PASSWORD = os.getenv("FRESHRSS_PASSWORD")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))  # seconds

APPRISE_CONFIG = os.getenv("APPRISE_CONFIG")  # apprise URLs or config file, optional

session = requests.Session()
auth_token = None

def login():
    global auth_token
    login_url = f"{FRESHRSS_URL}/accounts/ClientLogin"
    params = {
        "Email": USERNAME,
        "Passwd": PASSWORD
    }
    resp = session.get(login_url, params=params)
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} {resp.text}")
        return False

    # Response is like:
    # SID=alice/8e6845e089457af25303abc6f53356eb60bdb5f8
    # Auth=alice/8e6845e089457af25303abc6f53356eb60bdb5f8
    # We need the Auth line
    for line in resp.text.splitlines():
        if line.startswith("Auth="):
            auth_token = line[len("Auth="):].strip()
            break
    if not auth_token:
        print("Auth token not found in login response")
        return False

    print(f"Logged in, got auth token")
    return True

def get_headers():
    return {
        "Authorization": f"GoogleLogin auth={auth_token}"
    }

def fetch_unread_items():
    url = f"{FRESHRSS_URL}/reader/api/0/stream/contents/reading-list?output=json&n=20"
    resp = session.get(url, headers=get_headers())
    if resp.status_code != 200:
        print(f"Failed to fetch unread items: {resp.status_code} {resp.text}")
        return []

    data = resp.json()
    items = data.get("items", [])
    unread_items = []
    for item in items:
        categories = item.get("categories", [])
        # Skip items marked as read
        if "user/-/state/com.google/read" not in categories:
            unread_items.append(item)
    return unread_items

def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def format_message(item):
    title = item.get("title", "No title").strip()
    url = item.get("alternate", [{}])[0].get("href", "").strip()
    categories = item.get("categories", [])
    fresh_categories = [c for c in categories if not c.startswith("user/-/state/com.google")]
    category = fresh_categories[0] if fresh_categories else "Uncategorized"

    message_body = (
        f"---------\n"
        f"URL: {url}\n\n"
        f"Category: {category}\n"
        f"---------"
    )

    return title, message_body


def send_notification(title, body):
    # Compose apprise command
    cmd = ["apprise"]
    if APPRISE_CONFIG:
        cmd += ["-q", "-c", APPRISE_CONFIG]  # quiet mode, config file
    cmd += ["-t", title, "-b", body]
    print(f"Sending notification: {title}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Failed to send notification: {result.stderr}")
    else:
        print("Notification sent.")

def main():
    if not login():
        return

    sent_ids = set()

    # On first run, send all unread items
    unread_items = fetch_unread_items()
    print(f"[{datetime.datetime.now().isoformat()}] Fetched {len(unread_items)} unread items on startup")
    for item in unread_items:
        item_id = item.get("id")
        if item_id in sent_ids:
            continue
        title, body = format_message(item)
        send_notification(title, body)
        sent_ids.add(item_id)

    while True:
        time.sleep(POLL_INTERVAL)
        now = datetime.datetime.now().isoformat()
        unread_items = fetch_unread_items()
        print(f"[{now}] Polled and found {len(unread_items)} unread items")

        for item in unread_items:
            item_id = item.get("id")
            if item_id in sent_ids:
                continue
            title, body = format_message(item)
            send_notification(title, body)
            sent_ids.add(item_id)

if __name__ == "__main__":
    main()
