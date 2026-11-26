"""One-file launcher for the Gradio travel assistant."""

from pathlib import Path
import runpy
import sys


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_root))
    runpy.run_path(str(project_root / "app.py"), run_name="__main__")
