"""Stage the FCM fields for the test APK from an Android client config."""
import argparse
import base64
import json
import os
from pathlib import Path
import re

PACKAGE = "com.yuilyoung.subwayalert"
SECRET = "FIREBASE_ANDROID_CONFIG_BASE64"


def client_config(encoded):
    document = json.loads(base64.b64decode("".join(encoded.split()), validate=True))
    if "private_key" in document or "type" in document:
        raise ValueError("expected Android client configuration")
    project = document["project_info"]
    sender = project["project_number"]
    project_id = project["project_id"]
    if not re.fullmatch(r"[0-9]+", sender) or not re.fullmatch(r"[A-Za-z0-9.:-]+", project_id):
        raise ValueError("invalid project metadata")
    matches = [item for item in document["client"]
               if item["client_info"].get("android_client_info", {}).get("package_name") == PACKAGE]
    if len(matches) != 1:
        raise ValueError("expected exactly one matching Android client")
    client = matches[0]
    app_id = client["client_info"]["mobilesdk_app_id"]
    if not re.fullmatch(rf"1:{sender}:android:[0-9a-fA-F]+", app_id):
        raise ValueError("invalid Android app identifier")
    api_key = client["api_key"][0]["current_key"]
    if not re.fullmatch(r"AIza[A-Za-z0-9_-]{35}", api_key):
        raise ValueError("invalid Android API key")

    # Only these public client fields are needed by the Firebase Messaging SDK.
    return {
        "project_info": {"project_id": project_id, "project_number": sender},
        "client": [{
            "client_info": {"android_client_info": {"package_name": PACKAGE}, "mobilesdk_app_id": app_id},
            "api_key": [{"current_key": api_key}],
        }],
        "configuration_version": "1",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    target = parser.parse_args().output
    try:
        config = client_config(os.environ.get(SECRET, ""))
    except (AttributeError, ValueError, KeyError, IndexError, TypeError, RecursionError):
        raise SystemExit(f"Missing or invalid {SECRET}. Supply the Firebase Android client config for {PACKAGE}.") from None
    with open(target, "x", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
        json.dump(config, output)


if __name__ == "__main__":
    main()
