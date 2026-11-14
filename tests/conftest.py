import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "make_synthetic_trace", Path(__file__).parents[1] / "scripts" / "make_synthetic_trace.py"
)
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)
