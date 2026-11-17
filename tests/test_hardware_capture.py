import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "capture_hardware", pathlib.Path(__file__).parent.parent / "scripts" / "capture_hardware.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_collect_has_required_keys():
    info = _mod.collect()
    for key in ("timestamp_utc", "os", "cpu_threads", "python"):
        assert info[key]
