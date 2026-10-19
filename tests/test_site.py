"""The presentation site in docs/: served on hermez.dev, with the Hermez brand assets."""

from __future__ import annotations

import json
import re
import struct
import unittest
from pathlib import Path

from . import context  # noqa: F401  (adds src/ to the import path)

import whisper_desk

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SITE = "https://hermez.dev/whisper-desk/"


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    return struct.unpack(">II", header[16:24])


class SiteTest(unittest.TestCase):
    def setUp(self):
        self.html = (DOCS / "index.html").read_text(encoding="utf-8")

    def meta(self, attribute: str, name: str) -> str:
        found = re.search(rf'<meta {attribute}="{re.escape(name)}" content="([^"]*)"', self.html)
        self.assertIsNotNone(found, name)
        return found.group(1)

    def json_ld(self) -> dict:
        found = re.search(r'<script type="application/ld\+json">(.*?)</script>', self.html, re.S)
        return json.loads(found.group(1))

    def test_nothing_points_to_the_former_domain(self):
        # cardona.digital only redirects now, and the anchors get lost on the way;
        # the Umami instance stays on it, like the rest of the infrastructure.
        texts = [p for p in DOCS.iterdir() if p.suffix in {".html", ".txt", ".xml", ".md"}]
        for path in texts + [ROOT / "README.md"]:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8").replace("https://umami.cardona.digital/", "")
                self.assertNotIn("cardona.digital", text)

    def test_the_urls_are_the_ones_of_hermez_dev(self):
        self.assertIn(f'<link rel="canonical" href="{SITE}">', self.html)
        self.assertEqual(self.meta("property", "og:url"), SITE)
        self.assertEqual(self.json_ld()["url"], SITE)
        self.assertIn(f"<loc>{SITE}</loc>", (DOCS / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertIn(f"Sitemap: {SITE}sitemap.xml", (DOCS / "robots.txt").read_text(encoding="utf-8"))

    def test_umami_counts_the_visits_of_hermez_dev(self):
        self.assertRegex(self.html, r'<script src="https://umami\.[^"]+" [^>]*data-domains="hermez\.dev"')

    def test_the_share_image_is_1200_by_630(self):
        for image in (self.meta("property", "og:image"), self.meta("name", "twitter:image")):
            with self.subTest(image=image):
                self.assertTrue(image.startswith(SITE), image)
                self.assertEqual(png_size(DOCS / image.removeprefix(SITE)), (1200, 630))

    def test_the_author_is_the_hermez_organization(self):
        self.assertEqual(self.json_ld()["author"], {"@type": "Organization", "name": "Hermez", "url": "https://hermez.dev"})

    def test_the_favicons_exist(self):
        icons = re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]* href="([^"]+)"', self.html)
        self.assertTrue(icons)
        for icon in icons:
            with self.subTest(icon=icon):
                self.assertTrue((DOCS / icon).is_file())


class PackageTest(unittest.TestCase):
    def test_author_and_homepage(self):
        self.assertEqual(whisper_desk.__author__, "Hermez")
        self.assertEqual(whisper_desk.__homepage__, SITE)


if __name__ == "__main__":
    unittest.main()
