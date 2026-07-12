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
