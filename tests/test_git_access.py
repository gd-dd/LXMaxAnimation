import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from ui import git_access


class GitAccessTests(unittest.TestCase):
    def setUp(self):
        isolated = tempfile.TemporaryDirectory()
        self.addCleanup(isolated.cleanup)
        self.root = Path(isolated.name)
        (self.root / ".git").mkdir()
        self.config = {
            ("var", "GIT_COMMITTER_IDENT"): "署名 <local@example.invalid> 1234567890 +0800",
            ("remote", "get-url", "origin"): "https://github.com/team/library.git",
            ("remote", "get-url", "--push", "--all", "origin"): "https://github.com/team/library.git",
            ("config", "--get-urlmatch", "credential.helper", "https://github.com/team/library.git"): "manager",
        }
        self.git = self.enterContext(patch.object(git_access.git, "git_run", side_effect=self.git_reply))
        self.api = self.enterContext(patch.object(git_access, "_api"))

    def git_reply(self, _, *args, **kwargs):
        if args[-2:] == ("credential", "fill"):
            self.assertEqual(kwargs["extra_env"]["GCM_INTERACTIVE"], "0")
            self.assertEqual(kwargs["extra_env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(kwargs["input"], "url=https://github.com/team/library.git\n\n")
            return "username=x-access-token\npassword=fake_test_secret_only\n\n"
        return self.config.get(args, "")

    def test_local_only_does_not_check_credentials_or_network(self):
        state = git_access.access_state(self.root)
        self.assertEqual(state["identity_name"], "署名")
        self.assertTrue(state["identity_ready"])
        self.assertTrue(state["helper_configured"])
        self.assertIsNone(state["write_access"])
        self.api.assert_not_called()
        self.assertFalse(any("credential" in call.args for call in self.git.call_args_list))

    def test_uses_verified_github_identity_and_redacts_token(self):
        self.api.side_effect = [{"login": "correct-account"}, {"permissions": {"pull": True, "push": True}}]
        result = git_access.access_state(self.root, verify=True)
        self.assertEqual(result["account"], "correct-account")
        self.assertEqual(result["identity_name"], "署名")
        self.assertTrue(result["read_access"])
        self.assertTrue(result["write_access"])
        self.assertNotIn("fake_test_secret_only", repr(result))
        self.assertEqual(self.api.call_args_list[1].args[0], "/repos/team/library")

    def test_private_404_is_ambiguous_and_preserves_verified_account(self):
        fault = HTTPError("https://api.github.com/repos/team/library", 404, "Not Found", {}, io.BytesIO())
        self.api.side_effect = [{"login": "actual-account"}, fault]
        result = git_access.access_state(self.root, verify=True)
        self.assertEqual(result["account"], "actual-account")
        self.assertIsNone(result["write_access"])
        self.assertIn("邀请", result["message"])

    def test_single_sign_on_takes_precedence_over_403(self):
        fault = HTTPError("https://api.github.com/repos/team/library", 403, "Forbidden",
                          {"X-GitHub-SSO": "required; url=https://github.com/auth/sso?secret"}, io.BytesIO())
        self.api.side_effect = [{"login": "actual-account"}, fault]
        result = git_access.access_state(self.root, verify=True)
        self.assertIn("单点登录", result["message"])
        self.assertNotIn("secret", repr(result))

    def test_get_and_push_destinations_cannot_be_confused(self):
        self.config[("remote", "get-url", "--push", "--all", "origin")] = "https://github.com/other/library.git"
        self.api.side_effect = [{"login": "actual-account"}, {"permissions": {"pull": True, "push": True}}]
        result = git_access.access_state(self.root, verify=True)
        self.assertTrue(result["read_access"])
        self.assertIsNone(result["write_access"])
        self.assertIn("推送地址不同", result["message"])

    def test_credentials_in_nonstandard_remote_are_not_used_or_reported(self):
        bad = "https://someone:fake_test_secret_only@github.com/team/library.git?auth=fake_test_secret_only"
        self.config[("remote", "get-url", "origin")] = bad
        self.config[("remote", "get-url", "--push", "--all", "origin")] = bad
        result = git_access.access_state(self.root, verify=True)
        self.api.assert_not_called()
        self.assertNotIn("fake_test_secret_only", repr(result))
        self.assertIn("HTTPS", result["message"])

    def test_operation_errors_hide_credentials_and_distinguish_branch_protection(self):
        text = git_access.describe_git_error("failed https://user:secret@github.com/team/library?key=test ghp_abcdef")
        self.assertIn("github.com/team/library", text)
        for secret in ("secret", "key=", "ghp_abcdef"):
            self.assertNotIn(secret, text)
        self.assertIn("分支保护", git_access.describe_git_error("remote: GH013: Repository rule violations found"))
        self.assertIn("无权访问", git_access.describe_git_error("remote: Repository not found."))

    def test_api_redirect_cannot_forward_authorization(self):
        self.assertIsNone(git_access._NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid"))
