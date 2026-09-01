import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "sync.py"
SPEC = importlib.util.spec_from_file_location("icloud_sync", MODULE_PATH)
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def test_parse_bool(self):
        self.assertTrue(sync.parse_bool("true"))
        self.assertTrue(sync.parse_bool("YES"))
        self.assertFalse(sync.parse_bool("false"))
        self.assertFalse(sync.parse_bool("0"))

    def test_normalize_single_line_yaml(self):
        source = "- name: Dee shared_url: https://example.test/#abc album_subfolder: dee"
        parsed = sync.parse_albums(source)
        self.assertEqual(parsed[0]["name"], "Dee")
        self.assertEqual(parsed[0]["album_subfolder"], "dee")

    def test_native_album_editor_data_gets_friendly_defaults(self):
        parsed = sync.parse_albums(
            [{"name": "Dad and Janice", "shared_url": "https://example.test/#abc"}]
        )
        self.assertEqual(parsed[0]["album_subfolder"], "dad-and-janice")
        self.assertEqual(parsed[0]["dest_mode"], "config_www")
        self.assertEqual(parsed[0]["media_subfolder"], "icloud-albums")
        self.assertEqual(parsed[0]["index_filename"], "index.json")

    def test_disabled_album_is_ignored(self):
        parsed = sync.parse_albums(
            [
                {"name": "Old", "shared_url": "https://example.test/#old", "enabled": False},
                {"name": "Current", "shared_url": "https://example.test/#new", "enabled": True},
            ]
        )
        self.assertEqual([album["name"] for album in parsed], ["Current"])

    def test_selects_largest_photo_derivative(self):
        photo = {
            "photoGuid": "guid",
            "width": "2049",
            "height": "1537",
            "derivatives": {
                "342": {"checksum": "small", "width": "342", "height": "257", "fileSize": "50000"},
                "2049": {"checksum": "large", "width": "2049", "height": "1537", "fileSize": "900000"},
            },
        }
        selected = sync.select_derivative(photo, minimum_long_edge=1280, minimum_bytes=100000)
        self.assertEqual(selected[0], "large")

    def test_selects_video_not_poster(self):
        photo = {
            "photoGuid": "guid",
            "mediaAssetType": "video",
            "derivatives": {
                "PosterFrame": {"checksum": "poster", "width": "1920", "height": "1080", "fileSize": "300000"},
                "720p": {"checksum": "video", "width": "1280", "height": "720", "fileSize": "5000000"},
            },
        }
        selected = sync.select_derivative(photo, minimum_long_edge=1280, minimum_bytes=100000)
        self.assertEqual(selected[0], "video")

    def test_mirror_protects_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("keep.jpg", "remove.jpg", "index.json", "latest.jpg", ".icloud_album_sync.json", "notes.txt"):
                (root / name).write_text("x", encoding="utf-8")
            removed = sync.mirror_media(root, {"keep.jpg"})
            self.assertEqual(removed, ["remove.jpg"])
            self.assertTrue((root / "index.json").exists())
            self.assertTrue((root / "latest.jpg").exists())
            self.assertTrue((root / "notes.txt").exists())

    def test_atomic_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "index.json"
            sync.atomic_write_json(target, {"version": 2, "items": []})
            self.assertEqual(json.loads(target.read_text())["version"], 2)
            self.assertFalse((Path(tmp) / "index.json.part").exists())


if __name__ == "__main__":
    unittest.main()
