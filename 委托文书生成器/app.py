# -*- coding: utf-8 -*-
"""委托文书生成器 —— 本地 Web 服务。

用法：./启动.command 或 ./.venv/bin/python app.py
浏览器访问 http://127.0.0.1:5092
"""
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import date

from flask import Flask, jsonify, request, send_from_directory

import docgen
import ocr
import parsers
from demo_templates import ensure_demo_templates

BASE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(BASE, "templates_docx")
OUT_DIR = os.path.join(BASE, "output")
UPLOAD_DIR = os.path.join(BASE, "uploads")
MAP_FILE = os.path.join(BASE, "mappings.json")

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".pdf", ".heic"}

app = Flask(__name__, static_folder=os.path.join(BASE, "web"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024


def load_mappings():
    if os.path.exists(MAP_FILE):
        try:
            with open(MAP_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_mappings(m):
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def template_list():
    ensure_demo_templates()
    mappings = load_mappings()
    items = []
    for fn in sorted(os.listdir(TPL_DIR)):
        if not fn.endswith(".docx") or fn.startswith("~$"):
            continue
        path = os.path.join(TPL_DIR, fn)
        tokens = docgen.extract_tokens(path)
        m = mappings.get(fn, {})
        # 没有保存过映射的占位符给自动建议
        suggested = {t: m.get(t) or docgen.guess_field(t) for t in tokens}
        items.append({"filename": fn, "tokens": suggested})
    return items


@app.route("/")
def index():
    return send_from_directory(os.path.join(BASE, "web"), "index.html")


@app.route("/api/fields")
def api_fields():
    return jsonify({"fields": docgen.FIELD_DEFS})


@app.route("/api/templates")
def api_templates():
    return jsonify({"templates": template_list()})


@app.route("/api/templates/upload", methods=["POST"])
def api_template_upload():
    f = request.files.get("file")
    if not f or not f.filename.endswith(".docx"):
        return jsonify({"error": "请上传 .docx 模板文件"}), 400
    fn = re.sub(r"[\\/:*?\"<>|]", "_", f.filename)
    path = os.path.join(TPL_DIR, fn)
    f.save(path)
    tokens = docgen.extract_tokens(path)
    mappings = load_mappings()
    mappings[fn] = {t: docgen.guess_field(t) or "" for t in tokens}
    save_mappings(mappings)
    return jsonify({"ok": True, "filename": fn, "tokens": len(tokens)})


@app.route("/api/templates/delete", methods=["POST"])
def api_template_delete():
    fn = request.json.get("filename", "")
    if fn.startswith("示例-"):  # 示例模板不删，可覆盖
        return jsonify({"error": "示例模板不可删除"}), 400
    path = os.path.join(TPL_DIR, fn)
    if os.path.exists(path):
        os.remove(path)
    m = load_mappings()
    m.pop(fn, None)
    save_mappings(m)
    return jsonify({"ok": True})


@app.route("/api/templates/map", methods=["POST"])
def api_template_map():
    data = request.json or {}
    fn = data.get("filename", "")
    token_map = data.get("map", {})
    if not os.path.exists(os.path.join(TPL_DIR, fn)):
        return jsonify({"error": "模板不存在"}), 404
    m = load_mappings()
    m[fn] = {k: v for k, v in token_map.items() if v}
    save_mappings(m)
    return jsonify({"ok": True})


@app.route("/api/ocr", methods=["POST"])
def api_ocr():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "未收到文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "仅支持 png/jpg/jpeg/heic/pdf"}), 400
    tmp = tempfile.mktemp(suffix=ext)
    f.save(tmp)
    try:
        lines = ocr.ocr_file(tmp)
        if not lines:
            return jsonify({"error": "未识别到文字，请确认图片清晰度，或改用手动输入"}), 422
        ctype, fields = parsers.parse(lines)
        return jsonify({"type": ctype, "fields": fields, "lines": lines})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "识别失败：%s" % e}), 500
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.json or {}
    ctype = data.get("type")
    values = dict(data.get("fields") or {})
    chosen = data.get("templates") or []

    if ctype not in ("person", "company"):
        return jsonify({"error": "当事人类型未确定"}), 400
    if not values.get("client_name") or not values.get("client_id"):
        return jsonify({"error": "委托人姓名/名称与证件号码为必填项"}), 400
    if ctype == "person" and not parsers.valid_id_number(values.get("client_id", "")):
        return jsonify({"error": "身份证号校验位不符，请核对后重试"}), 400
    if ctype == "company" and not values.get("legal_rep"):
        return jsonify({"error": "法人客户需填写法定代表人姓名"}), 400
    if not values.get("case_reason"):
        return jsonify({"error": "案由为必填项"}), 400

    # 日期：一个日期输入拆成 年/月/日 三个字段
    d = values.get("sign_date") or date.today().isoformat()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(d))
    if m:
        values["sign_year"], values["sign_month"], values["sign_day"] = m.groups()

    ensure_demo_templates()
    mappings = load_mappings()
    available = {it["filename"] for it in template_list()}

    if not chosen:
        chosen = ["委托代理合同", "授权委托书", "法定代表人身份证明"]
    selected = []
    for fn in available:
        if any(k in fn for k in chosen):
            selected.append(fn)
    # 法人身份证明仅法人需要；自然人客户自动排除
    if ctype == "person":
        selected = [fn for fn in selected if "法定代表人" not in fn]

    if not selected:
        return jsonify({"error": "未找到可用模板，请先在模板管理页上传"}), 400

    folder = "%s-%s-%s" % (
        re.sub(r"[\\/:*?\"<>|]", "", values.get("client_name", "委托人")),
        re.sub(r"[\\/:*?\"<>|]", "", values.get("case_reason", "案件")),
        uuid.uuid4().hex[:6])
    out_path = os.path.join(OUT_DIR, folder)
    os.makedirs(out_path, exist_ok=True)

    results = []
    for fn in selected:
        tpl = os.path.join(TPL_DIR, fn)
        tokens = docgen.extract_tokens(tpl)
        saved = mappings.get(fn, {})
        token_map = {t: saved.get(t) or docgen.guess_field(t) for t in tokens}
        out_file = os.path.join(out_path, fn.replace("示例-", ""))
        try:
            docgen.fill_template(tpl, token_map, values, out_file)
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": "生成 %s 失败：%s" % (fn, e)}), 500
        # 报告未填充的占位符
        left = [t for t in docgen.extract_tokens(out_file)]
        results.append({"file": fn.replace("示例-", ""), "unfilled": left})

    return jsonify({"ok": True, "folder": folder, "results": results})


@app.route("/download/<path:sub>")
def download(sub):
    return send_from_directory(OUT_DIR, sub, as_attachment=True)


@app.route("/open-output", methods=["POST"])
def open_output():
    folder = (request.json or {}).get("folder", "")
    path = os.path.join(OUT_DIR, folder)
    if os.path.isdir(path):
        os.system('open "%s"' % path.replace('"', ""))
    return jsonify({"ok": True})


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ensure_demo_templates()
    print("委托文书生成器已启动：http://127.0.0.1:5092")
    app.run(host="127.0.0.1", port=5092, debug=False)
