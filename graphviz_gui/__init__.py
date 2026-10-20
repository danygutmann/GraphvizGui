from flask import Flask, jsonify

from .config import Settings
from .files import DataStore
from .rendering import GraphvizRenderer


def create_app(settings=None):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(Settings.from_env())
    if settings:
        app.config.update(settings)
    app.config["MAX_CONTENT_LENGTH"] = app.config["MAX_REQUEST_BYTES"]
    app.extensions["data_store"] = DataStore(app.config["DATA_DIR"])
    app.extensions["graphviz_renderer"] = GraphvizRenderer(
        timeout=app.config["RENDER_TIMEOUT"],
        max_parallel=app.config["MAX_PARALLEL_RENDERS"],
        max_dot_bytes=app.config["MAX_DOT_BYTES"],
    )

    from .routes.api import api
    from .routes.web import web

    app.register_blueprint(api, url_prefix="/api/v1")
    app.register_blueprint(web)

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify(error={
            "code": "REQUEST_TOO_LARGE",
            "message": "The request exceeds the configured size limit.",
        }), 413

    @app.errorhandler(415)
    def unsupported_media_type(_error):
        return jsonify(error={
            "code": "UNSUPPORTED_MEDIA_TYPE",
            "message": "Send a JSON request with Content-Type: application/json.",
        }), 415

    return app
