import os
from pathlib import Path

from .api import DEFAULT_DATA, create_app

app = create_app(Path(os.environ.get("PAPER_NOTES_DATA", DEFAULT_DATA)))
