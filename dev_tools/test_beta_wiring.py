from __future__ import annotations

import inspect
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BetaWiringTests(unittest.TestCase):
    def test_supported_launchers_use_one_qwen3_model(self) -> None:
        launchers = [
            ROOT / "start_autoro_linux.sh",
            ROOT / "Double Click to Start AutoRO Windows Useres .bat",
            ROOT / "Launch AutoRO (PowerShell).ps1",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in launchers)
        self.assertIn("Qwen3-4B-Instruct-2507-Q4_K_M.gguf", combined)
        self.assertNotIn("start_estimate_model", combined)
        self.assertNotIn("8081", combined)
        self.assertIn("runtime\\Database\\autoro.db", combined)

    def test_linux_browser_opens_when_web_app_is_ready(self) -> None:
        source = (ROOT / "start_autoro_linux.sh").read_text(encoding="utf-8")
        self.assertIn("Opening browser while the Qwen model finishes loading", source)
        self.assertIn("Browser launch request sent.", source)
        self.assertIn("AutoRO could not open the browser automatically.", source)
        self.assertIn("The existing AutoRO session is healthy; a second copy was not started.", source)
        self.assertIn("Press Enter to close this launcher", source)

    def test_dashboard_tracks_shared_qwen_after_startup(self) -> None:
        source = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("engines.estimate_ai", source)
        self.assertIn("engines.translator || sharedEngine", source)
        self.assertIn("engines.estimate_ai || engines.estimator || sharedEngine", source)
        self.assertIn("allOnline ? 10000 : 3000", source)
        self.assertIn("window.setTimeout(loadDashboardReadiness, 3000)", source)

    def test_customer_communication_brand_is_consistent(self) -> None:
        active_brand_files = [
            ROOT / "README.md",
            ROOT / "app" / "main.py",
            ROOT / "app" / "prompt_templates.py",
            *sorted((ROOT / "app" / "templates").glob("*.html")),
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in active_brand_files)
        self.assertIn("AutoRO Communication Layer", combined)
        self.assertIn("Turning shop findings into customer-ready explanations.", combined)
        self.assertNotIn("AutoRO AI Shop Layer", combined)
        self.assertNotIn("Calgary independent shop layer", combined)

    def test_retired_second_model_scripts_are_absent(self) -> None:
        for name in (
            "start_estimate_model.bat",
            "start_estimate_model_linux.sh",
            "test_estimate_api.ps1",
            "test_estimate_api_linux.sh",
        ):
            self.assertFalse((ROOT / "Llamafile" / name).exists(), name)

    def test_inshop_model_work_does_not_block_event_loop(self) -> None:
        from app.routes import analyze_inshop_estimate

        source = inspect.getsource(analyze_inshop_estimate)
        self.assertIn("await run_in_threadpool", source)

    def test_inshop_pdfs_use_configured_estimate_output(self) -> None:
        from app.routes import generate_inshop_pdf

        source = inspect.getsource(generate_inshop_pdf)
        self.assertIn('conversion_paths()["output_dir"]', source)
        self.assertNotIn('/ "reports"', source)

    def test_fastapi_uses_lifespan_startup(self) -> None:
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("lifespan=lifespan", source)
        self.assertNotIn('@app.on_event("startup")', source)

    def test_release_identity_covers_supported_launchers_and_deployment(self) -> None:
        from dev_tools.release_identity import DEFAULT_INCLUDE_GLOBS

        for required in (
            "Double Click to Start AutoRO Windows Useres .bat",
            "Launch AutoRO (PowerShell).ps1",
            "Llamafile/*.bat",
            "Llamafile/*.sh",
            "shop_template/*.py",
            "shop_template/.env.template",
            "requirements.txt",
            "docs/*.md",
        ):
            self.assertIn(required, DEFAULT_INCLUDE_GLOBS)


if __name__ == "__main__":
    unittest.main()
