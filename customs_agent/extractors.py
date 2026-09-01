from pathlib import Path

from docx import Document
from pypdf import PdfReader
from pypdf.generic import ContentStream


class ExtractionError(ValueError):
    pass


def _decode_utf16(value: bytes) -> str:
    """Decode text drawn by the SimSun form XObjects used in China customs PDFs."""
    if not value or len(value) % 2:
        return ""
    try:
        text = value.decode("utf-16-be").strip()
    except UnicodeDecodeError:
        return ""
    printable = sum(ch.isprintable() for ch in text)
    return text if text and printable / len(text) > 0.85 else ""


def _form_xobject_text(reader: PdfReader, page, name) -> str:
    ref = (page.get("/Resources", {}).get("/XObject", {}) or {}).get(name)
    if not ref:
        return ""
    obj = ref.get_object()
    if obj.get("/Subtype") != "/Form":
        return ""
    try:
        stream = ContentStream(obj, reader)
    except Exception:
        return ""
    segments: list[str] = []
    for operands, operator in stream.operations:
        if operator not in (b"Tj", b"TJ"):
            continue
        values = operands if operator == b"Tj" else operands[0]
        if not isinstance(values, list):
            values = [values]
        raw = b"".join(value.original_bytes for value in values if hasattr(value, "original_bytes"))
        decoded = _decode_utf16(raw)
        if decoded:
            segments.append(decoded)
    return " ".join(segments)


def _customs_form_fields(reader: PdfReader, page) -> dict[str, str]:
    """Recover values from the flattened standard customs declaration layout.

    These PDFs draw each value in a Form XObject and frequently omit usable
    ToUnicode mappings. The form locations are stable even when XObject names vary.
    """
    positioned: list[tuple[float, float, str]] = []

    def before(operator, operands, cm, _tm):
        if operator != b"Do":
            return
        value = _form_xobject_text(reader, page, operands[0])
        if value:
            positioned.append((float(cm[4]), float(cm[5]), value))

    page.extract_text(visitor_operand_before=before)

    zones = {
        "海关编号": (65, 78, 270, 315),
        "境内发货人统一社会信用代码": (80, 94, 65, 100),
        "境内发货人": (94, 104, 20, 65),
        "出境关别代码": (80, 94, 270, 315),
        "出境关别": (94, 104, 235, 285),
        "出口日期": (94, 104, 500, 540),
        "境外收货人": (115, 128, 20, 75),
        "运输方式代码": (104, 116, 270, 315),
        "运输方式": (115, 128, 235, 285),
        "运输工具名称及航次号": (115, 128, 365, 410),
        "提运单号": (115, 128, 500, 540),
        "生产销售单位统一社会信用代码": (128, 138, 65, 105),
        "生产销售单位": (138, 151, 20, 75),
        "监管方式代码": (128, 138, 270, 315),
        "监管方式": (138, 151, 235, 285),
        "征免性质代码": (128, 138, 400, 440),
        "征免性质": (138, 151, 365, 410),
        "许可证号": (138, 151, 500, 540),
        "合同协议号": (160, 173, 20, 75),
        "贸易国代码": (150, 160, 295, 330),
        "贸易国（地区）": (160, 173, 235, 285),
        "运抵国代码": (150, 160, 425, 455),
        "运抵国（地区）": (160, 173, 365, 410),
        "指运港代码": (150, 160, 530, 565),
        "指运港": (160, 173, 500, 555),
        "离境口岸代码": (150, 160, 655, 690),
        "离境口岸": (160, 173, 615, 675),
        "包装种类代码": (175, 187, 65, 95),
        "包装种类": (187, 199, 20, 90),
        "件数": (187, 199, 235, 275),
        "毛重（千克）": (187, 199, 285, 330),
        "净重（千克）": (187, 199, 365, 410),
        "成交方式代码": (173, 185, 480, 515),
        "成交方式": (187, 199, 445, 490),
        "随附单证及编号": (205, 225, 20, 760),
        "标记唛码及备注": (225, 255, 20, 790),
        "申报单位": (515, 550, 20, 500),
        "自报自缴": (470, 500, 700, 760),
    }
    fields: dict[str, str] = {}
    for name, (x1, x2, y1, y2) in zones.items():
        matches = [value for x, y, value in positioned if x1 <= x <= x2 and y1 <= y <= y2]
        if matches:
            # Prefer the most informative value when a field contains both code and name.
            fields[name] = max(matches, key=len)

    # Commodity rows repeat vertically. A row begins with its item number at y≈36.
    item_starts = sorted(
        (x, value) for x, y, value in positioned
        if x >= 270 and 25 <= y <= 48 and value.isdigit()
    )
    commodity_columns = {
        "商品编号": (48, 82), "商品名称": (82, 165),
        "数量及单位": (315, 385), "单价/总价/币制": (405, 475),
        "原产国（地区）": (475, 535), "最终目的国（地区）": (545, 610),
        "境内货源地": (620, 700), "征免": (735, 790),
    }
    for index, (start_x, item_no) in enumerate(item_starts, 1):
        next_x = item_starts[index][0] if index < len(item_starts) else start_x + 35
        row = [(x, y, value) for x, y, value in positioned if start_x - 1 <= x < next_x - 1]
        fields[f"商品{index}-项号"] = item_no
        for column, (y1, y2) in commodity_columns.items():
            values = [
                (x, value) for x, y, value in row
                if y1 <= y <= y2 and (column != "商品名称" or x < start_x + 8)
            ]
            if values:
                if column in {"原产国（地区）", "最终目的国（地区）"}:
                    ordered = list(dict.fromkeys(value for _, value in sorted(values)))
                    fields[f"商品{index}-{column}"] = " ".join(ordered)
                else:
                    fields[f"商品{index}-{column}"] = max((value for _, value in values), key=len)
        # The specification/model line is below the commodity-name line.
        specs = [value for x, y, value in positioned if start_x + 8 <= x < next_x - 1 and 82 <= y <= 165]
        if specs:
            fields[f"商品{index}-规格型号"] = max(specs, key=len)

    # Preserve convenient singular aliases for questions when only/first commodity is requested.
    for alias in commodity_columns:
        first = fields.get(f"商品1-{alias}")
        if first:
            fields[alias] = first
    return fields


