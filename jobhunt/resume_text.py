"""Read a resume from PDF, Markdown or plain text."""

from __future__ import annotations

from pathlib import Path


def read_resume(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{p} does not exist")
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(p))
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = "\n\n".join(pages).strip()
        if not text:
            raise ValueError(
                f"{p.name} has no extractable text (scanned PDF?). "
                "Export it as text or paste it into a .txt file."
            )
        return text
    return p.read_text(encoding="utf-8", errors="replace").strip()
