"""Exercise the APK job's secret boundary with synthetic Android metadata."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[2] / "deploy" / "prepare_android_firebase.py"
PACKAGE = "com.yuilyoung.subwayalert"
SENDER = "123456789012"
APP_ID = f"1:{SENDER}:android:0123456789abcdef"
KEY = "AIza" + "a" * 35
CLIENT = {
    "client_info": {"android_client_info": {"package_name": PACKAGE}, "mobilesdk_app_id": APP_ID},
    "api_key": [{"current_key": KEY}],
}
CONFIG = {
    "project_info": {"project_id": "subway-ci-fixture", "project_number": SENDER},
    "client": [CLIENT],
    "configuration_version": "1",
}


def encode(value):
    return base64.b64encode(json.dumps(value).encode()).decode()


class AndroidFirebaseConfigTest(unittest.TestCase):
    def prepare(self, target, value):
        env = os.environ.copy()
        env.pop("FIREBASE_ANDROID_CONFIG_BASE64", None)
        if value is not None:
            env["FIREBASE_ANDROID_CONFIG_BASE64"] = value
        return subprocess.run([sys.executable, str(HELPER), str(target)], env=env,
                              capture_output=True, text=True, check=False)

    def test_stages_only_fcm_fields_for_the_matching_android_client(self):
        config = copy.deepcopy(CONFIG)
        other = copy.deepcopy(CLIENT)
        other["client_info"]["android_client_info"]["package_name"] = "com.example.other"
        config["client"].insert(0, other)
        config["client"][1]["oauth_client"] = [{"client_id": "unrelated-identity"}]
        wrapped = "\n".join(encode(config)[i:i+76] for i in range(0, len(encode(config)), 76))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "google-services.json"
            result = self.prepare(target, wrapped)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, "")
            self.assertEqual(json.loads(target.read_bytes()), CONFIG)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_invalid_secrets_fail_without_writing_or_printing_the_input(self):
        def changed_client(key, value):
            client = copy.deepcopy(CLIENT)
            client[key] = value
            return {**CONFIG, "client": [client]}

        invalid = [None, " ", "@@@" + KEY, base64.b64encode(b"invalid JSON").decode(),
                   encode({"type": "service_account", "private_key": KEY}),
                   encode({**CONFIG, "type": "service_account", "private_key": KEY}),
                   encode({**CONFIG, "client": []}), encode({**CONFIG, "client": [CLIENT, CLIENT]}),
                   encode({**CONFIG, "project_info": {"project_id": "subway-ci-fixture"}}),
                   encode(changed_client("client_info", {"android_client_info": {"package_name": "com.example.other"},
                                                         "mobilesdk_app_id": APP_ID})),
                   encode(changed_client("client_info", {"android_client_info": {"package_name": PACKAGE},
                                                         "mobilesdk_app_id": "1:999:android:abcdef"})),
                   encode(changed_client("api_key", [])), encode(changed_client("api_key", [{"current_key":"invalid"}]))]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "google-services.json"
            for i, value in enumerate(invalid):
                with self.subTest(case=i):
                    result = self.prepare(target, value)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(target.exists())
                    self.assertIn("FIREBASE_ANDROID_CONFIG_BASE64", result.stderr)
                    self.assertNotIn(KEY, result.stdout + result.stderr)
                    if value and len(value) > 10:
                        self.assertNotIn(value, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
