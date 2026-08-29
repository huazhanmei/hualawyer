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

    m = re.search(r"法定代表人[：:]?([\u4e00-\u9fa5·]{2,10})", joined)
    if m:
        fields["legal_rep"] = m.group(1)

    m = re.search(r"职务[：:]?([\u4e00-\u9fa5]{2,10})", joined)
    if m:
        fields["legal_rep_duty"] = m.group(1)

    m = re.search(
        r"(?:注册地址|住所|企业住所|经营场所|注册地|主要经营场所)[：:]?(.*?)(?=%s|$)" % _NEXT_LABELS,
        joined, re.S)
    if m and m.group(1):
        addr = re.sub(r"[\s　\n]+", "", m.group(1))
        if 4 <= len(addr) <= 60:
            fields["client_address"] = addr

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
