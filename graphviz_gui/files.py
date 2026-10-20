import json
import os
import re
import tempfile
from pathlib import Path


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
DIRECTORIES = ("projects", "templates", "macros", "examples", "config")


class DataStore:
    def __init__(self, data_dir):
        self.root = Path(data_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in DIRECTORIES:
            directory = self.root / name
            directory.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink() or not directory.resolve().is_relative_to(self.root):
                raise ValueError(f"The data directory {name} must not point outside DATA_DIR.")
        self._seed_defaults()

    def _seed_defaults(self):
        defaults = Path(__file__).parent / "defaults"
        for dirname in ("examples", "templates", "macros"):
            source = defaults / dirname
            target = self.root / dirname
            if not source.is_dir():
                continue
            for item in source.iterdir():
                destination = target / item.name
                if item.is_file() and not destination.exists():
                    destination.write_bytes(item.read_bytes())

    def _path(self, directory, filename, suffix):
        if not isinstance(filename, str) or not NAME_RE.fullmatch(filename):
            raise ValueError("Names may contain only letters, numbers, dots, underscores, and dashes.")
        if not filename.lower().endswith(suffix):
            filename += suffix
        path = (self.root / directory / filename).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid file path.")
        return path

    def list_projects(self):
        return sorted(path.name for path in (self.root / "projects").glob("*.dot") if path.is_file())

    def read_project(self, name):
        path = self._path("projects", name, ".dot")
        if not path.is_file():
            raise FileNotFoundError(name)
        if path.stat().st_size > 512_000:
            raise ValueError("Project exceeds the 512 KB limit.")
        return path.read_text(encoding="utf-8")

    def save_project(self, name, content, overwrite=False):
        path = self._path("projects", name, ".dot")
        if not isinstance(content, str):
            raise ValueError("Project content must be text.")
        try:
            size = len(content.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError("Project content must be valid UTF-8 text.") from exc
        if size > 512_000:
            raise ValueError("Project exceeds the 512 KB limit.")
        if path.exists() and not overwrite:
            raise FileExistsError(path.name)
        fd, temporary = tempfile.mkstemp(prefix=".project-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return path.name

    def list_documents(self, directory):
        if directory not in ("templates", "examples"):
            raise ValueError("Unsupported library.")
        result = []
        for path in sorted((self.root / directory).glob("*.dot")):
            if path.is_file() and path.resolve().is_relative_to(self.root):
                result.append({"name": path.stem, "filename": path.name})
        return result

    def read_document(self, directory, name):
        if directory not in ("templates", "examples"):
            raise ValueError("Unsupported library.")
        path = self._path(directory, name, ".dot")
        if not path.is_file():
            raise FileNotFoundError(name)
        if path.stat().st_size > 512_000:
            raise ValueError("DOT document exceeds the 512 KB limit.")
        return path.read_text(encoding="utf-8")

    def list_macros(self):
        result = []
        for path in sorted((self.root / "macros").glob("*.json")):
            if (
                not path.is_file()
                or not path.resolve().is_relative_to(self.root)
                or path.stat().st_size > 64_000
            ):
                continue
            try:
                macro = json.loads(path.read_text(encoding="utf-8"))
                if (
                    isinstance(macro, dict)
                    and all(isinstance(macro.get(key), str) for key in ("name", "description", "category", "dot"))
                    and isinstance(macro.get("parameters"), list)
                    and all(
                        isinstance(parameter, dict)
                        and all(isinstance(parameter.get(key), str) for key in ("name", "default", "description"))
                        for parameter in macro["parameters"]
                    )
                ):
                    result.append(macro)
            except (OSError, json.JSONDecodeError):
                continue
        return result
