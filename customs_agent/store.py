import json
import re
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def init(self):
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY, filename TEXT NOT NULL, stored_name TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE, page_count INTEGER NOT NULL,
                    fields_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                    content, document_id UNINDEXED, chunk_index UNINDEXED,
                    tokenize='unicode61'
                );
            """)

    def add(self, filename: str, stored_name: str, sha256: str, page_count: int,
            fields: dict, chunk_values: list[str]) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO documents(filename, stored_name, sha256, page_count, fields_json) VALUES(?,?,?,?,?)",
                (filename, stored_name, sha256, page_count, json.dumps(fields, ensure_ascii=False)),
            )
            doc_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO chunks(content, document_id, chunk_index) VALUES(?,?,?)",
                [(value, doc_id, i) for i, value in enumerate(chunk_values)],
            )
            return int(doc_id)

    def by_hash(self, sha256: str):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM documents WHERE sha256=?", (sha256,)).fetchone()

    def reindex(self, document_id: int, page_count: int, fields: dict, chunk_values: list[str]):
        with self.connect() as conn:
            conn.execute(
                "UPDATE documents SET page_count=?, fields_json=? WHERE id=?",
                (page_count, json.dumps(fields, ensure_ascii=False), document_id),
            )
            conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
            conn.executemany(
                "INSERT INTO chunks(content, document_id, chunk_index) VALUES(?,?,?)",
                [(value, document_id, i) for i, value in enumerate(chunk_values)],
            )

    def list_documents(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()
        return [{**dict(row), "fields": json.loads(row["fields_json"])} for row in rows]

    def find_structured_field(self, question: str):
        aliases = {
            "境内发货人": ("境内发货人", "发货人"),
            "境内收发货人": ("境内收发货人", "收发货人"),
            "出境关别": ("出境关别", "出口关别"),
            "运输工具名称及航次号": ("运输工具名称及航次号", "运输工具及航次号", "航次号"),
            "商品编号": ("商品编号", "海关商品编号", "税则号", "HS编码", "HS CODE"),
            "商品名称": ("商品名称", "品名"),
            "规格型号": ("规格型号", "商品规格"),
            "数量及单位": ("数量及单位", "数量", "单位"),
            "单价/总价/币制": ("单价", "总价", "币制", "金额"),
            "原产国（地区）": ("原产国",),
            "最终目的国（地区）": ("最终目的国",),
            "境内货源地": ("境内货源地",),
            "征免": ("商品征免", "征免方式"),
            "海关编号": ("海关编号",),
            "预录入编号": ("预录入编号",),
            "申报单位": ("申报单位",),
            "运输方式": ("运输方式",),
            "贸易方式": ("贸易方式", "监管方式"),
            "生产销售单位": ("生产销售单位",),
            "许可证号": ("许可证号",),
            "贸易国（地区）": ("贸易国",),
            "运抵国（地区）": ("运抵国",),
            "指运港": ("指运港",),
            "离境口岸": ("离境口岸",),
            "包装种类": ("包装种类",),
            "随附单证及编号": ("随附单证",),
            "标记唛码及备注": ("标记唛码", "备注"),
            "合同协议号": ("合同协议号", "合同号"),
            "提运单号": ("提运单号",),
            "毛重": ("毛重",),
            "净重": ("净重",),
            "件数": ("件数",),
        }
        upper_question = question.upper()
        matched = next(
            (field for field, names in aliases.items() if any(name.upper() in upper_question for name in names)),
            None,
        )
        if not matched:
            return None, []
        results = []
        documents = self.resolve_documents(question)
        commodity_fields = {
            "商品编号", "商品名称", "规格型号", "数量及单位", "单价/总价/币制",
            "原产国（地区）", "最终目的国（地区）", "境内货源地", "征免",
        }
        for document in documents:
            value = document["fields"].get(matched)
            indexed = [
                v for k, v in document["fields"].items()
                if k.endswith(f"-{matched}") and v
            ]
            if indexed and (matched in commodity_fields or not value):
                value = "；".join(dict.fromkeys(indexed))
            if value:
                results.append({
                    "document_id": document["id"], "filename": document["filename"],
                    "field": matched, "value": value,
                })
        return matched, results

    def resolve_documents(self, question: str):
        """Scope a question to named companies/IDs before field retrieval."""
        documents = self.list_documents()
        compact_question = re.sub(r"[\s_\-]+", "", question).lower()
        identifiers = re.findall(r"[A-Z0-9]{8,}", question.upper())
        company_candidates = re.findall(
            r"[\u4e00-\u9fff]{2,}(?:有限责任公司|股份有限公司|有限公司|公司)", question
        )
        scoped = []
        for document in documents:
            searchable_values = [document["filename"]]
            searchable_values.extend(str(value) for value in document["fields"].values())
            searchable = re.sub(r"[\s_\-]+", "", " ".join(searchable_values)).lower()
            company_match = any(
                re.sub(r"[\s_\-]+", "", candidate).lower() in searchable
                for candidate in company_candidates
            )
            identifier_match = any(identifier.lower() in searchable for identifier in identifiers)
            if company_match or identifier_match:
                scoped.append(document)
        # Only narrow the search when the question supplied a usable discriminator.
        return scoped if (company_candidates or identifiers) else documents

    def search(self, query: str, limit: int = 5):
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", query.lower())
        # Chinese FTS tokenization often keeps long sequences intact. OR plus LIKE fallback improves recall.
        fts_query = " OR ".join(f'"{token}"' for token in tokens[:12])
        with self.connect() as conn:
            rows = []
            if fts_query:
                try:
                    rows = conn.execute("""
                        SELECT c.content, c.document_id, c.chunk_index, d.filename, bm25(chunks) score
                        FROM chunks c JOIN documents d ON d.id=c.document_id
                        WHERE chunks MATCH ? ORDER BY score LIMIT ?
                    """, (fts_query, limit * 4)).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows and tokens:
                clauses = " OR ".join("c.content LIKE ?" for _ in tokens[:8])
                rows = conn.execute(f"""
                    SELECT c.content, c.document_id, c.chunk_index, d.filename, 0 score
                    FROM chunks c JOIN documents d ON d.id=c.document_id
                    WHERE {clauses} LIMIT ?
                """, (*[f"%{t}%" for t in tokens[:8]], limit * 4)).fetchall()
        candidates = [dict(row) for row in rows]

        def quality(item):
            content = item["content"]
            replacement = content.count("�")
            controls = sum(not ch.isprintable() and not ch.isspace() for ch in content)
            unusual = sum(
                not (ch.isalnum() or ch.isspace() or "\u4e00" <= ch <= "\u9fff" or ch in "，。；：、（）()[]【】{}<>《》+-_./,%$￥'\"!?：")
                for ch in content
            )
            readable = 1 - min(1, (replacement * 8 + controls * 8 + unusual) / max(len(content), 1))
            structured_bonus = 0.35 if "[结构化字段]" in content else 0
            return readable + structured_bonus

        candidates.sort(key=quality, reverse=True)
        selected = []
        seen_documents = set()
        for item in candidates:
            if quality(item) < 0.72 or item["document_id"] in seen_documents:
                continue
            selected.append(item)
            seen_documents.add(item["document_id"])
            if len(selected) >= limit:
                break
        return selected
