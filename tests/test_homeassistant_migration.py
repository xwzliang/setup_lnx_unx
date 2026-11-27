import argparse
import http.client
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from setup_homeassistant import migrate


class HomeAssistantRestoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.archive = Path(folder.name) / migrate.ARCHIVE
        metadata = json.dumps({"homeassistant": {"version": "2026.11.3"}, "slug": "abcdef01"}).encode()
        with tarfile.open(self.archive, "w") as archive:
            member = tarfile.TarInfo("./backup.json")
            member.size = len(metadata)
            archive.addfile(member, io.BytesIO(metadata))
        self.archive.with_name(migrate.KEY_FILE).write_text("test-key\n")
        self.args = argparse.Namespace(
            archive=self.archive, key_file=None, target="http://192.0.2.10:8123", timeout=10,
        )
        self.backup_info = {
            "state": "idle",
            "backups": [{
                "backup_id": "abcdef01",
                "agents": {migrate.AGENT: {"size": self.archive.stat().st_size, "protected": True}},
                "addons": [{"slug": "core_ssh"}, {"slug": "a0d7b954_nodered"}],
                "folders": ["share", "ssl", "addons/local"],
                "database_included": True,
            }],
        }
        self.installation = (200, b'{"installation_type":"Home Assistant OS"}')
        self.info_url = f"{migrate.BACKUP_API}/info"
        self.restore_url = f"{migrate.BACKUP_API}/restore"

    def test_upload_stream_and_restore_all_components_after_restart(self):
        requests = []

        def request(method, path, **kwargs):
            requests.append((method, path))
            if path == "/api/onboarding/installation_type":
                return self.installation
            if path == self.info_url:
                if ("POST", self.restore_url) in requests:
                    return 404, b""
                if requests.count(("GET", self.info_url)) == 1:
                    return 200, b'{"state":"idle","backups":[]}'
                return 200, json.dumps(self.backup_info).encode()
            if path == f"{migrate.BACKUP_API}/upload?agent_id={migrate.AGENT}":
                data = b"".join(kwargs["body"])
                self.assertEqual(len(data), int(kwargs["headers"]["Content-Length"]))
                self.assertIn(self.archive.read_bytes(), data)
                self.assertIn(b'name="file"; filename="home-assistant.tar"', data)
                return 201, b'{"backup_id":"abcdef01"}'
            if path == self.restore_url:
                self.assertEqual(json.loads(kwargs["body"]), {
                    "backup_id": "abcdef01",
                    "agent_id": migrate.AGENT,
                    "restore_addons": ["core_ssh", "a0d7b954_nodered"],
                    "restore_folders": ["share", "ssl", "addons/local"],
                    "restore_database": True,
                    "password": "test-key",
                })
                raise http.client.RemoteDisconnected()
            return (401 if path == "/api/" else 200), b""

        with patch.object(migrate.Target, "request", side_effect=request), patch("sys.stdout", new=io.StringIO()) as out:
            migrate.restore_backup(self.args)
        self.assertEqual(requests.count(("POST", self.restore_url)), 1)
        self.assertIn("UI is reachable", out.getvalue())

    def test_onboarded_target_receives_no_archive(self):
        with patch.object(migrate.Target, "request", return_value=(404, b"")) as request:
            with self.assertRaisesRegex(migrate.MigrationError, "welcome screen"):
                migrate.restore_backup(self.args)
        request.assert_called_once_with("GET", "/api/onboarding/installation_type")

    def test_wrong_key_keeps_existing_upload_and_reports_failure(self):
        responses = [
            self.installation,
            (200, json.dumps(self.backup_info).encode()),
            (400, b'{"code":"incorrect_password"}'),
        ]
        with patch.object(migrate.Target, "request", side_effect=responses) as request:
            with self.assertRaisesRegex(migrate.MigrationError, "rejected the backup key"):
                migrate.restore_backup(self.args)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args.args, ("POST", self.restore_url))

    def test_corrupt_archive_is_rejected_before_connecting(self):
        self.archive.with_name(migrate.CHECKSUM).write_text("incorrect-checksum\n")
        with patch.object(migrate.Target, "request") as request:
            with self.assertRaisesRegex(migrate.MigrationError, "SHA-256"):
                migrate.restore_backup(self.args)
        request.assert_not_called()
