from __future__ import annotations

import unittest

from app.estimate_conversion import history_prefix
from app.estimate_naming import estimate_output_stem


class EstimateNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parsed = {
            "source_filename": "1782800000000000000_DAX NADERI GX460.pdf",
            "customer": {"name": "NADERI, DAX"},
            "vehicle": {"year": 2015, "make": "Lexus", "model": "GX 460 - Premium"},
            "estimate_number": "077470",
        }

    def test_three_modes_use_clear_customer_facing_names(self) -> None:
        self.assertEqual(
            "OUT_OF_SHOP_ESTIMATE_DAX_NADERI_GX460",
            estimate_output_stem(self.parsed, "preestimate"),
        )
        self.assertEqual(
            "IN_SHOP_ESTIMATE_DAX_NADERI_GX460",
            estimate_output_stem(self.parsed, "inshop"),
        )
        self.assertEqual(
            "CUSTOM_BUILD_DAX_NADERI_GX460",
            estimate_output_stem(self.parsed, "custom_build"),
        )

    def test_generic_source_falls_back_to_customer_vehicle_and_ro(self) -> None:
        parsed = dict(self.parsed)
        parsed["source_filename"] = "estimate.pdf"
        self.assertEqual(
            "OUT_OF_SHOP_ESTIMATE_DAX_NADERI_2015_LEXUS_GX_460_PREMIUM_RO077470",
            estimate_output_stem(parsed, "preestimate"),
        )

    def test_conversion_history_uses_the_same_visible_name(self) -> None:
        self.assertEqual(
            estimate_output_stem(self.parsed, "preestimate"),
            history_prefix(self.parsed, "preestimate"),
        )


if __name__ == "__main__":
    unittest.main()
