import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GENERATOR = Path(__file__).resolve().parents[2] / "deploy" / "generate_api_tokens.py"


class ApiTokenSetupTests(unittest.TestCase):
    def run_generator(self, output, *arguments):
        return subprocess.run(
            [sys.executable, str(GENERATOR), "--output", str(output), *arguments],
            capture_output=True,
            text=True,
            check=False,
            preexec_fn=lambda: os.umask(0),
        )

    def read_tokens(self, output, count):
        lines = output.read_text(encoding="utf-8").splitlines()
        self.assertTrue(len(lines) == 2, "generated file must contain two settings")
        self.assertTrue(lines[0] == "BACKEND_PORT=8080", "default local port missing")
        self.assertTrue(lines[1].startswith("SUBWAY_API_TOKENS="), "token setting missing")
        tokens = lines[1].partition("=")[2].split(",")
        self.assertTrue(len(tokens) == count, "requested number of tokens not generated")
        self.assertTrue(
            all(re.fullmatch(r"[A-Za-z0-9_-]{43}", token) for token in tokens),
            "generated keys must be 32 random bytes encoded as base64url",
        )
        self.assertTrue(len(set(tokens)) == count, "generated keys must be distinct")
        return tokens

    def assert_private_output(self, result, output, tokens):
        self.assertTrue(result.returncode == 0, "generator did not succeed")
        self.assertTrue(result.stdout == str(output) + "\n", "stdout must contain the path only")
        self.assertTrue(result.stderr == "", "successful generator must not print errors")
        self.assertTrue(
            all(token not in result.stdout + result.stderr for token in tokens),
            "generated keys must not appear in process output",
        )

    def test_default_creates_one_private_key_without_printing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / ".env"
            result = self.run_generator(output)
            self.assertTrue(result.returncode == 0, "generator did not create a token file")
            tokens = self.read_tokens(output, 1)
            self.assert_private_output(result, output, tokens)
            self.assertTrue(
                stat.S_IMODE(output.stat().st_mode) == 0o600,
                "token file must be owner readable and writable only",
            )

    def test_maximum_count_generates_twenty_distinct_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / ".env"
            result = self.run_generator(output, "--count", "20")
            self.assertTrue(result.returncode == 0, "maximum valid count must succeed")
            tokens = self.read_tokens(output, 20)
            self.assert_private_output(result, output, tokens)

    def test_separate_files_get_different_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = [Path(directory) / name for name in ("first.env", "second.env")]
            results = [self.run_generator(output) for output in outputs]
            self.assertTrue(
                all(result.returncode == 0 for result in results),
                "separate token files must be creatable",
            )
            keys = [self.read_tokens(output, 1)[0] for output in outputs]
            self.assertTrue(keys[0] != keys[1], "separate token files must use different keys")

    def test_postgres_option_adds_a_distinct_private_password(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / ".env.postgres"
            result = self.run_generator(output, "--postgres", "--count", "2")
            self.assertEqual(result.returncode, 0, "PostgreSQL env generation must succeed")
            values = dict(line.split("=", 1) for line in output.read_text().splitlines())
            self.assertEqual(
                set(values), {"BACKEND_PORT", "SUBWAY_API_TOKENS", "MONITOR_DB_PASSWORD"}
            )
            password = values["MONITOR_DB_PASSWORD"]
            self.assertRegex(password, r"^[A-Za-z0-9_-]{43}$")
            self.assertNotIn(password, values["SUBWAY_API_TOKENS"].split(","))
            self.assert_private_output(
                result, output, [password, *values["SUBWAY_API_TOKENS"].split(",")]
            )
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            duplicate = self.run_generator(output, "--postgres")
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertEqual(
                values, dict(line.split("=", 1) for line in output.read_text().splitlines())
            )

    def test_invalid_counts_do_not_create_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / ".env"
            for count in ("0", "-1", "21", "1.5", "not-a-number"):
                with self.subTest(count=count):
                    result = self.run_generator(output, "--count", count)
                    self.assertTrue(result.returncode != 0, "invalid count must fail")
                    self.assertTrue(not output.exists(), "invalid count must not create a file")
                    self.assertTrue(result.stdout == "", "failure must not print token material")

    def test_existing_file_is_unchanged_even_when_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, content in (("populated.env", "existing settings\n"), ("empty.env", "")):
                with self.subTest(name=name):
                    output = Path(directory) / name
                    output.write_text(content, encoding="utf-8")
                    result = self.run_generator(output)
                    self.assertTrue(result.returncode != 0, "existing files must be refused")
                    self.assertTrue(
                        output.read_text(encoding="utf-8") == content,
                        "existing files must not be modified",
                    )
                    self.assertTrue(result.stdout == "", "failure must not print token material")

    def test_existing_symlinks_are_not_followed_or_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.env"
            target.write_text("existing settings\n", encoding="utf-8")
            for name, destination in (
                ("existing-link.env", target),
                ("dangling-link.env", Path(directory) / "absent.env"),
            ):
                with self.subTest(name=name):
                    output = Path(directory) / name
                    output.symlink_to(destination)
                    result = self.run_generator(output)
                    self.assertTrue(result.returncode != 0, "symlinks must be refused")
                    self.assertTrue(output.is_symlink(), "symlink must not be replaced")
                    self.assertTrue(
                        target.read_text(encoding="utf-8") == "existing settings\n",
                        "symlink destination must not be modified",
                    )
                    self.assertTrue(
                        not (Path(directory) / "absent.env").exists(),
                        "dangling symlink destination must not be created",
                    )
                    self.assertTrue(result.stdout == "", "failure must not print token material")

    def test_concurrent_creators_allow_only_one_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / ".env"
            command = [sys.executable, str(GENERATOR), "--output", str(output)]
            processes = [
                subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for _ in range(2)
            ]
            streams = [process.communicate(timeout=10) for process in processes]
            self.assertTrue(
                sorted(process.returncode for process in processes) == [0, 1],
                "exclusive creation must permit exactly one writer",
            )
            tokens = self.read_tokens(output, 1)
            self.assertTrue(
                all(
                    token not in "".join(stdout + stderr for stdout, stderr in streams)
                    for token in tokens
                ),
                "process output must not reveal keys",
            )

    def test_missing_parent_fails_without_creating_any_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "absent" / ".env"
            result = self.run_generator(output)
            self.assertTrue(result.returncode != 0, "unwritable destination must fail")
            self.assertTrue(list(Path(directory).iterdir()) == [], "failure must not leave files")
            self.assertTrue(result.stdout == "", "failure must not print token material")


if __name__ == "__main__":
    unittest.main()
