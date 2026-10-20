import os


class Settings:
    @classmethod
    def from_env(cls):
        return {
            "DATA_DIR": os.environ.get("DATA_DIR", "/data"),
            "API_TOKEN": os.environ.get("API_TOKEN", ""),
            "MAX_REQUEST_BYTES": _positive_int("MAX_REQUEST_BYTES", 1_048_576),
            "MAX_DOT_BYTES": _positive_int("MAX_DOT_BYTES", 512_000),
            "RENDER_TIMEOUT": _positive_float("RENDER_TIMEOUT", 10),
            "MAX_PARALLEL_RENDERS": _positive_int("MAX_PARALLEL_RENDERS", 2),
        }


def _positive_int(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _positive_float(name, default):
    try:
        return max(0.1, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default
