# -*- coding: utf-8 -*-
"""docx 模板填充模块：将【占位符】替换为字段值，尽量保留模板原格式。

遍历范围：正文段落、表格单元格、页眉、页脚。
占位符写法：【任意文字】（全角方括号），由"模板管理"页建立 占位符 → 数据字段 的映射。
"""
import re

from docx import Document
from docx.oxml.ns import qn

TOKEN_RE = re.compile(r"【[^】]{1,30}】")

# 证件号码组合标签：如"公民身份号码/统一社会信用代码"、"身份证号/统一社会信用代码"
# 生成时按当事人类型替换为单一标签（自然人→身份证号码；法人→统一社会信用代码）
_LABEL_COMBO_RE = re.compile(r"(?:公民身份号码|身份证号码|身份证号|身份号码)\s*/\s*统一社会信用代码")
# 组合标签 + 冒号且后面没有占位符（模板漏写【身份证号】的情形）→ 标签后直接补证件号
_LABEL_COMBO_TAIL_RE = re.compile(
    r"((?:公民身份号码|身份证号码|身份证号|身份号码)\s*/\s*统一社会信用代码)(\s*[:：][\s\u3000]*)$")


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
        label = values.get("client_id_label")
        id_no = values.get("client_id")
        if label:
            # 情形一：组合标签+冒号位于段尾且无占位符 → 直接补上证件号
            if id_no:
                m = _LABEL_COMBO_TAIL_RE.search(text)
                if m:
                    text = text[:m.start()] + label + m.group(2) + str(id_no)
            # 情形二：普通组合标签 → 替换为单一标签（占位符保留，走下方正常填充）
            text = _LABEL_COMBO_RE.sub(label, text)
            # 情形三：显式【证件号码类型】占位符
            text = text.replace("【证件号码类型】", str(label))

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
        has_token = "【" in full and "】" in full
        has_label = _LABEL_COMBO_RE.search(full) is not None
        if not has_token and not has_label:
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
    {"key": "client_phone", "label": "委托人联系电话", "group": "both", "required": True},
    {"key": "opponent_name", "label": "被告姓名（对方当事人）", "group": "both", "required": True},
    {"key": "case_reason", "label": "案由", "group": "both", "required": True},
    {"key": "agency_stage", "label": "代理阶段", "group": "both", "required": True},
    {"key": "auth_scope", "label": "代理权限", "group": "both", "required": True},
    {"key": "legal_rep", "label": "法定代表人姓名", "group": "company", "required": True},
    {"key": "legal_rep_duty", "label": "法定代表人职务", "group": "company", "required": True},
    {"key": "contract_no", "label": "合同编号", "group": "both", "required": False},
    {"key": "sign_date", "label": "签订日期", "group": "both", "required": False},
    {"key": "sign_year", "label": "日期·年", "group": "both", "required": False},
    {"key": "sign_month", "label": "日期·月", "group": "both", "required": False},
    {"key": "sign_day", "label": "日期·日", "group": "both", "required": False},
]

# 关键词 → 字段key 的自动映射规则（上传模板时预填建议）
# 注意顺序：【被告姓名】须先于【...姓名】；【法定代表人职务】须先于【法定代表人】；
# 【法定代表人姓名】须先于【...姓名】，否则会误映射
_AUTO_RULES = [
    (("被告", "对方当事人", "对方"), "opponent_name"),
    (("职务",), "legal_rep_duty"),
    (("法定代表人", "法定代表"), "legal_rep"),
    (("姓名", "委托人名", "甲方名", "委托人名称"), "client_name"),
    (("性别",), "client_gender"),
    (("民族",), "client_ethnicity"),
    (("出生",), "client_birth"),
    (("住址", "住所", "地址", "营业场所"), "client_address"),
    (("身份证", "身份号码", "证号", "信用代码", "信用证号"), "client_id"),
    (("电话", "联系方式", "手机"), "client_phone"),
    (("案由", "纠纷", "案件"), "case_reason"),
    (("代理阶段", "审理阶段", "诉讼阶段"), "agency_stage"),
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
    if "证件号码类型" in inner:
        return None  # 由 fill_template 按当事人类型动态填充，无需映射
    for keywords, key in _AUTO_RULES:
        for kw in keywords:
            if kw in inner:
                return key
    return None


def _set_eastasia(run, font):
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = rPr.makeelement(qn("w:rFonts"), {})
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), font)


def fix_eastasia_fonts(path, body_font="仿宋", title_font="宋体"):
    """修复 textutil 转换 .doc→.docx 后中文字体标记丢失的问题。

    首个非空段落视为标题（宋体加粗），其余正文统一设中文字体（默认仿宋）。
    西文字体与字号保留转换结果。
    """
    doc = Document(path)
    title_done = False
    for p in _iter_paragraphs(doc):
        text = "".join(r.text for r in p.runs)
        if not text.strip():
            continue
        if not title_done:
            for r in p.runs:
                _set_eastasia(r, title_font)
                if r.font.bold is None:
                    r.font.bold = True
            title_done = True
        else:
            for r in p.runs:
                _set_eastasia(r, body_font)
    doc.save(path)
