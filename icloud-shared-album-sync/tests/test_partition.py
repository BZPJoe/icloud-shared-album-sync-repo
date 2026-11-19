"""Synthetic endpoint regressions; never contact Apple or expose real tokens."""
import unittest
from unittest.mock import patch
from test_sync import sync


class PartitionTests(unittest.TestCase):
    def resolve(self, partition, token="synthetic"):
        return {"results": [{"anonymousPublicAccess": {
            "token": token, "databasePartition": partition}, "zoneID": {}}]}

    def test_accepted_partitions(self):
        for host in (
            "ckdatabasews.icloud.com", "ckdatabasews.icloud.com.cn",
            "p1.ckdatabasews.icloud.com", "a.b.ckdatabasews.icloud.com.cn",
            "p51-ckdatabasews.icloud.com", "p123-ckdatabasews.icloud.com.cn",
            "P51-CKDATABASEWS.ICLOUD.COM",
        ):
            with self.subTest(host=host):
                client = sync.ICloudClient(40)
                partition = "https://" + host
                with patch.object(client, "_cloudkit_post", side_effect=[
                    self.resolve(partition), {"records": []}
                ]) as post:
                    self.assertEqual(client._modern_public_album("synthetic", 0, 0), [])
                self.assertEqual(post.call_count, 2)
                self.assertEqual(post.call_args.args[0], partition +
                    "/database/1/com.apple.photos.cloud/production/shared/records/query")
                self.assertEqual(post.call_args.args[2]["publicAccessAuthToken"], "synthetic")

    def test_rejected_partitions_do_not_receive_token(self):
        cases = [
            ("https://p51-ckdatabasews.icloud.com", ""),
            ("https://p51-ckdatabasews.icloud.com", None),
            ("http://p51-ckdatabasews.icloud.com", "synthetic"),
            ("//p51-ckdatabasews.icloud.com", "synthetic"),
        ]
        for host in (
            "", "evil.example", "127.0.0.1", "[::1]",
            "p51-ckdatabasews.icloud.com.evil.example",
            "ckdatabasews.icloud.com.cn.evil.example",
            "evilckdatabasews.icloud.com", "p51-ckdatabasewsXicloud.com",
            "p-ckdatabasews.icloud.com", "px51-ckdatabasews.icloud.com",
            "p５１-ckdatabasews.icloud.com", "p51-ckdatabasews.icloud.comm",
            "ckdatabasews.icloud.com@evil.example",
        ):
            cases.append(("https://" + host, "synthetic"))
        for partition, token in cases:
            with self.subTest(partition=partition, token=token):
                client = sync.ICloudClient(40)
                with patch.object(client, "_cloudkit_post", return_value=
                    self.resolve(partition, token)) as post:
                    with self.assertRaises(sync.SyncError) as caught:
                        client._modern_public_album("synthetic", 0, 0)
                self.assertEqual(post.call_count, 1)
                self.assertEqual(str(caught.exception), "Apple returned an invalid public media endpoint.")
