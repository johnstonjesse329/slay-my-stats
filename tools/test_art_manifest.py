"""Tests for tools/art_manifest.py: python -m unittest tools.test_art_manifest"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import art_manifest  # noqa: E402


class ArtManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.manifest = self.root / "art_manifest.json"
        (self.root / "ui_icons" / "map").mkdir(parents=True)
        (self.root / "ui_icons" / "map" / "marked_x.png").write_bytes(b"x")
        (self.root / "card_final").mkdir()
        (self.root / "card_final" / "CARD.BASH.webp").write_bytes(b"bash")

    def tearDown(self):
        self._tmp.cleanup()

    def test_match_after_full_write(self):
        art_manifest.save(art_manifest.scan(self.root), self.manifest)
        self.assertEqual(art_manifest.problems(self.root, self.manifest), [])
        art_manifest.require_match(self.root, self.manifest)

    def test_missing_changed_and_extra_are_reported(self):
        art_manifest.save(art_manifest.scan(self.root), self.manifest)
        (self.root / "ui_icons" / "map" / "marked_x.png").unlink()
        (self.root / "card_final" / "CARD.BASH.webp").write_bytes(b"other bake")
        (self.root / "card_final" / "NEW.webp").write_bytes(b"n")
        found = art_manifest.problems(self.root, self.manifest)
        self.assertIn("missing: ui_icons/map/marked_x.png", found)
        self.assertIn("different: card_final/CARD.BASH.webp", found)
        self.assertIn("not in manifest: card_final/NEW.webp", found)
        with self.assertRaises(SystemExit):
            art_manifest.require_match(self.root, self.manifest)

    def test_no_manifest_refuses(self):
        with self.assertRaises(SystemExit):
            art_manifest.require_match(self.root, self.manifest)

    def test_update_replaces_only_its_prefix(self):
        art_manifest.save(art_manifest.scan(self.root), self.manifest)
        (self.root / "ui_icons" / "map" / "marked_x.png").unlink()
        (self.root / "ui_icons" / "map" / "circle.png").write_bytes(b"c")
        art_manifest.update(["ui_icons/map"], self.root, self.manifest)
        files = art_manifest.load(self.manifest)
        self.assertNotIn("ui_icons/map/marked_x.png", files)
        self.assertIn("ui_icons/map/circle.png", files)
        self.assertIn("card_final/CARD.BASH.webp", files)


if __name__ == "__main__":
    unittest.main()
