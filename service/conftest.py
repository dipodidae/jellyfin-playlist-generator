"""
Pytest conftest: stub heavy optional deps that are not installed in the test venv
(sentence_transformers, scipy, psycopg2) so pure-logic tests can import the app
modules without needing the full production environment.

Each stub is installed ONLY when the real package cannot be imported. In CI /
the container (where the real deps are installed) the genuine modules are used
and these fakes never shadow them.
"""
import importlib.util
import sys
import types


def _stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


def _real_available(name: str) -> bool:
    """True if the real package is importable (so we must NOT stub it)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


# --- sentence_transformers ---
if "sentence_transformers" not in sys.modules and not _real_available("sentence_transformers"):
    _st = _stub("sentence_transformers")

    class _FakeST:
        def __init__(self, *a, **k):
            pass

        def encode(self, *a, **k):
            import numpy as np
            return np.zeros(768)

    _st.SentenceTransformer = _FakeST

# --- scipy / scipy.interpolate ---
if "scipy" not in sys.modules and not _real_available("scipy"):
    _sp = _stub("scipy")
    _spi = _stub("scipy.interpolate")

    class _FakeCubicSpline:
        def __init__(self, *a, **k):
            pass

        def __call__(self, x):
            return x

    _spi.CubicSpline = _FakeCubicSpline
    _sp.interpolate = _spi

# --- psycopg2 ---
if "psycopg2" not in sys.modules and not _real_available("psycopg2"):
    _pg = _stub("psycopg2")
    _pg_extras = _stub("psycopg2.extras")
    _pg_pool = _stub("psycopg2.pool")

    class _FakeRealDictCursor:
        pass

    class _FakeThreadedConnectionPool:
        def __init__(self, *a, **k):
            pass

    _pg_extras.RealDictCursor = _FakeRealDictCursor
    _pg_pool.ThreadedConnectionPool = _FakeThreadedConnectionPool
    _pg.extras = _pg_extras
    _pg.pool = _pg_pool
    _pg.connect = lambda *a, **k: None
    _pg.OperationalError = Exception
    _pg.Error = Exception
    _pg.InterfaceError = Exception
