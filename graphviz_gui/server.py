import os
import sys

from gunicorn.app.wsgiapp import run


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    sys.argv = [
        "gunicorn",
        "--bind", f"0.0.0.0:{port}",
        "--workers", "1",
        "--threads", "4",
        "--timeout", "30",
        "graphviz_gui:create_app()",
    ]
    run()
