import os
import shutil
import subprocess
import tempfile
import unittest

from pipeline import editor


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg não disponível")
class TransitionExportTests(unittest.TestCase):
    def test_fades_and_video_overlay_are_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            assets = {}
            for name, color in (("red", "red"), ("blue", "blue"), ("green", "green")):
                path = os.path.join(tmp, name + ".mp4")
                subprocess.run([
                    "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=160x120:r=10:d=2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-y", path,
                ], check=True)
                assets[name] = {"path": path, "kind": "video", "has_audio": False,
                                "width": 160, "height": 120}

            def clip(asset, start, duration, fade_in=0, fade_out=0):
                return {"asset_id": asset, "start": start, "dur": duration, "in": 0,
                        "fade_in": fade_in, "fade_out": fade_out}

            project = {"width": 160, "height": 120, "fps": 10, "tracks": [
                {"type": "video", "clips": [clip("red", 0, 1, fade_out=.5),
                                            clip("blue", 1, 1, fade_in=.5)]},
            ]}
            out = os.path.join(tmp, "transition.mp4")
            editor.export_timeline(project, assets, out)

            def pixel(t):
                result = subprocess.run([
                    "ffmpeg", "-v", "error", "-ss", str(t), "-i", out,
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
                ], check=True, capture_output=True).stdout
                offset = (60 * 160 + 80) * 3
                return tuple(result[offset:offset + 3])

            red, fade, blue = pixel(.2), pixel(.9), pixel(1.7)
            self.assertGreater(red[0], 200)
            self.assertLess(fade[0], 120)
            self.assertGreater(blue[2], 200)

            project["tracks"].insert(0, {"type": "video", "clips": [clip("green", .8, .4)]})
            editor.export_timeline(project, assets, out)
            overlay = pixel(.9)
            self.assertGreater(overlay[1], 70)
            self.assertLess(overlay[0], 40)
            self.assertGreater(pixel(.2)[0], 200)

    def test_vp9_alpha_effect_keeps_background_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            background = os.path.join(tmp, "background.mp4")
            effect = os.path.join(tmp, "effect.webm")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=c=blue:s=160x120:r=10:d=1", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-y", background,
            ], check=True)
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=c=black@0:s=160x120:r=10:d=1,format=rgba,"
                "drawbox=x=40:y=30:w=80:h=60:color=red@1:t=fill:replace=1",
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-y", effect,
            ], check=True)
            assets = {
                "background": {"path": background, "kind": "video", "has_audio": False, "width": 160, "height": 120},
                "effect": {"path": effect, "kind": "video", "has_audio": False, "width": 160, "height": 120},
            }
            project = {"width": 160, "height": 120, "fps": 10, "tracks": [
                {"type": "video", "clips": [{"asset_id": "effect", "start": 0, "dur": 1}]},
                {"type": "video", "clips": [{"asset_id": "background", "start": 0, "dur": 1}]},
            ]}
            self.assertTrue(editor.probe_media(effect)["vp9_alpha"])
            out = os.path.join(tmp, "alpha.mp4")
            editor.export_timeline(project, assets, out)
            frame = subprocess.run([
                "ffmpeg", "-v", "error", "-ss", "0.5", "-i", out,
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ], check=True, capture_output=True).stdout
            center = frame[(60 * 160 + 80) * 3:(60 * 160 + 80) * 3 + 3]
            corner = frame[(10 * 160 + 10) * 3:(10 * 160 + 10) * 3 + 3]
            self.assertGreater(center[0], 200)
            self.assertGreater(corner[2], 200)
            self.assertLess(corner[0], 40)


if __name__ == "__main__":
    unittest.main()
