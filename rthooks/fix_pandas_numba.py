"""
Runtime hook: provide a dummy pandas.core._numba module and submodules when pandas expects them
This avoids ModuleNotFoundError inside frozen apps when numba isn't installed.
"""
import sys
import types

def create_dummy_module(name):
    """Create a dummy module with minimal attributes."""
    mod = types.ModuleType(name)
    mod.__all__ = []
    return mod

MODULE_NAMES = [
    'pandas.core._numba',
    'pandas.core._numba.executor',
]

for module_name in MODULE_NAMES:
    if module_name not in sys.modules:
        try:
            # If the real module exists, let it load
            __import__(module_name)
        except Exception:
            # Create a lightweight module stub
            sys.modules[module_name] = create_dummy_module(module_name)
