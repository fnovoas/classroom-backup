import tempfile
import unittest
from pathlib import Path

from src import drive_download, drive_video


class CommitPartFileTests(unittest.TestCase):
    def test_replaces_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "video.mp4"
            part = root / "video.mp4.part"

            target.write_text("old", encoding="utf-8")
            part.write_text("new", encoding="utf-8")

            drive_video._commit_part_file(part, target)

            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertFalse(part.exists())

    def test_pick_best_stream_supports_unencoded_fmt_stream_map(self) -> None:
        info = {
            "fmt_stream_map": "itag=18&url=https%3A%2F%2Fexample.com%2Fvideo.mp4&type=video%2Fmp4&quality=medium",
            "fmt_list": "18/640x360",
        }

        stream = drive_video.pick_best_stream(info)

        self.assertIsNotNone(stream)
        self.assertEqual(stream["itag"], "18")
        self.assertEqual(stream["url"], "https://example.com/video.mp4")

    def test_download_block_reason_for_view_only_files(self) -> None:
        meta = {"capabilities": {"canDownload": False}}

        self.assertEqual(drive_download._download_block_reason(meta), "view_only")


if __name__ == "__main__":
    unittest.main()
