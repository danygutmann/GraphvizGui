import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphviz_gui import create_app
from graphviz_gui.files import DataStore
from graphviz_gui.rendering import GraphvizRenderer, RenderError


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "DATA_DIR": self.tempdir.name,
            "API_TOKEN": "",
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_home_health_and_documentation(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
        self.assertEqual(self.client.get("/api/docs").status_code, 200)
        spec = self.client.get("/api/v1/openapi.json").get_json()
        self.assertEqual(spec["openapi"], "3.0.3")

    def test_public_information_and_seeded_libraries(self):
        self.assertIn("svg", self.client.get("/api/v1/formats").get_json()["formats"])
        self.assertIn("dot", self.client.get("/api/v1/engines").get_json()["engines"])
        self.assertEqual(len(self.client.get("/api/v1/examples").get_json()["items"]), 7)
        self.assertGreaterEqual(len(self.client.get("/api/v1/macros").get_json()["macros"]), 10)

    def test_authentication_is_required_when_configured(self):
        protected = create_app({
            "TESTING": True,
            "DATA_DIR": self.tempdir.name,
            "API_TOKEN": "test-secret",
        }).test_client()
        unauthorized = protected.post("/api/v1/render", json={"dot": "digraph {}"})
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.get_json()["error"]["code"], "UNAUTHORIZED")
        self.assertEqual(protected.get("/api/v1/health").status_code, 200)
        authorized = protected.get("/api/v1/projects", headers={"Authorization": "Bearer " + "test-secret"})
        self.assertEqual(authorized.status_code, 200)

    def test_invalid_dot_has_structured_diagnostics(self):
        response = self.client.post("/api/v1/validate", json={"dot": "digraph {"})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.get_json()["valid"])
        self.assertIn("diagnostics", response.get_json())

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_real_svg_and_png_rendering(self):
        for output_format, content_type in (("svg", "image/svg+xml"), ("png", "image/png")):
            response = self.client.post(
                "/api/v1/render",
                json={"dot": "digraph { A -> B }", "format": output_format},
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content_type.startswith(content_type))
            self.assertGreater(len(response.data), 10)

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_every_bundled_example_is_valid_dot(self):
        renderer = self.app.extensions["graphviz_renderer"]
        example_dir = Path(self.tempdir.name) / "examples"
        for path in example_dir.glob("*.dot"):
            valid, diagnostics = renderer.validate(path.read_text(), "dot")
            self.assertTrue(valid, f"{path.name}: {diagnostics}")

    def test_project_saving_conflicts_and_path_protection(self):
        created = self.client.post("/api/v1/projects", json={"name": "example", "dot": "digraph {}"})
        self.assertEqual(created.status_code, 201)
        conflict = self.client.post("/api/v1/projects", json={"name": "example", "dot": "digraph {}"})
        self.assertEqual(conflict.status_code, 409)
        loaded = self.client.get("/api/v1/projects/example.dot")
        self.assertEqual(loaded.get_json()["dot"], "digraph {}")
        rejected = self.client.post("/api/v1/projects", json={"name": "../other", "dot": "digraph {}"})
        self.assertEqual(rejected.status_code, 400)

    def test_request_body_limit_returns_json(self):
        app = create_app({
            "TESTING": True,
            "DATA_DIR": self.tempdir.name,
            "API_TOKEN": "",
            "MAX_REQUEST_BYTES": 100,
        })
        response = app.test_client().post(
            "/api/v1/validate", data=json.dumps({"dot": "x" * 200}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["error"]["code"], "REQUEST_TOO_LARGE")

    def test_renderer_timeout_and_limit(self):
        renderer = GraphvizRenderer(timeout=0.1, max_parallel=1)
        with patch.object(renderer, "engines", return_value=["dot"]), \
                patch.object(renderer, "formats", return_value=["svg"]), \
                patch("graphviz_gui.rendering.subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("dot", 0.1)):
            with self.assertRaises(RenderError) as error:
                renderer.render("digraph {}", "dot", "svg")
        self.assertEqual(error.exception.code, "RENDER_TIMEOUT")
        renderer = GraphvizRenderer(max_dot_bytes=3)
        with self.assertRaises(RenderError) as error:
            renderer.render("digraph {}", "dot", "svg")
        self.assertEqual(error.exception.code, "DOT_TOO_LARGE")

    def test_projects_persist_across_app_restarts(self):
        self.client.post("/api/v1/projects", json={"name": "persistent", "dot": "digraph { A }"})
        restarted = create_app({"TESTING": True, "DATA_DIR": self.tempdir.name, "API_TOKEN": ""})
        response = restarted.test_client().get("/api/v1/projects/persistent")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["dot"], "digraph { A }")

    def test_data_directory_symlinks_cannot_escape_configured_root(self):
        root = Path(self.tempdir.name) / "unsafe"
        root.mkdir()
        outside = Path(self.tempdir.name) / "outside"
        outside.mkdir()
        (root / "projects").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            DataStore(root)

    def test_macro_library_skips_invalid_files(self):
        macro_dir = Path(self.tempdir.name) / "macros"
        (macro_dir / "broken.json").write_text('{"name": 3}', encoding="utf-8")
        response = self.client.get("/api/v1/macros")
        self.assertTrue(all(isinstance(item["name"], str) for item in response.get_json()["macros"]))

    def test_template_routes_and_openapi_paths(self):
        loaded = self.client.get("/api/v1/templates/simple-directed-graph")
        self.assertEqual(loaded.status_code, 200)
        self.assertIn("digraph", loaded.get_json()["dot"])
        self.assertIn("/render", self.client.get("/api/v1/openapi.json").get_json()["paths"])


if __name__ == "__main__":
    unittest.main()
