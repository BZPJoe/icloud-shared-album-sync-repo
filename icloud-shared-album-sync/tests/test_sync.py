import importlib.util
import json
import sys
import tempfile
import unittest
from base64 import b64encode
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "sync.py"
SPEC = importlib.util.spec_from_file_location("icloud_sync", MODULE_PATH)
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def test_recognizes_current_photos_icloud_link(self):
        self.assertEqual(
            sync.modern_album_id_from_url(
                "https://photos.icloud.com/shared/album/0d1BnY5KrxNaYN5y1AZI-IK7Q"
            ),
            "0d1BnY5KrxNaYN5y1AZI-IK7Q",
        )
        self.assertIsNone(sync.modern_album_id_from_url("https://www.icloud.com/sharedalbum/#old"))

    def test_converts_current_public_album_record(self):
        filename = b64encode(b"Dee at the lake.jpg").decode()
        record = {
            "recordName": "record-guid",
            "recordType": "CPLMaster",
            "fields": {
                "itemType": {"value": "public.jpeg"},
                "filenameEnc": {"value": filename},
                "originalCreationDate": {"value": 1788307240472},
                "resJPEGMedWidth": {"value": 2048},
                "resJPEGMedHeight": {"value": 1536},
                "resJPEGMedFileType": {"value": "public.jpeg"},
                "resJPEGMedRes": {
                    "value": {
                        "size": 498385,
                        "downloadURL": "https://example.test/B/file/${f}?token=abc",
                    }
                },
            },
        }
        item = sync.modern_record_to_item(record, minimum_long_edge=1280, minimum_bytes=100000)
        self.assertIsNotNone(item)
        self.assertEqual(item.filename, "Dee at the lake.jpg")
        self.assertEqual(item.width, 2048)
        self.assertEqual(item.height, 1536)
        self.assertTrue(item.source_url.endswith("/Dee%20at%20the%20lake.jpg?token=abc"))
        self.assertEqual(item.media_type, "image")

    def test_current_public_album_prefers_dashboard_jpeg_over_heic_original(self):
        record = {
            "recordName": "heic-guid",
            "recordType": "CPLMaster",
            "fields": {
                "itemType": {"value": "public.heic"},
                "filenameEnc": {"value": b64encode(b"IMG_0001.HEIC").decode()},
                "resOriginalWidth": {"value": 4032},
                "resOriginalHeight": {"value": 3024},
                "resOriginalRes": {"value": {"size": 2000000, "downloadURL": "https://example.test/original/${f}"}},
                "resJPEGMedWidth": {"value": 2048},
                "resJPEGMedHeight": {"value": 1536},
                "resJPEGMedFileType": {"value": "public.jpeg"},
                "resJPEGMedRes": {"value": {"size": 500000, "downloadURL": "https://example.test/jpeg/${f}"}},
            },
        }
        item = sync.modern_record_to_item(record, minimum_long_edge=1280, minimum_bytes=100000)
        self.assertIsNotNone(item)
        self.assertEqual(item.filename, "IMG_0001.jpg")
        self.assertEqual((item.width, item.height), (2048, 1536))
        self.assertIn("/jpeg/IMG_0001.jpg", item.source_url)

    def test_current_public_album_record_honors_quality_floor(self):
        record = {
            "recordName": "tiny-guid",
            "recordType": "CPLMaster",
            "fields": {
                "itemType": {"value": "public.jpeg"},
                "resJPEGMedWidth": {"value": 800},
                "resJPEGMedHeight": {"value": 600},
                "resJPEGMedRes": {"value": {"size": 40000, "downloadURL": "https://example.test/tiny"}},
            },
        }
        self.assertIsNone(sync.modern_record_to_item(record, minimum_long_edge=1280, minimum_bytes=100000))

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

    def test_custom_folder_is_normalized_to_a_lowercase_dashboard_slug(self):
        parsed = sync.parse_albums(
            [{"name": "Dee", "shared_url": "https://example.test/#abc", "album_subfolder": "Dee Visits 2026"}]
        )
        self.assertEqual(parsed[0]["album_subfolder"], "dee-visits-2026")

    def test_native_album_editor_json_from_options(self):
        parsed = sync.parse_albums(
            '[{"name":"Family Photos","shared_url":"https://example.test/#abc","enabled":true}]'
        )
        self.assertEqual(parsed[0]["name"], "Family Photos")
        self.assertEqual(parsed[0]["album_subfolder"], "family-photos")

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
