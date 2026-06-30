"""Console entry point for the packaged ACSP Streamlit application."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    """Run the bundled Streamlit field-map application."""
    app_path = Path(__file__).resolve().parent.parent / "gbif_fieldmap_builder_app.py"
    if not app_path.is_file():
        raise RuntimeError(f"Bundled Streamlit app was not found: {app_path}")

    from streamlit.web.cli import main as streamlit_main

    sys.argv = ["streamlit", "run", str(app_path), *sys.argv[1:]]
    streamlit_main()
