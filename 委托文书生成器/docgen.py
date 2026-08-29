# -*- coding: utf-8 -*-
"""docx 模板填充模块：将【占位符】替换为字段值，尽量保留模板原格式。

遍历范围：正文段落、表格单元格、页眉、页脚。
占位符写法：【任意文字】（全角方括号），由"模板管理"页建立 占位符 → 数据字段 的映射。
"""
import re
from docx import Document

TOKEN_RE = re.compile(r"【[^】]{1,30}】")


def _iter_paragraphs(doc):
    for p in doc.paragraphs:
        yield p
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p
    for section in doc.sections:
        for container in (section.header, section.footer):
            for p in container.paragraphs:
                yield p
            for table in container.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            yield p


def extract_tokens(path):
    """提取模板中出现的全部【占位符】。"""
    doc = Document(path)
    tokens = set()
    for p in _iter_paragraphs(doc):
        full = "".join(r.text for r in p.runs)
        tokens.update(TOKEN_RE.findall(full))
    return sorted(tokens)


def fill_template(template_path, token_map, values, out_path):
    """token_map: {占位符: 字段key}；values: {字段key: 字符串值}。

    替换策略：段落级重写 —— 合并该段全部 run 的文本后整体替换，
    结果写回首 run 以保留其字体格式（占位符所在段落通常整段同格式）。
    """
    doc = Document(template_path)

    def substitute(text):
        def repl(m):
            key = token_map.get(m.group(0))
            if not key:
                return m.group(0)  # 未映射的占位符原样保留
            val = values.get(key)
            if val is None or val == "":
                return m.group(0)  # 字段为空也保留占位符，便于人工补填
            return str(val)
        return TOKEN_RE.sub(repl, text)

    replaced = 0
    for p in _iter_paragraphs(doc):
        full = "".join(r.text for r in p.runs)
        if "【" not in full or "】" not in full:
            continue
        new_text = substitute(full)
        if new_text == full:
            continue
        runs = p.runs
        if not runs:
            continue
        for r in runs[1:]:
            r._element.getparent().remove(r._element)
        runs[0].text = new_text
        replaced += 1

    doc.save(out_path)
    return replaced


# ---------------- 字段定义（网页表单与模板映射共用） ----------------

FIELD_DEFS = [
    {"key": "client_name", "label": "委托人姓名/名称", "group": "both", "required": True},
    {"key": "client_gender", "label": "性别", "group": "person", "required": False},
    {"key": "client_ethnicity", "label": "民族", "group": "person", "required": False},
    {"key": "client_birth", "label": "出生日期", "group": "person", "required": False},
    {"key": "client_address", "label": "住址/住所", "group": "both", "required": True},
    {"key": "client_id", "label": "身份证号/统一社会信用代码", "group": "both", "required": True},
    {"key": "client_phone", "label": "联系电话", "group": "both", "required": False},
    {"key": "legal_rep", "label": "法定代表人姓名", "group": "company", "required": True},
    {"key": "legal_rep_duty", "label": "法定代表人职务", "group": "company", "required": False},
    {"key": "case_reason", "label": "案由", "group": "both", "required": True},
    {"key": "auth_scope", "label": "代理权限", "group": "both", "required": True},
    {"key": "contract_no", "label": "合同编号", "group": "both", "required": False},
    {"key": "sign_date", "label": "签订日期", "group": "both", "required": False},
    {"key": "sign_year", "label": "日期·年", "group": "both", "required": False},
    {"key": "sign_month", "label": "日期·月", "group": "both", "required": False},
    {"key": "sign_day", "label": "日期·日", "group": "both", "required": False},
]

# 关键词 → 字段key 的自动映射规则（上传模板时预填建议）
_AUTO_RULES = [
    (("姓名", "委托人名", "甲方名"), "client_name"),
    (("性别",), "client_gender"),
    (("民族",), "client_ethnicity"),
    (("出生",), "client_birth"),
    (("住址", "住所", "地址", "营业场所"), "client_address"),
    (("身份证", "身份号码", "证号", "信用代码", "信用证号"), "client_id"),
    (("电话", "联系方式", "手机"), "client_phone"),
    (("法定代表人", "法定代表"), "legal_rep"),
    (("职务",), "legal_rep_duty"),
    (("案由", "纠纷", "案件"), "case_reason"),
    (("权限", "授权"), "auth_scope"),
    (("编号", "合同号"), "contract_no"),
    (("签订日期", "签署日期", "日期"), "sign_date"),
]


def guess_field(token):
    """根据占位符文字猜测对应字段 key，猜不出返回 None。"""
    inner = token.strip("【】")
    if inner == "年":
        return "sign_year"
    if inner == "月":
        return "sign_month"
    if inner == "日":
        return "sign_day"
    for keywords, key in _AUTO_RULES:
        for kw in keywords:
            if kw in inner:
                return key
    return None
