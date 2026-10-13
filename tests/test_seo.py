import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

import app as website


class SearchDiscoveryTests(unittest.TestCase):
    def test_old_search_urls_redirect_to_their_content(self):
        client = website.app.test_client()
        for old, canonical in (("/index.html", "/"), ("/index", "/"),
                               ("/contact", "/contact.html"),
                               ("/services", "/services.html"),
                               ("/test-colour.html", "/test-appearance.html"),
                               ("/test-resistivity", "/test-tan-delta.html")):
            with self.subTest(url=old):
                response = client.get(old)
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response.headers["Location"], canonical)
                with client.get(canonical) as target:
                    self.assertEqual(target.status_code, 200)
        with client.get("/unknown-seo-page") as response:
            self.assertEqual(response.status_code, 404)

    def test_indexable_pages_use_the_live_domain_and_valid_json(self):
        for page in Path(website.SITE_DIR).glob("*.html"):
            with self.subTest(page=page.name):
                source = page.read_text(encoding="utf-8")
                self.assertNotIn("ladlielectricaltesting.com", source)
                url = "https://ladlilab.com/" + ("" if page.name == "index.html" else page.name)
                if page.name == "test-colour.html":
                    url = "https://ladlilab.com/test-appearance.html"
                elif page.name == "test-resistivity.html":
                    url = "https://ladlilab.com/test-tan-delta.html"
                self.assertIn(f'rel="canonical" href="{url}"', source)
                for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', source, re.S):
                    json.loads(block)

    def test_sitemap_lists_only_working_canonical_pages(self):
        root = ElementTree.parse(Path(website.SITE_DIR, "sitemap.xml"))
        urls = [node.text for node in root.findall(".//{*}loc")]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertIn("https://ladlilab.com/", urls)
        client = website.app.test_client()
        for url in urls:
            with self.subTest(url=url):
                parsed = urlsplit(url)
                self.assertEqual(parsed.netloc, "ladlilab.com")
                with client.get(parsed.path) as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn(b'content="noindex', response.data)
        self.assertIn("Sitemap: https://ladlilab.com/sitemap.xml",
                      Path(website.SITE_DIR, "robots.txt").read_text())


if __name__ == "__main__":
    unittest.main()
