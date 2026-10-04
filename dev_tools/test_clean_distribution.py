from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "shop_template" / "deploy_shop.py"
SPEC = importlib.util.spec_from_file_location("deploy_shop", MODULE_PATH)
assert SPEC and SPEC.loader
deploy_shop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy_shop)


class CleanDistributionTests(unittest.TestCase):
    def make_template(self, root: Path, contaminated: bool = False) -> Path:
        template = root / "template"
        database = template / "runtime" / "Database" / "autoro.db"
        database.parent.mkdir(parents=True)
        (template / "runtime" / "data").mkdir(parents=True)
        (template / "runtime" / "data" / "rules.json").write_text("{}", encoding="utf-8")
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE cases (id INTEGER PRIMARY KEY, notes TEXT)")
            if contaminated:
                connection.execute("INSERT INTO cases (notes) VALUES ('customer record')")
            connection.commit()
        return template

    def test_template_database_must_have_no_business_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            template = self.make_template(Path(temp_dir), contaminated=True)
            with self.assertRaisesRegex(ValueError, "contaminated"):
                deploy_shop.validate_clean_template(template)

    def test_estimate_runtime_records_are_not_copied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            target.mkdir()

            for relative in deploy_shop.ESTIMATE_IMMUTABLE_PATHS:
                folder = source / "estimate_conversion" / relative
                folder.mkdir(parents=True)
                (folder / "code.py").write_text("# application code\n", encoding="utf-8")

            workspace = source / "estimate_conversion" / "workspace"
            for name in ("uploads", "autoro_outbox", "import_records"):
                folder = workspace / name
                folder.mkdir(parents=True)
                (folder / "customer-data.txt").write_text("private", encoding="utf-8")

            original_core_paths = deploy_shop.CORE_PATHS
            try:
                deploy_shop.CORE_PATHS = []
                deploy_shop.copy_immutable_application(source, target)
            finally:
                deploy_shop.CORE_PATHS = original_core_paths

            self.assertTrue(
                (target / "estimate_conversion" / "workspace" / "estimates" / "code.py").is_file()
            )
            for name in ("uploads", "autoro_outbox", "import_records"):
                self.assertFalse(
                    (target / "estimate_conversion" / "workspace" / name / "customer-data.txt").exists()
                )

    def test_clean_runtime_contains_reference_data_and_empty_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = self.make_template(root)
            target = root / "target"
            target.mkdir()

            deploy_shop.create_clean_runtime(template, target)

            self.assertTrue((target / "runtime" / "Database" / "autoro.db").is_file())
            self.assertTrue((target / "runtime" / "data" / "rules.json").is_file())
            for relative in deploy_shop.RUNTIME_DIRS:
                directory = target / relative
                self.assertTrue(directory.is_dir())
                if relative == "runtime/Database":
                    self.assertEqual(["autoro.db"], [path.name for path in directory.iterdir()])
                else:
                    self.assertEqual([], list(directory.iterdir()))

    def test_existing_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            (target / "old-shop.db").write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                deploy_shop.require_empty_target(target)


if __name__ == "__main__":
    unittest.main()
