import json
import unittest
from pathlib import Path
import app as studio

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.client = studio.app.test_client()

    def test_default_project_validates(self):
        project = json.loads(json.dumps(studio.DEFAULT_PROJECT))
        self.assertEqual(len(studio.validate_project(project)["scenes"]), 3)

    def test_invalid_preset_falls_back_to_preview(self):
        project = json.loads(json.dumps(studio.DEFAULT_PROJECT))
        project["settings"]["preset"] = "arbitrary"
        self.assertEqual(studio.validate_project(project)["settings"]["preset"], "preview")

    def test_path_traversal_is_rejected(self):
        self.assertIsNone(studio.safe_asset_path("../secret.txt"))
        self.assertIsNone(studio.safe_asset_path("/etc/passwd"))

    def test_homepage_and_diagnostics(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        response = self.client.get("/api/diagnostics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("ffmpeg", response.get_json())

    def test_media_and_exports_endpoints(self):
        self.assertEqual(self.client.get("/api/media").status_code, 200)
        self.assertEqual(self.client.get("/api/exports").status_code, 200)

    def test_neon_motion_frames_change_over_time(self):
        first, fw, fh = studio.motion_frame(0, 24, 480, 854, (155, 92, 255))
        later, fw2, fh2 = studio.motion_frame(12, 24, 480, 854, (155, 92, 255))
        self.assertEqual((fw, fh), (fw2, fh2))
        self.assertNotEqual(first, later)

    def test_empty_project_rejected(self):
        response = self.client.post("/api/render", json={"name": "empty", "scenes": [], "settings": {}})
        self.assertEqual(response.status_code, 400)

if __name__ == "__main__":
    unittest.main()
