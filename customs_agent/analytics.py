import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation


def _number(value) -> Decimal:
    if value is None:
        return Decimal(0)
    match = re.search(r"-?[\d,]+(?:\.\d+)?", str(value))
    if not match:
        return Decimal(0)
    try:
        return Decimal(match.group().replace(",", ""))
    except InvalidOperation:
        return Decimal(0)


def _money(value: str) -> tuple[Decimal, str]:
    numbers = re.findall(r"[\d,]+(?:\.\d+)?", value or "")
    total = _number(numbers[1] if len(numbers) > 1 else numbers[0] if numbers else "0")
    currency_match = re.search(r"(人民币|美元|欧元|英镑|日元|港币|澳元|加元|USD|CNY|EUR|GBP|JPY|HKD)", value or "", re.I)
    return total, currency_match.group(1).upper() if currency_match else "币种未识别"


def _name(fields: dict) -> str:
    return fields.get("境内发货人") or fields.get("境内收发货人") or fields.get("生产销售单位") or "未识别企业"


def build_analytics(documents: list[dict]) -> dict:
    company_stats = defaultdict(lambda: {"documents": 0, "items": 0, "gross_weight": Decimal(0), "net_weight": Decimal(0), "amounts": defaultdict(Decimal)})
    customs_stats = defaultdict(int)
    destination_stats = defaultdict(lambda: {"documents": 0, "items": 0})
    transport_stats = defaultdict(int)
    product_stats = defaultdict(lambda: {"name": set(), "items": 0, "quantity_text": [], "amounts": defaultdict(Decimal), "companies": set()})
    currency_totals = defaultdict(Decimal)
    total_items = 0
    total_gross = Decimal(0)
    total_net = Decimal(0)
    total_packages = Decimal(0)
    dates = []
    complete = defaultdict(int)
    important_fields = ["境内发货人", "海关编号", "出境关别", "出口日期", "运输方式", "运抵国（地区）", "毛重（千克）", "净重（千克）"]

    for document in documents:
        fields = document["fields"]
        company = _name(fields)
        company_stats[company]["documents"] += 1
        gross = _number(fields.get("毛重（千克）") or fields.get("毛重"))
        net = _number(fields.get("净重（千克）") or fields.get("净重"))
        packages = _number(fields.get("件数"))
        total_gross += gross
        total_net += net
        total_packages += packages
        company_stats[company]["gross_weight"] += gross
        company_stats[company]["net_weight"] += net
        customs_stats[fields.get("出境关别", "未识别")] += 1
        destination = fields.get("运抵国（地区）") or fields.get("最终目的国（地区）") or "未识别"
        destination_stats[destination]["documents"] += 1
        transport_stats[fields.get("运输方式", "未识别")] += 1
        date = fields.get("出口日期") or fields.get("进口日期") or fields.get("申报日期")
        if date and re.fullmatch(r"\d{8}", str(date)):
            dates.append(str(date))
        for field in important_fields:
            if fields.get(field):
                complete[field] += 1

        item_numbers = sorted(
            (int(match.group(1)), key) for key in fields
            if (match := re.fullmatch(r"商品(\d+)-项号", key))
        )
        for item_index, _ in item_numbers:
            prefix = f"商品{item_index}-"
            hs = fields.get(prefix + "商品编号", "未识别")
            name = fields.get(prefix + "商品名称", "未识别")
            quantity = fields.get(prefix + "数量及单位", "未识别")
            amount, currency = _money(fields.get(prefix + "单价/总价/币制", ""))
            total_items += 1
            company_stats[company]["items"] += 1
            company_stats[company]["amounts"][currency] += amount
            destination_stats[destination]["items"] += 1
            product_stats[hs]["name"].add(name)
            product_stats[hs]["items"] += 1
            product_stats[hs]["companies"].add(company)
            if quantity != "未识别": product_stats[hs]["quantity_text"].append(quantity)
            product_stats[hs]["amounts"][currency] += amount
            currency_totals[currency] += amount

    def amount_text(amounts):
        return "；".join(f"{currency} {value:,.2f}" for currency, value in sorted(amounts.items())) or "未识别"

    count = len(documents)
    return {
        "overview": {
            "documents": count,
            "companies": len(company_stats),
            "items": total_items,
            "gross_weight_kg": float(total_gross),
            "net_weight_kg": float(total_net),
            "package_count": float(total_packages),
            "weight_difference_kg": float(total_gross - total_net),
            "date_from": min(dates) if dates else None,
            "date_to": max(dates) if dates else None,
        },
        "currency_totals": [{"currency": k, "amount": float(v)} for k, v in sorted(currency_totals.items())],
        "companies": [{
            "company": k, "documents": v["documents"], "items": v["items"],
            "gross_weight_kg": float(v["gross_weight"]), "net_weight_kg": float(v["net_weight"]),
            "amount": amount_text(v["amounts"]),
        } for k, v in sorted(company_stats.items(), key=lambda x: (-x[1]["documents"], x[0]))],
        "customs_offices": [{"name": k, "documents": v} for k, v in sorted(customs_stats.items(), key=lambda x: -x[1])],
        "destinations": [{"name": k, **v} for k, v in sorted(destination_stats.items(), key=lambda x: -x[1]["documents"])],
        "transports": [{"name": k, "documents": v} for k, v in sorted(transport_stats.items(), key=lambda x: -x[1])],
        "products": [{
            "hs_code": k, "names": "；".join(sorted(v["name"])), "items": v["items"],
            "companies": len(v["companies"]), "amount": amount_text(v["amounts"]),
            "quantity_samples": "；".join(v["quantity_text"][:3]),
        } for k, v in sorted(product_stats.items(), key=lambda x: (-x[1]["items"], x[0]))],
        "data_quality": [{
            "field": field, "recognized": complete[field], "total": count,
            "rate": round(complete[field] / count * 100, 1) if count else 0,
        } for field in important_fields],
    }

