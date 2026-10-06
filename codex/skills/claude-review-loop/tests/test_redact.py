import unittest

from claude_review_loop import redact


class TestRedact(unittest.TestCase):
    def test_private_key_body_is_removed(self):
        begin = "-----BEGIN " + "PRIVATE KEY-----"
        end = "-----END " + "PRIVATE KEY-----"
        text = f"before\n{begin}\nVERYSECRETBASE64\n{end}\nafter"
        scrubbed, changed = redact.redact_text(text)
        self.assertTrue(changed)
        self.assertNotIn("VERYSECRETBASE64", scrubbed)
        self.assertIn("BEGIN PRIVATE KEY", scrubbed)
        self.assertIn("END PRIVATE KEY", scrubbed)

    def test_connection_password_is_removed(self):
        scrubbed, changed = redact.redact_text(
            "DATABASE_URL=" + "postgres://" + "user:" +
            "correct-horse-battery-staple" + "@localhost/db"
        )
        self.assertTrue(changed)
        self.assertNotIn("correct-horse", scrubbed)
        self.assertIn("postgres://user:", scrubbed)

    def test_secret_path_detection(self):
        for path in (
            ".env", "config/.env.prod", "certs/app.pem", "prod.env",
            "id_rsa", "id_ecdsa", "keys/id_dsa",
        ):
            self.assertTrue(redact.is_secret_path(path), path)
        self.assertFalse(redact.is_secret_path("src/environment.py"))
        self.assertFalse(redact.is_secret_path("conf/.env.d/README.md"))

    def test_removed_private_key_diff_is_redacted_across_hunks(self):
        begin = "-----BEGIN " + "PRIVATE KEY-----"
        end = "-----END " + "PRIVATE KEY-----"
        diff = (
            "diff --git a/config.txt b/config.txt\n"
            "index 123..456 100644\n"
            "--- a/config.txt\n"
            "+++ b/config.txt\n"
            "@@ -1,3 +0,0 @@\n"
            f"-{begin}\n"
            "-VERYSECRETBASE64PART1\n"
            "@@ -20,2 +17,0 @@\n"
            "-VERYSECRETBASE64PART2\n"
            f"-{end}\n"
        )
        scrubbed, paths = redact.redact_diff(diff)
        self.assertNotIn("VERYSECRETBASE64", scrubbed)
        self.assertIn("[redacted: secret value]", scrubbed)
        self.assertEqual(paths, ["config.txt"])

    def test_open_private_key_redacts_next_hunk_function_context(self):
        begin = "-----BEGIN " + "PRIVATE KEY-----"
        end = "-----END " + "PRIVATE KEY-----"
        function_context = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC"
        diff = (
            "diff --git a/config.txt b/config.txt\n"
            "--- a/config.txt\n"
            "+++ b/config.txt\n"
            "@@ -1,2 +0,0 @@\n"
            f"-{begin}\n"
            "-FIRSTKEYBODY\n"
            f"@@ -20,2 +18,0 @@ {function_context}\n"
            "-SECONDKEYBODY\n"
            f"-{end}\n"
        )
        scrubbed, paths = redact.redact_diff(diff)
        self.assertNotIn(function_context, scrubbed)
        self.assertNotIn("FIRSTKEYBODY", scrubbed)
        self.assertNotIn("SECONDKEYBODY", scrubbed)
        self.assertEqual(paths, ["config.txt"])

    def test_suppressed_blank_context_does_not_close_private_key_block(self):
        body = "SENSITIVE_PRIVATE_KEY_BODY_123456789"
        begin = "-----BEGIN " + "PRIVATE KEY-----"
        end = "-----END " + "PRIVATE KEY-----"
        diff = (
            "diff --git a/config.txt b/config.txt\n"
            "--- a/config.txt\n"
            "+++ b/config.txt\n"
            "@@ -0,0 +1,4 @@\n"
            f"+{begin}\n"
            "\n"
            f"+{body}\n"
            f"+{end}\n"
        )
        scrubbed, paths = redact.redact_diff(diff)
        self.assertNotIn(body, scrubbed)
        self.assertIn("[redacted: secret value]", scrubbed)
        self.assertEqual(paths, ["config.txt"])

    def test_removed_comment_that_looks_like_header_is_still_scanned(self):
        sensitive_value = "hunter2-" + "password-value-123"
        diff = (
            "diff --git a/query.sql b/query.sql\n"
            "--- a/query.sql\n"
            "+++ b/query.sql\n"
            "@@ -1 +0,0 @@\n"
            f"--- password: {sensitive_value}\n"
        )
        scrubbed, paths = redact.redact_diff(diff)
        self.assertNotIn(sensitive_value, scrubbed)
        self.assertEqual(paths, ["query.sql"])

    def test_ordinary_identifier_assignments_are_not_redacted(self):
        text = (
            "token = get_access_token_for_x1\n"
            "name = task-abcdefghijklmnopqrstuv\n"
            'sort_key = "created_at_descending"'
        )
        self.assertEqual(redact.redact_text(text), (text, False))

    def test_quoted_generic_secret_is_redacted(self):
        value = "correct-horse-battery-staple"
        text = f'password = "{value}"'
        scrubbed, changed = redact.redact_text(text)
        self.assertTrue(changed)
        self.assertNotIn(value, scrubbed)

    def test_base64url_secret_with_underscore_is_redacted(self):
        value = "abc_def_ghi_jkl_mno_pqr"
        text = f'API_KEY = "{value}"'
        scrubbed, changed = redact.redact_text(text)
        self.assertTrue(changed)
        self.assertNotIn(value, scrubbed)

    def test_json_quoted_key_secret_is_redacted(self):
        value = "correct-horse-battery-staple"
        text = f'{{"password": "{value}"}}'
        scrubbed, changed = redact.redact_text(text)
        self.assertTrue(changed)
        self.assertNotIn(value, scrubbed)
        self.assertIn('"password": "[redacted: secret value]"', scrubbed)

    def test_prefixed_secret_assignment_keys_are_redacted(self):
        value = "correct-horse-battery-staple"
        keys = (
            "DB_PASSWORD", "EMAIL_HOST_PASSWORD", "AWS_SECRET_ACCESS_KEY",
            "auth_token", "refresh_token", "bearer_token", "POSTGRES_PASSWORD",
        )
        for key in keys:
            with self.subTest(key=key):
                scrubbed, changed = redact.redact_text(f'{key} = "{value}"')
                self.assertTrue(changed)
                self.assertNotIn(value, scrubbed)

    def test_ansi_colored_diff_fails_closed(self):
        with self.assertRaisesRegex(OSError, "ANSI escape sequence"):
            redact.redact_diff("\x1b[1mdiff --git a/x b/x\x1b[0m\n")

    def test_ansi_escape_inside_file_content_is_allowed(self):
        diff = (
            "diff --git a/terminal.txt b/terminal.txt\n"
            "--- a/terminal.txt\n"
            "+++ b/terminal.txt\n"
            "@@ -0,0 +1 @@\n"
            "+literal terminal sequence: \x1b[31mred\x1b[0m\n"
        )
        scrubbed, paths = redact.redact_diff(diff)
        self.assertIn("\x1b[31mred", scrubbed)
        self.assertEqual(paths, [])

    def test_combined_diff_header_fails_closed(self):
        with self.assertRaisesRegex(OSError, "unsupported git diff header"):
            redact.redact_diff(
                "diff --cc conflicted.env\n"
                "index 111,222..333\n"
                "--- a/conflicted.env\n"
                "+++ b/conflicted.env\n"
            )

    def test_hunk_heading_secret_is_redacted(self):
        sensitive_value = "sk-ant-" + "A" * 30
        diff = (
            "diff --git a/config.py b/config.py\n"
            "--- a/config.py\n"
            "+++ b/config.py\n"
            f'@@ -2 +2 @@ API_KEY = "{sensitive_value}"\n'
            "-old = 1\n"
            "+new = 2\n"
        )
        scrubbed, paths = redact.redact_diff(diff)
        self.assertNotIn(sensitive_value, scrubbed)
        self.assertEqual(paths, ["config.py"])

    def test_non_newline_control_character_does_not_bypass_redaction(self):
        sensitive_value = "secret-value-with-digits-123"
        diff = (
            "diff --git a/config.txt b/config.txt\n"
            "--- a/config.txt\n"
            "+++ b/config.txt\n"
            "@@ -1 +1 @@\n"
            f'+prefix\x0cpassword = "{sensitive_value}"\r\n'
        )
        scrubbed, paths = redact.redact_diff(diff)
        self.assertNotIn(sensitive_value, scrubbed)
        self.assertIn("\x0c", scrubbed)
        self.assertIn("\r\n", scrubbed)
        self.assertEqual(paths, ["config.txt"])


