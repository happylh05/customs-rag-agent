# 报关单智能检索助手

本地优先的报关单 RAG 应用。支持一次批量选择 PDF、DOCX、TXT、Markdown 文件，逐份提取字段、分块写入 SQLite 全文索引，并在问答时返回原文证据。单个文件失败不会中断同批次的其他文件。检索不到时固定回答“未在已入库的报关单中找到相关信息”，不调用模型补写。

针对中国海关标准出口货物报关单，系统会恢复 PDF 绘制对象中的完整字段，包括企业、关别、日期、运输、监管、征免、合同、国家/港口、重量金额、随附单证、备注以及多行商品明细。页面中的“查看全部识别数据”可以核对全部入库字段。

## 运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a; source .env; set +a
uvicorn app:app --reload
```

打开 <http://127.0.0.1:8000>。

`OPENAI_API_KEY` 可留空：此时系统执行本地解析、结构化查询和全文检索，不生成自由归纳答案。需要启用 LLM 时，将 `.env.example` 复制为 `.env`，填入服务端密钥并重启；应用会自动读取 `.env`。配置后，密钥仅在服务端使用，模型只接收已经检索出的证据片段；调用设置 `store=False`。生产环境应补充登录鉴权、租户隔离、病毒扫描、审计日志和备份策略。

若使用 AGICTO 等 OpenAI 兼容服务，配置 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 和 `LLM_API_MODE=chat_completions`。第三方服务会接收发送给模型的检索证据，使用前应确认其数据保护与合规条款。

## 当前边界

- DOC 旧格式请先转成 DOCX。
- 图片型扫描 PDF 当前会拒绝入库并提示先 OCR，避免把空白或错误内容写进知识库。
- SQLite FTS5 是轻量本地 RAG，适合原型和中小规模数据；大规模部署可替换为向量数据库，同时保留相同的“无证据不回答”门控。

## 测试

```bash
pytest -q
```
