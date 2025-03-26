import os
import json
import requests
from pathlib import Path

SOURCE_DIR = "/path/to/test/results"
REMOTE_URL = "http://remote.server.com:5000/api/results"


def send_file(filepath, category):
    with open(filepath, 'r') as f:
        content = json.load(f)

    payload = {
        "category": category,
        "filename": os.path.basename(filepath),
        "content": content
    }

    try:
        r = requests.post(REMOTE_URL, json=payload)
        if r.status_code == 200:
            print(f"Sent: {filepath}")
        else:
            print(f"Failed {filepath}: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Error: {filepath}: {e}")


def push_all():
    for root, _, files in os.walk(SOURCE_DIR):
        for file in files:
            if file.endswith(".json"):
                filepath = Path(root) / file
                category = Path(root).name  # Use folder name as category
                send_file(filepath, category)


if __name__ == "__main__":
    push_all()
