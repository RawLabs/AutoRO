from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bg_rules import BG_DB_PATH, bg_service_options


class BGServiceTests(unittest.TestCase):
    def test_runtime_database_exposes_service_list(self) -> None:
        self.assertEqual("runtime", BG_DB_PATH.relative_to(Path(__file__).resolve().parents[1]).parts[0])
        services = bg_service_options()
        self.assertEqual(15, len(services))
        self.assertTrue(all(service["id"] and service["label"] for service in services))


if __name__ == "__main__":
    unittest.main()
