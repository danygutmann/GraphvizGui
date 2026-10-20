# Graphviz Designer

Graphviz Designer is a single-container Flask application for editing DOT source, rendering diagrams with the locally installed Graphviz engine, and using the same renderer through a versioned REST API. It has no database and no required CDN access.

## Features and architecture

- Flask serves the responsive CodeMirror 6 editor, static bundled assets, and `/api/v1/`.
- Graphviz is invoked with a fixed argument list (no shell) and DOT passed over standard input.
- The renderer exposes installed formats and engines, checks DOT through Graphviz, bounds request size and execution time, and limits concurrent renders.
- File services create and seed `/data/{projects,templates,macros,examples,config}`. User additions in these directories survive container replacement.
- The OpenAPI document is served at `/api/v1/openapi.json`; the locally bundled Swagger UI is at `/api/docs`.
- `compose.yaml` is the Portainer-ready deployment configuration.

```text
graphviz_gui/
  routes/                 Flask API and web routes
  rendering.py            Graphviz allowlists, validation, and rendering
  files.py                Persistent, path-checked file storage
  config.py               Environment configuration
  defaults/{examples,templates,macros}/  Seed content
  templates/              Flask HTML pages
  static/                 Application CSS; editor and Swagger bundles are built
frontend/                 CodeMirror 6 source
tests/                    unittest API and Graphviz integration tests
.github/workflows/        Test and GHCR publication workflow
```

## Run locally

Install Python 3.12+, Node.js 22+, and Graphviz (`dot` must be on `PATH`).

```bash
python -m pip install -r requirements.txt
npm ci
npm run build
DATA_DIR=./data PORT=8080 python -m graphviz_gui.server
```

Open <http://localhost:8080>. The editor supports syntax highlighting, line numbers, indentation, examples/templates, macro insertion at the cursor, zoomable SVG/PNG preview, save/load, and DOT/render downloads. Enter the API token in the GUI when one is configured. Rendering errors do not replace the last successful preview.

Run tests, including real Graphviz renders of the bundled examples:

```bash
python -m unittest discover -s tests -v
```

## REST API

All routes are rooted under `/api/v1`:

| Method and path | Purpose | Authentication when `API_TOKEN` is set |
| --- | --- | --- |
| `POST /render` | Render JSON `{ "dot": "...", "format": "svg", "engine": "dot" }`; returns the file directly | Required |
| `POST /validate` | Validate JSON `{ "dot": "...", "engine": "dot" }`; returns `{ "valid": true, "diagnostics": "" }` | Required |
| `GET /health` | App and Graphviz availability | Public |
| `GET /formats` | Installed output formats (SVG/PNG/PDF when supported) | Public |
| `GET /engines` | Available layout engines | Public |
| `GET /templates`, `GET /templates/{name}` | List and read DOT templates | Public |
| `GET /examples`, `GET /examples/{name}` | List and read DOT examples | Public |
| `GET /macros` | List macro definitions | Public |
| `GET /projects`, `GET /projects/{name}` | List and load projects | Required |
| `GET /projects/{name}/download` | Download a DOT project | Required |
| `POST /projects` | Create `{ "name": "network", "dot": "digraph {}" }` | Required |
| `PUT /projects/{name}` | Replace a project | Required |

For private routes, set the `Authorization` header to the word `Bearer` followed by the configured token. With an empty `API_TOKEN`, API authentication is disabled. The GUI has an in-memory token field; the token is not saved in browser storage.

Examples:

```sh
curl http://localhost:8080/api/v1/health
curl -H 'Content-Type: application/json' \
  -d '{"dot":"digraph { A -> B }","format":"svg","engine":"dot"}' \
  http://localhost:8080/api/v1/render -o graph.svg
curl -H 'Content-Type: application/json' \
  -d '{"dot":"digraph { A -> B }"}' \
  http://localhost:8080/api/v1/validate
```

Formats and engines are allowlisted and reported from the installed Graphviz tools. Render errors return JSON such as:

```json
{"error":{"code":"INVALID_DOT","message":"The DOT source could not be rendered."}}
```

Common statuses: `200` success, `201` project created, `400` malformed request/unsupported option, `401` authentication failure, `409` project already exists, `413` body too large, `415` non-JSON request, `422` invalid DOT, and `503` render concurrency limit or unavailable Graphviz. A validation response with invalid DOT has `valid: false`, diagnostics, and status `422`. The full request/response schemas are exposed at `/api/v1/openapi.json`; interactive API documentation is at `/api/docs`.

## Security and limits

Defaults are `MAX_REQUEST_BYTES=1048576`, `MAX_DOT_BYTES=512000`, `RENDER_TIMEOUT=10` seconds, and `MAX_PARALLEL_RENDERS=2`. Override them with environment variables. A single Gunicorn worker shares the render semaphore across its request threads. Graphviz is called without shell parsing, with allowlisted engines/formats, a restricted process environment, a bounded timeout, and DOT on stdin. Project names are validated, file operations stay within their configured data subdirectory, project writes use atomic replacement, and an existing project requires explicit overwrite.

Rendered SVG is returned as `image/svg+xml` with a restrictive CSP and is shown in an `<img>` element rather than inserted as active HTML. Treat DOT as untrusted input and keep the container updated. Do not transmit API tokens unencrypted over the public Internet: use HTTPS through a properly configured reverse proxy or equivalent TLS termination, and restrict network access as appropriate.

