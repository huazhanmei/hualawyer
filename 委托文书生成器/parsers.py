# -*- coding: utf-8 -*-
"""证件解析模块：从 OCR 文本行中结构化提取当事人信息。

- 自然人：身份证号（含校验位验证）、姓名、性别、民族、出生日期、住址
- 法人：企业名称、统一社会信用代码、法定代表人、住所
"""
import re

ID_RE = re.compile(r"[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]")
USCC_RE = re.compile(r"[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}")

WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
CHECK_CODES = "10X98765432"

# 企查查截图中"注册地址"之后常见的下一个字段标签（用于截断地址串）
_NEXT_LABELS = (
    "统一社会信用代码|纳税人识别号|经营范围|曾用名|组织机构代码|"
    "参保人数|电话|邮箱|官网|所属行业|企业类型|成立日期|注册资本|"
    "登记机关|核准日期|登记状态|人员规模|英文名|股东信息|主要人员"
)
# 已知字段标签词：从姓名/职务候选值中剔除，防止 OCR 多列挤同行时误吞
_LABEL_WORDS = (
    "统一社会信用代码", "纳税人识别号", "经营范围", "曾用名", "组织机构代码",
    "参保人数", "电话", "邮箱", "官网", "所属行业", "企业类型", "成立日期",
    "注册资本", "登记机关", "核准日期", "登记状态", "人员规模", "英文名",
    "股东信息", "主要人员", "注册地址", "法定代表人", "职务", "不详", "暂无",
)
# 兜底：地址标签缺失时（企查查移动端 App 截图，地址直接跟在地图图标后），
# 按中国地址格式在 OCR 文本中查找。规则：含"市"且含"路/街/道/巷"且含"号"。
_ADDR_FALLBACK_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,8}市[\u4e00-\u9fa5A-Za-z0-9·]{1,30}(?:路|街|道|巷)[\u4e00-\u9fa5A-Za-z0-9]{1,20}号[\u4e00-\u9fa5A-Za-z0-9号座栋单元层室楼-]*"
)
# 兜底：职务标签缺失时（人员区"姓名+职务"同行布局），按常见职务词匹配
# 注意：Python re 的 alternation 按列表顺序优先匹配，所以长的词必须排在前面，
# 否则短词（如"董事"）会先吃掉匹配位，导致"执行董事兼总经理"被截成"董事"。
_DUTY_FALLBACK_RE = re.compile(
    r"执行董事兼总经理|董事长兼总经理|执行董事|副董事长|"
    r"董事长|总经理|副总经理|董事|经理|副经理|监事长|监事|"
    r"财务负责人|法定代表人"
)
# 排除区块：这些行/上下文里的地址/职务不应作为企业基本信息采纳
_BLOCK_WORDS = ("风险", "股东", "人员", "动态", "历史信息", "自身", "关联", "扫", "描", "提示", "发票")


def _trim_label_words(s):
    """把候选值里混入的后续标签词截掉；若整个值都是标签词则返回 None。"""
    if not s:
        return None
    for w in _LABEL_WORDS:
        idx = s.find(w)
        if idx == 0:
            return None
        if idx > 0:
            s = s[:idx]
    s = s.strip("：:，,、")
    return s if len(s) >= 2 else None
COMPANY_SUFFIX = (
    "公司|企业|集团|厂|中心|合作社|事务所|银行|商店|商场|"
    "研究院|研究所|医院|学校|大学|俱乐部|工作室|合伙"
)
COMPANY_RE = re.compile(r"[\u4e00-\u9fa5（）()A-Za-z0-9]{2,40}(?:%s)" % COMPANY_SUFFIX)


def valid_id_number(num):
    """验证 18 位身份证号校验位。"""
    num = (num or "").strip().upper()
    if not re.fullmatch(r"\d{17}[\dX]", num):
        return False
    total = sum(int(num[i]) * WEIGHTS[i] for i in range(17))
    return CHECK_CODES[total % 11] == num[17]


def _joined(lines):
    """把多行 OCR 结果用换行符拼接，保留行边界作为字段截断依据。"""
    return "\n".join(re.sub(r"[\s　]+", "", ln) for ln in lines)


def detect_type(lines):
    """判断证件类型：person（身份证）/ company（企业截图）。"""
    joined = _joined(lines)
    if ID_RE.search(joined):
        return "person"
    if USCC_RE.search(joined):
        return "company"
    if "居民身份证" in joined or "公民身份号码" in joined:
        return "person"
    if "法定代表人" in joined or "统一社会信用代码" in joined or "注册资本" in joined:
        return "company"
    return "unknown"


