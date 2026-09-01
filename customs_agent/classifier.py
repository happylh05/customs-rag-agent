import re


FIELD_PATTERNS = {
    "预录入编号": [r"预录入编号\s*[：:]\s*([A-Z0-9-]{8,})"],
    "海关编号": [r"海关编号\s*[：:]\s*([A-Z0-9-]{8,})"],
    "境内发货人": [r"境内发货人\s*[：:]\s*([^\n|]{2,60})"],
    "境内收发货人": [r"(?:境内)?收发货人\s*[：:]\s*([^\n|]{2,60})"],
    "出境关别": [r"出境关别\s*[：:]\s*([^\n|]{2,40})"],
    "运输工具名称及航次号": [r"运输工具名称及航次号\s*[：:]\s*([^\n|]{2,60})"],
    "商品编号": [r"商品编号\s*[：:]\s*(\d{8,13})"],
    "申报单位": [r"申报单位\s*[：:]\s*([^\n|]{2,60})"],
    "运输方式": [r"运输方式\s*[：:]\s*([^\n|]{1,30})"],
    "贸易方式": [r"(?:监管方式|贸易方式)\s*[：:]\s*([^\n|]{1,30})"],
    "征免性质": [r"征免性质\s*[：:]\s*([^\n|]{1,30})"],
    "成交方式": [r"成交方式\s*[：:]\s*([^\n|]{1,30})"],
    "合同协议号": [r"合同协议号\s*[：:]\s*([^\s|]{2,40})"],
    "提运单号": [r"提运单号\s*[：:]\s*([^\s|]{2,40})"],
    "启运国（地区）": [r"启运国(?:（地区）|\(地区\))?\s*[：:]\s*([^\n|]{1,30})"],
    "运抵国（地区）": [r"运抵国(?:（地区）|\(地区\))?\s*[：:]\s*([^\n|]{1,30})"],
    "件数": [r"件数\s*[：:]\s*(\d+)"],
    "毛重": [r"毛重(?:\(千克\)|（千克）)?\s*[：:]\s*([\d,.]+)"],
    "净重": [r"净重(?:\(千克\)|（千克）)?\s*[：:]\s*([\d,.]+)"],
}


def classify(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    normalized = re.sub(r"[ \t]+", " ", text)
    if "[结构化字段]" in text:
        for structured in text.split("[结构化字段]")[1:]:
            structured = structured.split("[第 ", 1)[0]
            for line in structured.splitlines():
                match = re.match(r"^([^：:\n]{1,50})\s*[：:]\s*(.+)$", line.strip())
                if match:
                    fields[match.group(1).strip()] = match.group(2).strip()
    for name, patterns in FIELD_PATTERNS.items():
        if name in fields:
            continue
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                fields[name] = match.group(1).strip(" ：:")
                break
    direction = "进口" if "进口" in text else "出口" if "出口" in text else "未识别"
    fields["申报类型"] = direction
    return fields
