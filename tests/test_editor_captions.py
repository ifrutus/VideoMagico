import os
import shutil
import subprocess
import tempfile
import unittest
import wave

from pipeline import captions, editor


class CaptionTests(unittest.TestCase):
    def test_transcript_chunks_and_fallback(self):
        transcript = {"segments": [
            {"words": [{"start": i, "end": i + .5, "word": f" palavra{i}"} for i in range(5)]},
            {"start": 6, "end": 7, "text": "Sem palavras", "words": []},
        ]}
        cues = captions.cues_from_transcript(transcript)
        self.assertEqual(len(cues), 3)
        self.assertEqual(cues[0], {"start": 0.0, "end": 3.5, "text": "palavra0 palavra1 palavra2 palavra3"})
        self.assertEqual(cues[1]["start"], 4)
        self.assertEqual(cues[2]["text"], "Sem palavras")

    def test_ass_escapes_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "captions.ass")
            captions.build_ass_for_cues([{"start": 0, "end": 1, "text": "{oi}\n\\N"}], path, 320, 240)
            with open(path, encoding="utf-8") as file:
                data = file.read()
            self.assertIn("(OI) ＼N", data)
            with self.assertRaises(ValueError):
                captions.build_ass_for_cues([{"start": 1, "end": 0, "text": "x"}], path, 320, 240)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg não disponível")
    def test_audio_timing_and_burned_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=2", "-y", source], check=True)
            assets = {"a": {"path": source, "kind": "audio", "has_audio": True}}
            clip = {"asset_id": "a", "start": .5, "dur": .75, "in": .25, "volume": 1}
            project = {"width": 320, "height": 240, "fps": 10,
                       "tracks": [{"type": "audio", "clips": [clip]}],
                       "captions": [{"start": .5, "end": 1.2, "text": "Olá mundo"}]}
            audio = os.path.join(tmp, "mix.wav")
            editor.extract_timeline_audio(project, assets, audio)
            with wave.open(audio, "rb") as wav:
                self.assertEqual(wav.getframerate(), 16000)
                samples = wav.readframes(wav.getnframes())
            import struct
            samples = struct.unpack(f"<{len(samples) // 2}h", samples)
            self.assertLess(max(abs(v) for v in samples[1600:4800]), 100)
            self.assertGreater(max(abs(v) for v in samples[9600:11200]), 500)
            out = os.path.join(tmp, "out.mp4")
            editor.export_timeline(project, assets, out)
            frame = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.8", "-i", out,
                                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                   check=True, capture_output=True).stdout
            self.assertGreater(max(frame), 150)
            project["tracks"][0]["muted"] = True
            with self.assertRaisesRegex(ValueError, "áudio ativo"):
                editor.extract_timeline_audio(project, assets, audio)


if __name__ == "__main__":
    unittest.main()
