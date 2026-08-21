# -*- coding: utf-8 -*-
"""
app.py —— Flask 入口：负责路由 + 提供 JSON API。

Series 与 Film 共用同一套页面模板 / JS / 接口（form 参数区分），
保证两层布局、交互、视觉风格完全一致。

运行：cd dashboard && python app.py
打开：http://127.0.0.1:5000
"""
from flask import Flask, jsonify, render_template, request, abort

import analytics

app = Flask(__name__)

VALID_FORMS = ("series", "film")
FORM_TITLES = {"series": "Series 系列动画", "film": "Film 动画电影"}


def _check_form(form):
    if form not in VALID_FORMS:
        abort(404)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/<form>")
def page(form):
    _check_form(form)
    return render_template("form.html", form=form, title=FORM_TITLES[form])


@app.route("/association")
def association():
    return render_template("association.html")


@app.route("/api/kpis")
def api_kpis():
    return jsonify(analytics.get_kpis())


@app.route("/api/overview")
def api_overview():
    return jsonify({
        "sentiment": analytics.get_sentiment(),
        "platform_dist": analytics.get_platform_dist(),
    })


@app.route("/api/association")
def api_association_page():
    return jsonify(analytics.get_association_page())


@app.route("/api/<form>/options")
def api_options(form):
    _check_form(form)
    return jsonify(analytics.get_options(form))


@app.route("/api/<form>/data")
def api_data(form):
    _check_form(form)
    return jsonify(analytics.get_data(
        form,
        work=request.args.get("work") or None,
        platform=request.args.get("platform") or None,
        sentiment=request.args.get("sentiment") or None,
    ))


@app.route("/api/<form>/association")
def api_association(form):
    _check_form(form)
    return jsonify(analytics.get_association(form))


@app.route("/api/<form>/balanced")
def api_balanced(form):
    """情感主口径 platform_balanced（封版，用于和 pooled 联动图区分）。"""
    _check_form(form)
    return jsonify(analytics.get_balanced(form))


@app.route("/api/comments")
def api_comments():
    form = request.args.get("form", "series")
    _check_form(form)
    return jsonify(analytics.get_comments(
        form=form,
        work=request.args.get("work") or None,
        platform=request.args.get("platform") or None,
        sentiment=request.args.get("sentiment") or None,
        offset=int(request.args.get("offset", 0)),
        limit=int(request.args.get("limit", 20)),
    ))


if __name__ == "__main__":
    # debug=True 便于开发期改代码自动重载；交付时可关掉
    app.run(debug=True)
