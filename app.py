"""Root-level entry point for Streamlit.

Run with: streamlit run app.py
"""

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from steam_analyst.ui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
