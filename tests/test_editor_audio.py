import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave

from pipeline import editor


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg não disponível")
class EditorAudioTests(unittest.TestCase):
    def test_waveform_shows_silence_and_sound_and_linked_audio_is_not_doubled(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "input.mp4")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=10:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000:duration=2",
                "-af", "volume=enable='lt(t,1)':volume=0", "-c:v", "libx264",
                "-c:a", "aac", "-shortest", "-y", video,
            ], check=True)
            peaks = editor.audio_peaks(video)
            self.assertGreaterEqual(len(peaks), 195)
            self.assertLess(max(peaks[10:80]), 0.01)
            self.assertGreater(max(peaks[120:180]), 0.08)
            asset = {"path": video, **editor.probe_media(video)}
            clip = {"asset_id": "v", "start": 0, "dur": 2, "in": 0, "volume": 1}
            project = {"width": 160, "height": 120, "fps": 10, "tracks": [
                {"type": "video", "clips": [dict(clip, audio_disabled=True)]},
                {"type": "audio", "clips": [dict(clip)]},
            ]}
            audio = os.path.join(tmp, "audio.wav")
            editor.extract_timeline_audio(project, {"v": asset}, audio)
            with wave.open(audio, "rb") as wav:
                data = wav.readframes(wav.getnframes())
            actual = struct.unpack(f"<{len(data) // 2}h", data)
            level = max(abs(s) for s in actual[19200:28800])
            self.assertGreater(level, 1500)
            self.assertLess(level, 6000)
            output = os.path.join(tmp, "output.mp4")
            editor.export_timeline(project, {"v": asset}, output)
            self.assertTrue(os.path.getsize(output) > 0)


if __name__ == "__main__":
    unittest.main()