def parse_person(lines):
    joined = _joined(lines)
    fields = {}

    m = ID_RE.search(joined)
    if m:
        num = m.group(0).upper()
        fields["client_id"] = num
        fields["id_valid"] = valid_id_number(num)
        # 从证号推导出生日期与性别（OCR 标签常缺失，推导更可靠）
        y, mo, d = num[6:10], num[10:12], num[12:14]
        fields["client_birth"] = "%d年%d月%d日" % (int(y), int(mo), int(d))
        fields["client_gender"] = "男" if int(num[16]) % 2 == 1 else "女"
    else:
        fields["id_valid"] = False

    m = re.search(r"姓名[：:]?([\u4e00-\u9fa5·]{2,15})", joined)
    if m:
        fields["client_name"] = m.group(1)

    m = re.search(r"民族[：:]?([\u4e00-\u9fa5]{1,4})", joined)
    if m:
        fields["client_ethnicity"] = m.group(1)

    m = re.search(r"性别[：:]?([男女])", joined)
    if m:
        fields["client_gender"] = m.group(1)

    # 住址：从"住址"标签起，跨行到"公民身份号码"、身份证号或串尾
    m = re.search(
        r"住址[：:]?(.*?)(?=公民身份号码|[1-9]\d{16}[\dXx]|$)", joined, re.S)
    if m and m.group(1):
        addr = re.sub(r"[\s　\n]+", "", m.group(1))
        if 4 <= len(addr) <= 60:
            fields["client_address"] = addr

    return fields


def parse_company(lines):
    joined = _joined(lines)
    fields = {}

    m = USCC_RE.search(joined)
    if m:
        fields["client_id"] = m.group(0)

    m = re.search(r"企业名称[：:]?([\u4e00-\u9fa5（）()A-Za-z0-9]{2,40})", joined)
    if m:
        fields["client_name"] = m.group(1)
    else:
        # 企查查截图：公司名通常是含"公司/集团"等后缀的第一串文本
        for ln in lines:
            ln_clean = re.sub(r"[\s　]+", "", ln)
            m2 = COMPANY_RE.search(ln_clean)
            if m2:
                fields["client_name"] = m2.group(0)
                break

    # 法定代表人：兼容三种 OCR 布局——
    # ① 同行（"法定代表人 王海川"）② 带冒号（"法定代表人：王海川"）
    # ③ 分行（标签一列、姓名一列，企查查 App 截图常见："法定代表人\n王海川"）
    # 同行用懒惰匹配+标签前瞻，防止多列挤同行时把后续标签吞进姓名
    _look = "(?=%s|职务|法定代表人|\\n|$)" % _NEXT_LABELS
    m = re.search(r"法定代表人[：:]?([\u4e00-\u9fa5·]{2,10}?)" + _look, joined)
    if m:
        name = _trim_label_words(m.group(1))
        if name:
            fields["legal_rep"] = name
    if "legal_rep" not in fields:
        m = re.search(r"法定代表人[：:]?[ \t]*\n[ \t]*([\u4e00-\u9fa5·]{2,10})\n", joined)
        if m:
            name = _trim_label_words(m.group(1))
            if name:
                fields["legal_rep"] = name

    # 职务：兼容标签同行/分行/缺失三种 OCR 布局
    m = re.search(r"职务[：:]?([\u4e00-\u9fa5]{2,10})", joined)
    if m:
        duty = _trim_label_words(m.group(1))
        if duty:
            fields["legal_rep_duty"] = duty
    if "legal_rep_duty" not in fields:
        m = re.search(r"职务[：:]?[ \t]*\n[ \t]*([\u4e00-\u9fa5]{2,10})\n", joined)
        if m:
            duty = _trim_label_words(m.group(1))
            if duty:
                fields["legal_rep_duty"] = duty
    # 兜底：人员区"姓名+职务"同行布局（如"谢云峰 执行董事兼总经理"）
    if "legal_rep_duty" not in fields and fields.get("legal_rep"):
        rep = re.escape(fields["legal_rep"])
        for ln in lines:
            if rep in ln:
                if any(b in ln for b in _BLOCK_WORDS):
                    continue
                tail = ln.split(rep, 1)[-1]  # 姓名之后的内容
                m2 = _DUTY_FALLBACK_RE.search(tail)
                if m2:
                    fields["legal_rep_duty"] = m2.group(0)
                    break

    m = re.search(
        r"(?:注册地址|住所|企业住所|经营场所|注册地|主要经营场所)[：:]?(.*?)(?=%s|$)" % _NEXT_LABELS,
        joined, re.S)
    if m and m.group(1):
        addr = re.sub(r"[\s　\n]+", "", m.group(1))
        if 4 <= len(addr) <= 60:
            fields["client_address"] = addr
    # 兜底：企查查移动端 App 截图，地址标签缺失，地址直接跟在地图图标后
    if "client_address" not in fields:
        for ln in lines:
            ln_clean = re.sub(r"[\s　]+", "", ln)
            if any(b in ln for b in _BLOCK_WORDS):
                continue
            m2 = _ADDR_FALLBACK_RE.search(ln_clean)
            if m2:
                cand = m2.group(0)
                # 去掉行首的杂字符（如 ◎、● 等图标）
                cand = re.sub(r"^[^一-龥A-Za-z]+", "", cand)
                if 6 <= len(cand) <= 60:
                    fields["client_address"] = cand
                    break

    return fields


def parse(lines, ctype=None):
    """总入口：返回 (type, fields)。"""
    if ctype is None:
        ctype = detect_type(lines)
    if ctype == "person":
        return ctype, parse_person(lines)
    if ctype == "company":
        return ctype, parse_company(lines)
    return ctype, {}