# Obviously fake fixtures, assembled at runtime so no secret-shaped literal
# sits in the source.
_FAKE_AGE_KEY = "AGE-SECRET-KEY-" + "1" + "FAKEFAKEFAKE" * 5
_FAKE_TOKEN = "0123456789abcdef" * 2 + "fake"
_FAKE_BASIC = "ZmFrZS11c2VyOmZha2UtcGFzcw=="  # base64 of fake-user:fake-pass
_FAKE_SLACK_PATH = "T00000FAKE/B00000FAKE/" + "FAKEFAKEFAKE" * 2
_FAKE_MAILGUN = "key-" + "0f" * 16


class TestNewSecretShapes(unittest.TestCase):
    CASES = (
        ("age", f"export SOPS_AGE_KEY={_FAKE_AGE_KEY}", _FAKE_AGE_KEY[16:]),
        ("age-keyfile", f"{_FAKE_AGE_KEY}", _FAKE_AGE_KEY[16:]),
        ("token-header", f"Authorization: Token {_FAKE_TOKEN}", _FAKE_TOKEN),
        ("basic-header", f"authorization: basic {_FAKE_BASIC}", _FAKE_BASIC),
        ("token-dict",
         f'headers = {{"Authorization": "Token {_FAKE_TOKEN}"}}', _FAKE_TOKEN),
        ("basic-curl", f"curl -H 'Authorization: Basic {_FAKE_BASIC}' x",
         _FAKE_BASIC),
        ("basic-shortest", "Authorization: Basic YTpi", "YTpi"),
        ("basic-short-padded", "Authorization: Basic YWI6Yw==", "YWI6Yw=="),
        ("bearer-dict",
         f'{{"Authorization": "Bearer {_FAKE_TOKEN}"}}', _FAKE_TOKEN),
        ("slack-webhook",
         "url = https://hooks.slack.com/services/" + _FAKE_SLACK_PATH,
         _FAKE_SLACK_PATH),
        ("mailgun", f"mg = Client({_FAKE_MAILGUN!r})", _FAKE_MAILGUN),
    )

    def test_new_shapes_are_redacted_in_text(self):
        for name, line, sensitive in self.CASES:
            with self.subTest(name):
                scrubbed, changed = redact.redact_text(f"before\n{line}\nafter")
                self.assertTrue(changed)
                self.assertNotIn(sensitive, scrubbed)
                self.assertIn("[redacted: secret value]", scrubbed)

    def test_new_shapes_are_redacted_in_diff(self):
        for name, line, sensitive in self.CASES:
            with self.subTest(name):
                diff = (
                    "diff --git a/app.py b/app.py\n"
                    "--- a/app.py\n"
                    "+++ b/app.py\n"
                    "@@ -1,2 +1,2 @@\n"
                    f"-{line}\n"
                    f"+{line}\n"
                    " unchanged = 1\n"
                )
                scrubbed, paths = redact.redact_diff(diff)
                self.assertNotIn(sensitive, scrubbed)
                self.assertEqual(paths, ["app.py"])

    def test_header_scheme_survives_redaction(self):
        scrubbed, _ = redact.redact_text(f"Authorization: Token {_FAKE_TOKEN}")
        self.assertEqual(scrubbed, "Authorization: Token [redacted: secret value]")
        scrubbed, _ = redact.redact_text(
            "https://hooks.slack.com/services/" + _FAKE_SLACK_PATH)
        self.assertEqual(
            scrubbed, "https://hooks.slack.com/services/[redacted: secret value]")

    def test_ordinary_code_and_prose_are_not_redacted(self):
        for text in (
            "Send the Token header; Basic auth is disabled.",
            "Authorization: Token <token>",
            "Authorization: Basic {credentials}",
            'headers["Authorization"] = f"Token {token}"',
            "Authorization: Token abc",
            "Authorization: Basic YTp",
            "AGE-SECRET-KEY-1 identities live in keys.txt",
            "AGE-SECRET-KEY-1" + "lowercase" * 6,
            "a key-value store with key-" + "0f" * 8,
            "monkey-" + "0f" * 16,
            "see hooks.slack.com/services/ for setup",
            "token_type = 'Bearer'",
        ):
            with self.subTest(text):
                self.assertEqual(redact.redact_text(text), (text, False))

    def test_new_secret_paths(self):
        for path in (
            ".git-credentials", "home/.pgpass", ".npmrc", "keys.txt",
            "sops/age/keys.txt", "certs/client.pfx", "vault/Passwords.kdbx",
            "credentials.json", "gcp/credentials.json",
        ):
            with self.subTest(path):
                self.assertTrue(redact.is_secret_path(path))
        for path in (
            "keys.py", "src/keys.txt.md", "keys_test.txt", "pgpass.py",
            "credentials.py", "docs/credentials.md", "npmrc.example",
            "git-credentials.md", "my-keys.txt",
        ):
            with self.subTest(path):
                self.assertFalse(redact.is_secret_path(path))

    def test_new_secret_paths_are_withheld_from_diff(self):
        for path in (".git-credentials", ".pgpass", "keys.txt"):
            with self.subTest(path):
                diff = (
                    f"diff --git a/{path} b/{path}\n"
                    "new file mode 100644\n"
                    "--- /dev/null\n"
                    f"+++ b/{path}\n"
                    "@@ -0,0 +1 @@\n"
                    "+fake-host:5432:db:fake-user:fake-password-value\n"
                )
                scrubbed, paths = redact.redact_diff(diff)
                self.assertNotIn("fake-password-value", scrubbed)
                self.assertIn("[redacted: secret-looking file not sent]", scrubbed)
                self.assertEqual(paths, [path])
