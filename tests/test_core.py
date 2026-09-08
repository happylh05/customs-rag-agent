from customs_agent.answering import NO_EVIDENCE, answer
from customs_agent.analytics import build_analytics
from customs_agent.classifier import classify
from customs_agent.extractors import chunks
from customs_agent.store import Store


def test_classify_common_fields():
    fields = classify("进口报关单\n海关编号: 123456789012345678\n境内收发货人：上海示例贸易有限公司\n毛重（千克）: 100.5")
    assert fields["海关编号"] == "123456789012345678"
    assert fields["申报类型"] == "进口"
    assert fields["毛重"] == "100.5"


def test_classify_requested_customs_fields():
    fields = classify("""[结构化字段]
境内发货人: 鹤山国机南联摩托车工业有限公司
出境关别: 南沙新港
运输工具名称及航次号: 赋力898/000260424003
商品编号: 8711202000""")
    assert fields["境内发货人"] == "鹤山国机南联摩托车工业有限公司"
    assert fields["出境关别"] == "南沙新港"
    assert fields["运输工具名称及航次号"] == "赋力898/000260424003"
    assert fields["商品编号"] == "8711202000"


def test_store_and_no_hallucination(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = Store(tmp_path / "test.db")
    store.add("a.txt", "a.txt", "hash", 1, {}, chunks("海关编号 9988 境内收货人 上海甲公司"))
    assert store.search("9988")
    assert answer("完全不存在的数据", [])[0] == NO_EVIDENCE


def test_structured_field_lookup(tmp_path):
    store = Store(tmp_path / "fields.db")
    fields = {
        "境内发货人": "鹤山国机南联摩托车工业有限公司",
        "出境关别": "南沙新港",
        "运输工具名称及航次号": "赋力898/000260424003",
        "商品编号": "8711202000",
        "成交方式": "FOB",
    }
    store.add("sample.pdf", "sample.pdf", "hash", 1, fields, ["sample"])
    for question, field in [
        ("境内发货人是谁", "境内发货人"), ("出境关别", "出境关别"),
        ("运输工具名称及航次号", "运输工具名称及航次号"), ("商品编号", "商品编号"),
        ("成交方式是什么", "成交方式"),
    ]:
        matched, rows = store.find_structured_field(question)
        assert matched == field
        assert rows[0]["value"] == fields[field]


def test_classifier_keeps_all_structured_fields():
    fields = classify("""正文\n[结构化字段]
贸易国（地区）: 肯尼亚
商品1-商品编号: 8711202000
商品1-规格型号: 125CC|SENKE牌|CG125
标记唛码及备注: 出口退税""")
    assert fields["贸易国（地区）"] == "肯尼亚"
    assert fields["商品1-商品编号"] == "8711202000"
    assert fields["商品1-规格型号"] == "125CC|SENKE牌|CG125"


def test_answer_without_key_never_calls_model(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result, mode = answer("问题", [{"filename": "a.pdf", "content": "证据", "chunk_index": 0}])
    assert mode == "retrieval-only"
    assert "证据" in result


def test_company_scoped_field_lookup(tmp_path):
    store = Store(tmp_path / "scoped.db")
    store.add("振锐.pdf", "a.pdf", "a", 1, {
        "境内发货人": "江门市振锐贸易有限公司", "出境关别": "大鹏海关"
    }, ["振锐资料"])
    store.add("富美.pdf", "b.pdf", "b", 1, {
        "境内发货人": "江门富美贸易有限公司", "出境关别": "南沙新港"
    }, ["富美资料"])
    field, rows = store.find_structured_field("振锐贸易有限公司出境关别是哪里")
    assert field == "出境关别"
    assert len(rows) == 1
    assert rows[0]["filename"] == "振锐.pdf"
    assert rows[0]["value"] == "大鹏海关"


def test_classifier_preserves_first_structured_block_in_multipage_pdf():
    text = """[第 1 页]\n报关单\n[结构化字段]
商品1-商品编号: 8509900000
商品2-商品编号: 8208300000
[第 2 页]\n放行通知书正文"""
    fields = classify(text)
    assert fields["商品1-商品编号"] == "8509900000"
    assert fields["商品2-商品编号"] == "8208300000"


def test_query_collects_all_commodity_rows(tmp_path):
    store = Store(tmp_path / "items.db")
    store.add("items.pdf", "items.pdf", "items", 1, {
        "商品编号": "8509900000",
        "商品1-商品编号": "8509900000",
        "商品2-商品编号": "8208300000",
    }, ["items"])
    field, rows = store.find_structured_field("商品编号有哪些")
    assert field == "商品编号"
    assert rows[0]["value"] == "8509900000；8208300000"


def test_analytics_separates_currencies_and_counts_items():
    documents = [{"fields": {
        "境内发货人": "甲公司", "海关编号": "1", "出境关别": "南沙新港",
        "出口日期": "20260101", "运输方式": "水路运输", "运抵国（地区）": "埃及",
        "成交方式": "FOB", "最终目的国（地区）": "肯尼亚",
        "毛重（千克）": "100", "净重（千克）": "90", "件数": "2",
        "商品1-项号": "1", "商品1-商品编号": "8509900000", "商品1-商品名称": "配件",
        "商品1-数量及单位": "10千克", "商品1-单价/总价/币制": "1.00 10.00 美元",
        "商品2-项号": "2", "商品2-商品编号": "8208300000", "商品2-商品名称": "刀具",
        "商品2-数量及单位": "2个", "商品2-单价/总价/币制": "5.00 10.00 人民币",
        "商品2-最终目的国（地区）": "坦桑尼亚",
    }}]
    result = build_analytics(documents)
    assert result["overview"]["items"] == 2
    assert result["overview"]["weight_difference_kg"] == 10
    assert {row["currency"] for row in result["currency_totals"]} == {"美元", "人民币"}
    assert result["deal_methods"] == [{"name": "FOB", "documents": 1}]
    assert result["final_destinations"] == [
        {"name": "肯尼亚", "documents": 1, "items": 1},
        {"name": "坦桑尼亚", "documents": 1, "items": 1},
    ]


def test_classifier_extracts_deal_method_and_final_destination():
    fields = classify("成交方式：FOB\n最终目的国（地区）：肯尼亚")
    assert fields["成交方式"] == "FOB"
    assert fields["最终目的国（地区）"] == "肯尼亚"


def test_search_prefers_structured_evidence_and_one_chunk_per_document(tmp_path):
    store = Store(tmp_path / "quality.db")
    store.add("a.pdf", "a.pdf", "a", 1, {}, [
        "目标编号 ABC123456 正常原文证据",
        "目标编号 ABC123456 SabeYGYj0Wue-Wfy ¦q6g(bX Å pu(IWWr¶,v}",
    ])
    store.add("b.pdf", "b.pdf", "b", 1, {}, ["目标编号 ABC123456 第二份正常证据"])
    rows = store.search("ABC123456", limit=4)
    assert len(rows) == 2
    assert len({row["document_id"] for row in rows}) == 2


def test_deal_method_value_returns_unique_companies(tmp_path):
    store = Store(tmp_path / "deal-method.db")
    store.add("a.pdf", "a.pdf", "a", 1, {
        "境内发货人": "甲公司", "成交方式": "FOB",
    }, ["成交方式 FOB"])
    store.add("b.pdf", "b.pdf", "b", 1, {
        "境内发货人": "甲公司", "成交方式": "FOB",
    }, ["成交方式 FOB"])
    store.add("c.pdf", "c.pdf", "c", 1, {
        "境内发货人": "乙公司", "成交方式": "C&F",
    }, ["成交方式 C&F"])

    method, companies = store.companies_by_deal_method("FOB")
    assert method == "FOB"
    assert len(companies) == 1
    assert companies[0]["company"] == "甲公司"
    assert companies[0]["documents"] == 2
    assert {source["filename"] for source in companies[0]["sources"]} == {"a.pdf", "b.pdf"}
    method, companies = store.companies_by_deal_method("C&F有哪些公司")
    assert method == "C&F"
    assert companies[0]["company"] == "乙公司"
