import shutil
import subprocess
import tempfile
from pathlib import Path

FALLBACK_SOFFICE_PATH = r"C:\Program Files\LibreOffice\program\soffice.exe"


def _find_soffice() -> str:
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    if Path(FALLBACK_SOFFICE_PATH).exists():
        return FALLBACK_SOFFICE_PATH
    raise RuntimeError(
        "LibreOffice (soffice) was not found on PATH or at the default Windows "
        "install location. PPTX-to-PDF conversion requires it to be installed."
    )


def convert_pptx_to_pdf(pptx_path: str, timeout: int = 60) -> bytes:
    """Convert a .pptx file to PDF bytes using headless LibreOffice."""
    soffice = _find_soffice()
    pptx_path = str(Path(pptx_path).resolve())

    with tempfile.TemporaryDirectory() as outdir:
        result = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir, pptx_path],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            raise RuntimeError(f"LibreOffice conversion failed (exit {result.returncode}): {stderr}")

        pdf_path = Path(outdir) / (Path(pptx_path).stem + ".pdf")
        if not pdf_path.exists():
            raise RuntimeError("LibreOffice did not produce a PDF output file.")

        return pdf_path.read_bytes()
