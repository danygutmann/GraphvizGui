import hmac
from flask import Blueprint, Response, current_app, jsonify, request

from ..rendering import ENGINES, FORMATS, RenderError

api = Blueprint("api", __name__)
MIME_TYPES = {"svg": "image/svg+xml", "png": "image/png", "pdf": "application/pdf"}


def _error(code, message, status):
    return jsonify(error={"code": code, "message": message}), status


@api.before_request
def require_token_for_private_routes():
    token = current_app.config.get("API_TOKEN", "")
    if not token:
        return None
    private = request.endpoint in {
        "api.render_graph", "api.validate_graph",
        "api.list_projects", "api.project", "api.download_project",
        "api.save_project",
    }
    if not private:
        return None
    authorization = request.headers.get("Authorization", "")
    supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(supplied, token):
        return _error("UNAUTHORIZED", "A valid authentication token is required.", 401)
    return None


@api.post("/render")
def render_graph():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("dot"), str):
        return _error("INVALID_REQUEST", "A JSON object with a string 'dot' field is required.", 400)
    renderer = current_app.extensions["graphviz_renderer"]
    try:
        data = renderer.render(
            payload["dot"],
            payload.get("engine", "dot"),
            payload.get("format", "svg"),
        )
    except RenderError as exc:
        status = 503 if exc.code == "RENDER_BUSY" else 400
        return _error(exc.code, exc.message, status)
    response = Response(data, content_type=MIME_TYPES[payload.get("format", "svg")])
    response.headers["Content-Disposition"] = "inline"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if payload.get("format", "svg") == "svg":
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return response


@api.post("/validate")
def validate_graph():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("dot"), str):
        return _error("INVALID_REQUEST", "A JSON object with a string 'dot' field is required.", 400)
    try:
        valid, diagnostics = current_app.extensions["graphviz_renderer"].validate(
            payload["dot"], payload.get("engine", "dot")
        )
    except RenderError as exc:
        return _error(exc.code, exc.message, 400)
    return jsonify(valid=valid, diagnostics=diagnostics), (200 if valid else 422)


@api.get("/health")
def health():
    available = bool(current_app.extensions["graphviz_renderer"].engines())
    body = {"status": "ok" if available else "error", "graphviz": available}
    return jsonify(body), (200 if available else 503)


@api.get("/formats")
def formats():
    return jsonify(formats=current_app.extensions["graphviz_renderer"].formats())


@api.get("/engines")
def engines():
    return jsonify(engines=current_app.extensions["graphviz_renderer"].engines())


@api.get("/templates")
@api.get("/examples")
def templates():
    library = "examples" if request.path.endswith("/examples") else "templates"
    return jsonify(items=current_app.extensions["data_store"].list_documents(library))


@api.get("/templates/<name>")
@api.get("/examples/<name>")
def get_template(name):
    library = "examples" if request.path.startswith("/api/v1/examples/") else "templates"
    try:
        dot = current_app.extensions["data_store"].read_document(library, name)
    except (ValueError, FileNotFoundError):
        return _error("NOT_FOUND", "The requested template was not found.", 404)
    return jsonify(name=name, dot=dot)


@api.get("/macros")
def macros():
    return jsonify(macros=current_app.extensions["data_store"].list_macros())


@api.get("/projects")
def list_projects():
    return jsonify(projects=current_app.extensions["data_store"].list_projects())


@api.get("/projects/<name>")
def project(name):
    try:
        dot = current_app.extensions["data_store"].read_project(name)
    except ValueError:
        return _error("INVALID_NAME", "The project name is invalid.", 400)
    except FileNotFoundError:
        return _error("NOT_FOUND", "The requested project was not found.", 404)
    return jsonify(name=name, dot=dot)


@api.get("/projects/<name>/download")
def download_project(name):
    try:
        dot = current_app.extensions["data_store"].read_project(name)
    except (ValueError, FileNotFoundError):
        return _error("NOT_FOUND", "The requested project was not found.", 404)
    response = Response(dot, content_type="text/vnd.graphviz; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="{name.removesuffix(".dot")}.dot"'
    return response


@api.put("/projects/<name>")
@api.post("/projects")
def save_project(name=None):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("dot"), str):
        return _error("INVALID_REQUEST", "A JSON object with a string 'dot' field is required.", 400)
    name = name or payload.get("name", "")
    overwrite = payload.get("overwrite", request.method == "PUT")
    if not isinstance(overwrite, bool):
        return _error("INVALID_REQUEST", "'overwrite' must be a boolean.", 400)
    try:
        saved_name = current_app.extensions["data_store"].save_project(
            name, payload["dot"], overwrite=overwrite
        )
    except FileExistsError:
        return _error("PROJECT_EXISTS", "The project already exists; set overwrite=true to replace it.", 409)
    except ValueError:
        return _error("INVALID_PROJECT", "The project name or contents are invalid.", 400)
    return jsonify(name=saved_name), 200 if request.method == "PUT" else 201


@api.get("/openapi.json")
def openapi():
    return jsonify(OPENAPI)