def extract_text(path: Path) -> tuple[str, int]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            page_text = (page.extract_text() or "").strip()
            is_declaration = (
                "海关出口货物报关单" in page_text or "海关进口货物报关单" in page_text
            )
            form_fields = _customs_form_fields(reader, page) if is_declaration else {}
            if form_fields:
                structured = "\n".join(f"{name}: {value}" for name, value in form_fields.items())
                page_text = f"{page_text}\n\n[结构化字段]\n{structured}"
            pages.append(page_text)
        text = "\n\n".join(f"[第 {i + 1} 页]\n{value}" for i, value in enumerate(pages) if value)
        if not text.strip():
            raise ExtractionError("PDF 未包含可提取文字，可能是扫描件；请先进行 OCR 后再上传。")
        return text, len(reader.pages)
    if suffix == ".docx":
        doc = Document(str(path))
        parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        text = "\n".join(parts)
        if not text.strip():
            raise ExtractionError("Word 文件未包含可提取文字。")
        return text, 1
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            raise ExtractionError("文件内容为空。")
        return text, 1
    raise ExtractionError("仅支持 PDF、DOCX、TXT 和 Markdown 文件。")


def chunks(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    result: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n{paragraph}".strip()
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            result.append(current)
        current = (current[-overlap:] + "\n" + paragraph).strip() if current else paragraph
        while len(current) > size:
            result.append(current[:size])
            current = current[size - overlap :]
    if current:
        result.append(current)
    return result
