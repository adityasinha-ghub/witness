"""Put the src/ layout on sys.path so tests import witness without installing."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
