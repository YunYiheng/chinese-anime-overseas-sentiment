# -*- coding: utf-8 -*-
"""
app.py —— Flask 入口：负责路由 + 提供 JSON API。

Series 与 Film 共用同一套页面模板 / JS / 接口（form 参数区分），
保证两层布局、交互、视觉风格完全一致。

本地运行：cd dashboard && python app.py
打开：http://127.0.0.1:5000

云部署（Render）：gunicorn dashboard.app:app --bind 0.0.0.0:$PORT
（本文件最后的 app.run 只在直接 python 运行时生效；gunicorn 会跳过它）
"""
import os

from flask import Flask, jsonify, render_template, request, abort

try:
    import analytics  # 本地：cd dashboard && python app.py（cwd 在 dashboard/ 下）
except ImportError:
    import dashboard.analytics as analytics  # 云部署：gunicorn dashboard.app:app（cwd 在项目根）

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
    # 本地直接 python app.py 时：debug=True 便于开发期改代码自动重载。
    # 生产（gunicorn）不会进入这个分支，而是用 render.yaml 里的启动命令。
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
