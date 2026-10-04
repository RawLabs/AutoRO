from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildResult:
    """Standardized output from every estimate/build generator."""
    customer_pdf: Path
    advisor_pdf: Path | None = None
    subject: str | None = None
    sender: str | None = None

    def is_single(self) -> bool:
        return self.advisor_pdf is None

    def both(self) -> tuple[Path, Path]:
        if self.advisor_pdf is None:
            raise ValueError("No advisor PDF on this result.")
        return self.customer_pdf, self.advisor_pdf
