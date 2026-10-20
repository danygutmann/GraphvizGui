import re
import shutil
import subprocess
import threading


ENGINES = ("dot", "neato", "fdp", "sfdp", "twopi", "circo", "osage", "patchwork")
FORMATS = ("svg", "png", "pdf")


class RenderError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class GraphvizRenderer:
    def __init__(self, timeout=10, max_parallel=2, max_dot_bytes=512_000, executable="dot"):
        self.executable = shutil.which(executable) or executable
        self.timeout = timeout
        self.max_dot_bytes = max_dot_bytes
        self._slots = threading.BoundedSemaphore(max(1, max_parallel))
        self._formats = None
        self._formats_lock = threading.Lock()

    def engines(self):
        if not shutil.which(self.executable):
            return []
        return [engine for engine in ENGINES if engine == "dot" or shutil.which(engine)]

    def formats(self):
        if not shutil.which(self.executable):
            return []
        with self._formats_lock:
            if self._formats is None:
                try:
                    result = subprocess.run(
                        [self.executable, "-T?"], capture_output=True, text=True,
                        timeout=2, check=False,
                    )
                    available = set(re.findall(r"\b(?:svg|png|pdf)\b", result.stdout + result.stderr))
                    self._formats = [item for item in FORMATS if item in available]
                except (OSError, subprocess.TimeoutExpired):
                    self._formats = []
            return list(self._formats)

    def _run(self, dot, engine, output_format):
        if not isinstance(dot, str) or not dot.strip():
            raise RenderError("INVALID_DOT", "DOT source must be a non-empty string.")
        try:
            size = len(dot.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise RenderError("INVALID_DOT", "DOT source must be valid UTF-8 text.") from exc
        if size > self.max_dot_bytes:
            raise RenderError("DOT_TOO_LARGE", f"DOT source exceeds the {self.max_dot_bytes}-byte limit.")
        if engine not in ENGINES or engine not in self.engines():
            raise RenderError("UNSUPPORTED_ENGINE", "The requested layout engine is not available.")
        if output_format != "dot" and (output_format not in FORMATS or output_format not in self.formats()):
            raise RenderError("UNSUPPORTED_FORMAT", "The requested output format is not available.")
        if not self._slots.acquire(blocking=False):
            raise RenderError("RENDER_BUSY", "The renderer is busy. Retry shortly.")
        try:
            try:
                return subprocess.run(
                    [self.executable, f"-K{engine}", f"-T{output_format}"],
                    input=dot.encode("utf-8"), capture_output=True,
                    timeout=self.timeout, check=False, cwd="/",
                    env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                )
            except subprocess.TimeoutExpired as exc:
                raise RenderError("RENDER_TIMEOUT", "Graphviz exceeded the render time limit.") from exc
            except OSError as exc:
                raise RenderError("GRAPHVIZ_UNAVAILABLE", "The Graphviz engine could not be started.") from exc
        finally:
            self._slots.release()

    def validate(self, dot, engine="dot"):
        result = self._run(dot, engine, "dot")
        diagnostics = result.stderr.decode("utf-8", errors="replace").strip()
        if result.returncode:
            return False, diagnostics or "Graphviz rejected the DOT source."
        return True, diagnostics

    def render(self, dot, engine="dot", output_format="svg"):
        result = self._run(dot, engine, output_format)
        if result.returncode:
            raise RenderError(
                "INVALID_DOT",
                "The DOT source could not be rendered.",
            )
        return result.stdout