OPENAPI = {
    "openapi": "3.0.3",
    "info": {
        "title": "Graphviz Designer API",
        "version": "1.0.0",
        "description": "Render and validate DOT documents. Private endpoints use HTTP bearer authentication when configured.",
    },
    "servers": [{"url": "/api/v1"}],
    "components": {
        "securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}},
        "schemas": {
            "Error": {
                "type": "object",
                "properties": {"error": {"type": "object", "properties": {
                    "code": {"type": "string"}, "message": {"type": "string"},
                }, "required": ["code", "message"]}},
                "required": ["error"],
            },
            "DotRequest": {
                "type": "object", "required": ["dot"],
                "properties": {
                    "dot": {"type": "string", "example": "digraph { A -> B }"},
                    "format": {"type": "string", "enum": list(FORMATS), "default": "svg"},
                    "engine": {"type": "string", "enum": list(ENGINES), "default": "dot"},
                },
            },
            "ValidateRequest": {
                "type": "object", "required": ["dot"],
                "properties": {
                    "dot": {"type": "string", "example": "digraph { A -> B }"},
                    "engine": {"type": "string", "enum": list(ENGINES), "default": "dot"},
                },
            },
            "ProjectRequest": {
                "type": "object", "required": ["name", "dot"],
                "properties": {
                    "name": {"type": "string", "example": "network"},
                    "dot": {"type": "string", "example": "digraph { A -> B }"},
                    "overwrite": {"type": "boolean", "default": False},
                },
            },
            "ProjectUpdateRequest": {
                "type": "object", "required": ["dot"],
                "properties": {
                    "dot": {"type": "string", "example": "digraph { A -> B }"},
                    "overwrite": {"type": "boolean", "default": True},
                },
            },
        },
    },
    "paths": {
        "/render": {"post": {
            "summary": "Render DOT to an image or document",
            "security": [{"BearerAuth": []}],
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/DotRequest"},
                "example": {"dot": "digraph { A -> B }", "format": "svg", "engine": "dot"},
            }}},
            "responses": {
                "200": {"description": "Rendered file", "content": {
                    "image/svg+xml": {"schema": {"type": "string", "format": "binary"}},
                    "image/png": {"schema": {"type": "string", "format": "binary"}},
                    "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                }},
                "400": {"description": "Invalid request, DOT, engine, or format", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                "401": {"description": "Missing or invalid token"},
                "413": {"description": "Request too large"},
                "503": {"description": "Render concurrency limit reached"},
            },
        }},
        "/validate": {"post": {
            "summary": "Validate DOT with Graphviz",
            "security": [{"BearerAuth": []}],
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/ValidateRequest"},
                "example": {"dot": "digraph { A -> B }", "engine": "dot"},
            }}},
            "responses": {
                "200": {"description": "Valid DOT"},
                "422": {"description": "Invalid DOT with diagnostics"},
                "401": {"description": "Missing or invalid token"},
            },
        }},
        "/health": {"get": {"summary": "Application and Graphviz health", "responses": {"200": {"description": "Healthy"}, "503": {"description": "Graphviz unavailable"}}}},
        "/formats": {"get": {"summary": "Installed output formats", "responses": {"200": {"description": "Available formats"}}}},
        "/engines": {"get": {"summary": "Available layout engines", "responses": {"200": {"description": "Available engines"}}}},
        "/templates": {"get": {"summary": "List templates", "responses": {"200": {"description": "Templates"}}}},
        "/templates/{name}": {"get": {"summary": "Read template DOT", "parameters": [{"in": "path", "name": "name", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "DOT template"}, "404": {"description": "Not found"}}}},
        "/examples": {"get": {"summary": "List examples", "responses": {"200": {"description": "Examples"}}}},
        "/examples/{name}": {"get": {"summary": "Read example DOT", "parameters": [{"in": "path", "name": "name", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "DOT example"}, "404": {"description": "Not found"}}}},
        "/macros": {"get": {"summary": "List DOT macros", "responses": {"200": {"description": "Macros"}}}},
        "/projects": {
            "get": {"summary": "List projects", "security": [{"BearerAuth": []}], "responses": {"200": {"description": "Projects"}, "401": {"description": "Unauthorized"}}},
            "post": {
                "summary": "Create project",
                "security": [{"BearerAuth": []}],
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/ProjectRequest"},
                    "example": {"name": "network", "dot": "digraph { A -> B }"},
                }}},
                "responses": {"201": {"description": "Created"}, "400": {"description": "Invalid project"}, "401": {"description": "Unauthorized"}, "409": {"description": "Already exists"}},
            },
        },
        "/projects/{name}": {
            "get": {"summary": "Load project", "security": [{"BearerAuth": []}], "parameters": [{"in": "path", "name": "name", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "DOT project"}, "401": {"description": "Unauthorized"}, "404": {"description": "Not found"}}},
            "put": {
                "summary": "Update project",
                "security": [{"BearerAuth": []}],
                "parameters": [{"in": "path", "name": "name", "required": True, "schema": {"type": "string"}}],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProjectUpdateRequest"}}}},
                "responses": {"200": {"description": "Updated"}, "400": {"description": "Invalid project"}, "401": {"description": "Unauthorized"}},
            },
        },
        "/projects/{name}/download": {"get": {"summary": "Download DOT project", "security": [{"BearerAuth": []}], "parameters": [{"in": "path", "name": "name", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "DOT file"}, "401": {"description": "Unauthorized"}, "404": {"description": "Not found"}}}},
    },
}
