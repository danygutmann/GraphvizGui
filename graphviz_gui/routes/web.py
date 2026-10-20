from flask import Blueprint, render_template

web = Blueprint("web", __name__)


@web.get("/")
def index():
    return render_template("index.html")


@web.get("/api/docs")
def swagger_docs():
    return render_template("swagger.html")
