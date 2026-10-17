"""Release regressions using synthetic albums and temporary media only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from test_sync import sync


class ReleaseTests(unittest.TestCase):
    def test_normalized_collision_rejected_before_sync(self):
        with self.assertRaises(sync.SyncError):
            sync.parse_albums([
                {'name': name, 'shared_url': 'https://example.test/#synthetic'}
                for name in ('Same Name', 'same-name')
            ])

    def test_existing_custom_folder_and_legacy_settings_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Family Photos').mkdir()
            albums = sync.parse_albums(json.dumps([{
                'name': 'Family', 'shared_url': 'https://example.test/#synthetic',
                'album_subfolder': 'Family Photos', 'dest_mode': 'share',
                'media_subfolder': str(root).lstrip('/'), 'max_files': 0,
            }]))
            # Patch the base path to isolate all writes from real Home Assistant mounts.
            with patch.object(sync, 'Path', side_effect=lambda value: Path('/') if value == '/share' else Path(value)):
                destination, public, _ = sync.destination_for(albums[0])
            self.assertEqual(destination, root / 'Family Photos')
            self.assertIsNone(public)
            self.assertEqual(albums[0]['max_files'], 0)

    def test_failed_download_preserves_index_latest_and_unlisted_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('old.jpg', 'latest.jpg', 'index.json'):
                (root / name).write_bytes(b'original')
            item = sync.RemoteItem('new', 'new.jpg', 'https://example.test/?secret=private',
                                   'image', None, 2000, 1500, 100, '', '')
            config = dict(timeout=40, minimum_file_size_kb=0, minimum_long_edge=0,
                          keep_days=1, max_files=1, mirror_missing=True)
            with patch.object(sync, 'destination_for', return_value=(root, None, root)), \
                 patch.object(sync.ICloudClient, 'list_album', return_value=[item]), \
                 patch.object(sync, 'download_item', side_effect=sync.requests.RequestException('secret=private')):
                result, _ = sync.sync_album(dict(name='Test', album_subfolder='test', shared_url='synthetic'), config)
            self.assertEqual(result.status, 'error')
            for name in ('old.jpg', 'latest.jpg', 'index.json'):
                self.assertEqual((root / name).read_bytes(), b'original')
            self.assertNotIn('private', (root / '.icloud_album_sync.json').read_text())

    def test_missing_listing_is_not_an_empty_album(self):
        client = sync.ICloudClient(40)
        with patch.object(client, '_post', return_value={'serverErrorCode': 'TRY_AGAIN'}):
            with self.assertRaises(sync.SyncError):
                client.list_album('https://www.icloud.com/sharedalbum/#synthetic', 0, 0)

    def test_repeated_modern_page_marker_fails_closed(self):
        client = sync.ICloudClient(40)
        resolved = {'results': [{'anonymousPublicAccess': {'token': 'synthetic',
                    'databasePartition': 'https://p1.ckdatabasews.icloud.com'}, 'zoneID': {}}]}
        with patch.object(client, '_cloudkit_post', side_effect=[resolved,
                {'records': [], 'continuationMarker': 'again'},
                {'records': [], 'continuationMarker': 'again'}]):
            with self.assertRaises(sync.SyncError):
                client._modern_public_album('synthetic', 0, 0)

    def test_request_error_does_not_expose_signed_url(self):
        client = sync.ICloudClient(40)
        with patch.object(client.session, 'post', side_effect=sync.requests.RequestException('https://example.test/?token=private')):
            with self.assertRaises(sync.SyncError) as caught:
                client._cloudkit_post('https://example.test', {}, {})
        self.assertNotIn('private', str(caught.exception))

    def test_truncated_download_does_not_replace_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'keep.jpg'
            target.write_bytes(b'original')
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.iter_content.return_value = [b'short']
            session = Mock()
            session.get.return_value = response
            item = sync.RemoteItem('guid', 'keep.jpg', 'https://example.test', 'image', None, 0, 0, 100, '', '')
            with self.assertRaises(sync.SyncError):
                sync.download_item(session, item, target, 40, 0)
            self.assertEqual(target.read_bytes(), b'original')
            self.assertFalse(target.with_name('keep.jpg.part').exists())

    def test_jpeg_upgrade_does_not_keep_heic_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'photo.heic').write_bytes(b'original')
            item = sync.RemoteItem('guid', 'photo.jpg', 'https://example.test', 'image', None, 0, 0, 0, '', '')
            names = sync.unique_filenames([item], {'guid': {'filename': 'photo.heic'}}, root)
            self.assertEqual(names['guid'], 'photo.jpg')
