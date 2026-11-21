"""Security tests: untrusted remote data must never reach the terminal or the OS raw."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bitsearch as b  # noqa: E402

GOOD = "a" * 40


class Security(unittest.TestCase):
    def test_clean_strips_ansi_and_control_chars(self):
        evil = "ok\x1b[2J\x1b]0;pwned\x07\r\n\x9bname"
        out = b.clean(evil)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)
        self.assertNotIn("\x9b", out)
        self.assertNotIn("\n", out)

    def test_result_fields_are_sanitised(self):
        r = b.result("src\x1b[31m", "na\x1bme\r", 1, 1, 1, "magnet:?xt=urn:btih:x\x1b", GOOD)
        for k in ("source", "name", "link"):
            self.assertNotIn("\x1b", r[k])
            self.assertNotIn("\r", r[k])

    def test_magnet_rejects_injected_infohash(self):
        for bad in (GOOD + "&tr=http://evil", "zz", "", "a" * 39, "a" * 41,
                    "../../etc", "a" * 40 + "\n"):
            self.assertEqual(b.magnet(bad, "n"), "", bad)

    def test_magnet_accepts_hex_and_base32(self):
        self.assertTrue(b.magnet(GOOD, "n").startswith("magnet:?xt=urn:btih:" + GOOD))
        self.assertTrue(b.magnet("A" * 32, "n").startswith("magnet:?xt=urn:btih:"))

    def test_magnet_name_cannot_inject_parameters(self):
        m = b.magnet(GOOD, "x&xt=urn:btih:" + "b" * 40 + "&tr=http://evil")
        self.assertEqual(m.count("xt="), 1)
        self.assertNotIn("&tr=http://evil", m)

    def test_result_drops_invalid_infohash(self):
        self.assertEqual(b.result("s", "n", 1, 1, 1, "", "bad&x=1")["infohash"], "")

    def test_safe_link_only_allows_expected_schemes(self):
        for ok in ("magnet:?xt=urn:btih:" + GOOD, "https://a.b/c.torrent", "http://127.0.0.1:1/x"):
            self.assertTrue(b.safe_link(ok), ok)
        for bad in ("--help", "-o/tmp/x", "file:///etc/passwd", "javascript:alert(1)",
                    "smb://x/y", "ftp://x", "", "  file:///x"):
            self.assertEqual(b.safe_link(bad), "", bad)

    def test_mask_hides_api_keys(self):
        self.assertNotIn("SECRET123", b.mask("http://x/dl?apikey=SECRET123&a=1"))

    def test_redirect_to_non_http_scheme_is_refused(self):
        h = b._HttpOnlyRedirect()
        import urllib.request as ur
        for bad in ("ftp://x/y", "file:///etc/passwd", "gopher://x"):
            with self.assertRaises(Exception):
                h.redirect_request(ur.Request("http://a/"), None, 302, "Found", {}, bad)

    def test_oversized_response_is_refused(self):
        import io
        import urllib.request as ur

        class Fake(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        orig, b.MAX_BYTES = b._OPENER.open, 10
        b._OPENER.open = lambda *a, **k: Fake(b"x" * 100)
        try:
            with self.assertRaises(ValueError):
                b.http_get("http://a/")
        finally:
            b._OPENER.open, b.MAX_BYTES = orig, 20 * 1024 * 1024

    def test_xml_doctype_and_entities_refused_in_any_encoding(self):
        xml = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "x">]><r>&a;</r>'
        for enc in ("utf-8", "utf-16", "utf-16-le", "utf-16-be"):
            data = xml.encode(enc)
            if enc.startswith("utf-16-"):
                data = xml.replace("<?xml version=\"1.0\"?>", "").encode(enc)
            with self.assertRaises(ValueError, msg=enc):
                b.safe_xml(data)

    def test_xml_billion_laughs_refused(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
                '<l>&b;</l>')
        with self.assertRaises(ValueError):
            b.safe_xml(bomb.encode("utf-16"))

    def test_xml_normal_document_still_parses(self):
        root = b.safe_xml(b'<?xml version="1.0"?><rss><item><title>t</title></item></rss>')
        self.assertEqual(root.find("item/title").text, "t")

    def test_redact_removes_keys_from_error_messages(self):
        key = "".join(["fake", "%2F", "value", "+", "abc"])
        msg = f"URLError: <urlopen error http://x/api?apikey={key}&t=search> raw {key} enc {b.urllib.parse.quote(key)}"
        out = b.redact(msg, [key])
        self.assertNotIn("fake", out)
        self.assertNotIn("abc", out)

    def test_mask_covers_token_and_encoded_keys(self):
        self.assertNotIn("a%2Fb", b.mask("http://x/?APIKEY=a%2Fb&q=1"))
        self.assertNotIn("zzz", b.mask("http://x/?token=zzz"))
        self.assertIn("q=1", b.mask("http://x/?apikey=k&q=1"))

    def test_search_errors_never_contain_the_configured_key(self):
        key = "".join(["fake", "-", "test", "-", "value", "-", "0042"])  # built at runtime: not a real secret
        orig_cfg, orig_pub = b.load_config, dict(b.PUBLIC)
        b.load_config = lambda: {"torznab": [{"name": "t", "url": "http://127.0.0.1:1/api",
                                                "apikey": key, "enabled": True}]}
        b.PUBLIC.clear()
        orig_tz = b.s_torznab
        def boom(q, cfg, label="t"):
            raise RuntimeError(f"failed http://127.0.0.1:1/api?apikey={key}&t=search")
        b.s_torznab = boom
        try:
            _, errors, _ = b.search("x", privacy="private")
        finally:
            b.load_config, b.s_torznab = orig_cfg, orig_tz
            b.PUBLIC.update(orig_pub)
        self.assertTrue(errors)
        self.assertNotIn(key, " ".join(errors.values()))


if __name__ == "__main__":
    unittest.main()
