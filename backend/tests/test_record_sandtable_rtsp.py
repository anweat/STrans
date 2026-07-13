import unittest
from pathlib import Path

from scripts.record_sandtable_rtsp import build_ffmpeg_command


class SandtableRecordingTests(unittest.TestCase):
    def test_recording_uses_stream_copy_and_a_bounded_segment_ring(self):
        command = build_ffmpeg_command(
            ffmpeg="ffmpeg",
            source="rtsp://example.test:8554/live/live1",
            output_pattern=Path("recordings/live1_%03d.mkv"),
            segment_seconds=300,
            max_segments=96,
        )

        self.assertIn("copy", command)
        self.assertIn("segment", command)
        self.assertIn("96", command)
        self.assertIn("-rtsp_transport", command)


if __name__ == "__main__":
    unittest.main()
