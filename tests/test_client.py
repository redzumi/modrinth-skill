import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("modrinth_client", ROOT / "scripts/mr.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
TOKEN = "synthetic-" + "token-for-tests"


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = mock.patch.object(client, "CONFIG", self.root / "credentials.env")
        self.config.start()
        self.addCleanup(self.config.stop)
        self.env = mock.patch.dict(client.os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        client.PREFIX = "/v2"

    def invoke(self, args, response=None, error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(client, "request", return_value=response, side_effect=error) as request:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = client.main(args)
        data = json.loads(stdout.getvalue()) if stdout.getvalue().strip() else None
        return code, data, stderr.getvalue(), request

    def test_search_filters_without_credentials(self):
        code, data, _, request = self.invoke(["search", "render mod", "--loader", "fabric", "--game-version", "1.21.1"], {"hits": [], "total_hits": 0})
        self.assertEqual(code, 0)
        method, path, token = request.call_args.args
        self.assertEqual((method, token), ("GET", None))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        self.assertEqual(query["query"], ["render mod"])
        self.assertEqual(json.loads(query["facets"][0]), [["project_type:mod"], ["categories:fabric"], ["versions:1.21.1"]])
        self.assertIn("total_hits", data)

    def test_versions_keep_files_hashes_and_dependencies(self):
        versions = [{"id": "test", "dependencies": [{"project_id": "dependency", "dependency_type": "required"}], "files": [{"url": "https://cdn.example.invalid/mod.jar", "hashes": {"sha512": "synthetic"}}]}]
        code, data, _, request = self.invoke(["versions", "sample-mod", "--loader", "fabric"], versions)
        self.assertEqual(code, 0)
        self.assertEqual(data, versions)
        self.assertEqual(request.call_args.args[2], None)
        self.assertIn("/project/sample-mod/version?", request.call_args.args[1])

    def test_public_api_get_without_credentials(self):
        code, data, _, request = self.invoke(["api", "GET", "/project/sample-mod"], {"id": "sample"})
        self.assertEqual(code, 0)
        self.assertEqual(data["id"], "sample")
        self.assertEqual(request.call_args.args[2], None)

    def test_identity_requires_a_token(self):
        code, _, stderr, request = self.invoke(["whoami"])
        self.assertEqual(code, 1)
        self.assertIn("Configure MODRINTH_TOKEN", stderr)
        request.assert_not_called()

    def test_write_preview_does_not_read_credentials_or_send(self):
        with mock.patch.object(client, "load_token", side_effect=AssertionError("preview read credentials")):
            code, data, _, request = self.invoke(["api", "PATCH", "/project/sample-mod"])
        self.assertEqual(code, 0)
        self.assertTrue(data["dry_run"])
        request.assert_not_called()

    def test_explicit_write_sends_once_with_token(self):
        payload = self.root / "edit.json"
        payload.write_text('{"description":"fixture"}')
        with mock.patch.dict(client.os.environ, {"MODRINTH_TOKEN": TOKEN}):
            code, _, _, request = self.invoke(["api", "PATCH", "/project/sample-mod", "--json-file", str(payload), "--execute"], {"ok": True})
        self.assertEqual(code, 0)
        request.assert_called_once()
        self.assertEqual(request.call_args.args[2], TOKEN)
        self.assertEqual(json.loads(request.call_args.args[3]), {"description": "fixture"})

    def test_external_paths_traversal_and_token_queries_are_rejected(self):
        for path in ["https://evil.invalid/", "//evil.invalid/", "/../user", "/user?token=private", "/user#fragment", "/bad\\path"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                client.api_url(path)

    def test_redirects_are_refused(self):
        req = urllib.request.Request("https://api.modrinth.com/v2/user")
        with self.assertRaises(urllib.error.HTTPError) as error:
            client.NoRedirect().redirect_request(req, None, 302, "redirect", {}, "https://evil.invalid/")
        error.exception.close()

    def test_bad_search_limit_never_sends(self):
        code, _, _, request = self.invoke(["search", "fixture", "--limit", "101"])
        self.assertEqual(code, 1)
        request.assert_not_called()

    def test_get_payload_is_rejected(self):
        payload = self.root / "body.json"
        payload.write_text('{}')
        code, _, _, request = self.invoke(["api", "GET", "/user", "--json-file", str(payload)])
        self.assertEqual(code, 1)
        request.assert_not_called()

    def test_credentials_permissions_and_redaction(self):
        client.CONFIG.write_text("export MODRINTH_TOKEN='" + TOKEN + "'\n")
        client.CONFIG.chmod(0o644)
        with self.assertRaises(ValueError):
            client.load_token()
        client.CONFIG.chmod(0o600)
        self.assertEqual(client.load_token(), TOKEN)
        cleaned = client.clean({"nested": {"access_token": "other"}, "message": TOKEN}, TOKEN)
        self.assertEqual(cleaned, {"nested": {"access_token": "[REDACTED]"}, "message": "[REDACTED]"})

    def test_multipart_file_parts_are_validated(self):
        metadata = self.root / "release.json"
        jar = self.root / "fixture.jar"
        jar.write_bytes(b"synthetic fixture")
        metadata.write_text('{"file_parts":["jar"]}')
        body, content_type = client.multipart(metadata, ["jar=" + str(jar)], "data")
        self.assertIn(b"synthetic fixture", body)
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        metadata.write_text('{"file_parts":["missing"]}')
        with self.assertRaises(ValueError):
            client.multipart(metadata, ["jar=" + str(jar)], "data")


if __name__ == "__main__":
    unittest.main()