## Persistent data, templates, and macros

The app creates `/data/projects`, `/data/templates`, `/data/macros`, `/data/examples`, and `/data/config` when missing. On first initialization it copies bundled sample files into the corresponding library directories without overwriting files already present. Add `.dot` files to `templates/` or `examples/`; add macro JSON files to `macros/`. These files are read from the mounted volume, so customization does not require a code change. Project `.dot` files are limited to 512 KB.

Macro JSON has a deliberately small format:

```json
{
  "name": "Directed connection",
  "description": "Connect two nodes with an arrow.",
  "category": "Connections",
  "parameters": [
    {"name": "from", "default": "A", "description": "Source node."},
    {"name": "to", "default": "B", "description": "Destination node."}
  ],
  "dot": "{from} -> {to};"
}
```

The GUI asks for each parameter and inserts the fragment at the current editor cursor. Place the cursor inside the graph body; insertion does not replace surrounding text.

The supplied examples cover a directed graph, flowchart, decision, layered system, Docker architecture, dependencies, and state machine. The test suite validates each with Graphviz.

Back up the NAS data directory, including projects, library files, and config, using the NAS backup mechanism. The container has no database to back up.

## Docker

The multi-stage Dockerfile builds CodeMirror and Swagger UI into local static files, installs Graphviz in the runtime image, and runs the app as UID `10001`. It exposes port `8080` and provides a Docker healthcheck. To build and run locally:

```sh
docker build -t graphvizgui:local .
docker run --rm -p 8088:8080 \
  -e API_TOKEN='set-a-long-random-token' \
  -v "$PWD/data:/data" graphvizgui:local
```

Ensure a bind-mounted data directory is writable by container UID `10001`. On a NAS, provision the directory permissions for that UID/GID before deployment. The configured NAS path is `/volume1/docker/Graphviz`.

## GitHub Actions and GHCR

`.github/workflows/container.yml` runs `npm ci`, bundles the frontend, installs Graphviz and Python requirements, and executes the tests for pull requests, pushes to `main`, and version-tag pushes. Only non-PR runs publish. The publish job uses Buildx, the Actions cache, and the repository-provided `GITHUB_TOKEN` with `packages: write`; no personal registry token is required. The image name is normalized to lowercase:

```text
ghcr.io/danygutmann/graphvizgui
```

Branch builds receive the branch and `sha-<commit>` tags. Push a semantic version tag such as `v1.2.3` to publish a version tag (and major/minor aliases) plus `latest`:

```sh
git tag v1.2.3
git push origin v1.2.3
```

In repository Actions settings, allow GitHub Actions to create and approve workflows if requested. The workflow requires the default `GITHUB_TOKEN` and the package write permission declared in the publish job. After release, verify the matching successful workflow run and its publish job in **Actions**, then check the package/tag in the repository's **Packages** section. Set the GHCR package visibility to public if you want Portainer to pull it without registry credentials. If a build or push fails, inspect that run's failing job logs, correct the cause, and re-run the workflow; do not deploy a tag that does not exist.

No GHCR publication has been performed by this repository change. The compose example below pins `v1.0.0` as a release placeholder; replace it with a tag confirmed in GHCR after a successful release workflow. Do not assume that tag is available before publishing.

## Portainer deployment (Compose Web Editor)

After publishing a version, replace the example image tag below with that verified release tag, paste the configuration into Portainer's Stack Web editor, and deploy. There is no NAS-side image build.

```yaml
services:
  graphviz-gui:
    image: ghcr.io/danygutmann/graphvizgui:v1.0.0
    container_name: graphviz-gui
    restart: unless-stopped
    ports:
      - "8088:8080"
    environment:
      PORT: "8080"
      DATA_DIR: /data
      API_TOKEN: ${API_TOKEN:-}
      RENDER_TIMEOUT: "10"
      MAX_PARALLEL_RENDERS: "2"
      MAX_REQUEST_BYTES: "1048576"
      MAX_DOT_BYTES: "512000"
    volumes:
      - /volume1/docker/Graphviz:/data
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=3)"
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
```

Set a long random `API_TOKEN` in Portainer's stack environment variables (or its supported environment file) before exposing the API. If GHCR is private, first add a registry credential in Portainer under **Registries** using a GitHub account/PAT with `read:packages`, then select it for the stack/image pull. For a public package, no registry login is required.

## Troubleshooting

- **Container unhealthy:** Check `docker logs graphviz-gui`; confirm Graphviz is available with `dot -V`, and that the health endpoint responds inside the container.
- **Cannot save projects / seed libraries:** Check `/volume1/docker/Graphviz` ownership and permissions for UID `10001`.
- **401 from render/validate/projects:** Provide the configured bearer token in the UI field or `Authorization` header.
- **Render error or timeout:** Check Graphviz diagnostics, simplify large graphs, or adjust the render timeout/concurrency limits.
- **Missing version in GHCR:** Confirm the pushed tag matches `vMAJOR.MINOR.PATCH`, and inspect the corresponding successful Actions publish job.
- **Local editor or Swagger assets missing:** Run `npm ci && npm run build` before starting Flask.
