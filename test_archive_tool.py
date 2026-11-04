from pathlib import Path
import tempfile
import unittest

from x360archive.catalog import remote_name
from x360archive.service import build_plan, match_remote, scan_local
from x360archive.web import build_site


def catalog(*games):
    return {"schema_version": 1, "games": list(games)}


GAME = {
    "asset_id": "425307d5-fallout-3-game-of-the-year-edition",
    "title_id": "425307D5",
    "title": "Fallout 3: Game of the Year Edition",
    "expected_filename": "Fallout 3 - Game of the Year Edition.7z",
    "categories": ["RPG"],
}


class LocalScanTests(unittest.TestCase):
    def test_alias_finds_file_without_renaming_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actual = root / "Fallout-local-name.7z"
            actual.write_bytes(b"archive")
            result = scan_local(catalog(GAME), [str(root)], aliases={GAME["asset_id"]: actual.name})
            record = result["files"][GAME["asset_id"]]
            self.assertEqual(record["status"], "healthy")
            self.assertEqual(Path(record["path"]), actual)
            self.assertTrue(actual.exists())

    def test_missing_is_reported_from_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = scan_local(catalog(GAME), [tmp])
            self.assertEqual(result["files"][GAME["asset_id"]]["status"], "missing")

    def test_extra_local_archive_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = Path(tmp) / "Uncatalogued.7z"
            extra.write_bytes(b"extra")
            result = scan_local(catalog(GAME), [tmp])
            self.assertEqual(result["extra_files"], [str(extra)])


class ReconciliationTests(unittest.TestCase):
    def test_matching_technical_name_and_size_is_healthy(self):
        record = {"asset_id": GAME["asset_id"], "title_id": GAME["title_id"],
                  "expected_filename": GAME["expected_filename"], "size": 7, "sha256": "a" * 64}
        item = {"name": remote_name(GAME["asset_id"], "a" * 64), "size": 7, "removed": False}
        self.assertEqual(match_remote(record, [item]), item)

    def test_provider_error_blocks_plan_instead_of_claiming_healthy(self):
        local = {"files": {GAME["asset_id"]: {"asset_id": GAME["asset_id"],
                 "title_id": GAME["title_id"], "expected_filename": GAME["expected_filename"],
                 "status": "healthy", "path": "x", "size": 7}}}
        remotes = {"providers": {"webshare": {"status": "error", "error": "login", "files": []}}}
        plan = build_plan(catalog(GAME), local, remotes, ["webshare"])
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["blocked_providers"][0]["provider"], "webshare")

    def test_missing_remote_creates_upload_action(self):
        local = {"files": {GAME["asset_id"]: {"asset_id": GAME["asset_id"],
                 "title_id": GAME["title_id"], "expected_filename": GAME["expected_filename"],
                 "status": "healthy", "path": "fallout.7z", "size": 7}}}
        remotes = {"providers": {"webshare": {"status": "ok", "files": []}}}
        plan = build_plan(catalog(GAME), local, remotes, ["webshare"])
        self.assertEqual(plan["action_count"], 1)
        self.assertEqual(plan["actions"][0]["title_id"], "425307D5")


class SiteTests(unittest.TestCase):
    def test_healthy_remote_exposes_current_download_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            url = "https://webshare.cz/#/file/abc123"
            remotes = {"providers": {"webshare": {"status": "ok", "files": [{
                "name": GAME["expected_filename"], "size": 7, "url": url, "removed": False
            }]}}}
            build_site(catalog(GAME), None, remotes, Path(tmp),
                       archive_sizes={GAME["asset_id"]: 7})
            data = (Path(tmp) / "data/games.json").read_text(encoding="utf-8")
            self.assertIn(url, data)

    def test_remote_only_uses_tracked_size_to_detect_incomplete_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            remotes = {"providers": {"webshare": {"status": "ok", "files": [{
                "name": GAME["expected_filename"], "size": 6, "removed": False
            }]}}}
            build_site(catalog(GAME), None, remotes, Path(tmp),
                       archive_sizes={GAME["asset_id"]: 7})
            data = (Path(tmp) / "data/games.json").read_text(encoding="utf-8")
            self.assertIn('"webshare": "missing"', data)
            self.assertIn('"download_urls": {}', data)

    def test_public_data_does_not_contain_local_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = {"files": {GAME["asset_id"]: {"status": "healthy", "path": "E:/private/fallout.7z"}}}
            build_site(catalog(GAME), local, {"providers": {}}, Path(tmp))
            text = (Path(tmp) / "data/games.json").read_text(encoding="utf-8")
            self.assertNotIn("E:/private", text)
            self.assertIn("Fallout 3", text)


if __name__ == "__main__":
    unittest.main()
