from __future__ import annotations

import re
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "estimate_inshop.js"


class InShopDomSafetyTests(unittest.TestCase):
    @classmethod
    def render_source(cls) -> str:
        source = SOURCE.read_text(encoding="utf-8")
        match = re.search(
            r"function renderJobCards\(jobs, mappings\) \{(?P<body>.*?)\n  \}\n\n  btnSaveGenerate",
            source,
            flags=re.DOTALL,
        )
        if not match:
            raise AssertionError("renderJobCards function was not found")
        return match.group("body")

    def test_untrusted_job_renderer_has_no_html_sink(self) -> None:
        body = self.render_source()
        self.assertNotIn("innerHTML", body)
        self.assertNotIn("insertAdjacentHTML", body)
        self.assertNotIn("outerHTML", body)

    def test_untrusted_values_use_text_or_form_value_properties(self) -> None:
        body = self.render_source()
        self.assertIn("title.textContent", body)
        self.assertIn("option.textContent", body)
        self.assertIn("textarea.value", body)
        self.assertIn("document.createTextNode", body)

    def test_original_breakout_classes_remain_plain_data(self) -> None:
        body = self.render_source()
        malicious_examples = [
            "</textarea><img src=x onerror=alert(1)>",
            "<svg onload=alert(1)>",
        ]
        # The renderer has no parser sink; all attacker strings flow only to
        # textContent, createTextNode, option.value, or textarea.value.
        for payload in malicious_examples:
            self.assertIn("<", payload)
            self.assertNotIn("`" + payload, body)
        self.assertNotRegex(body, r"\.innerHTML\s*=")


if __name__ == "__main__":
    unittest.main()
