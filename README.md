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

## Docker 部署

复制环境变量模板并填写服务端密钥：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Compose 默认只把应用绑定到服务器的 `127.0.0.1:8000`，不会直接暴露到公网。正式共享前需在前方配置 HTTPS、登录鉴权和访问控制，切勿直接开放公网 8000 端口。

## 独立公网登录版

公网版使用独立入口 `app_public.py`、独立容器和独立数据目录，不会改变上面的 Tailscale/本机版。先在服务器创建 `.env.public`：

```bash
python3 scripts/hash_password.py
openssl rand -hex 32
nano .env.public
```

将前两条命令的结果分别写入以下配置。密码哈希和会话密钥不得提交到 Git：

```dotenv
PUBLIC_AUTH_USERNAME=你的登录账号
PUBLIC_AUTH_PASSWORD_HASH=密码生成器输出的整行内容
PUBLIC_SESSION_SECRET=openssl生成的随机内容
PUBLIC_SESSION_HOURS=12
MAX_UPLOAD_MB=25

# 沿用现有模型服务时，在服务器中安全填写；不要发送到聊天或提交到 Git。
LLM_API_KEY=
LLM_BASE_URL=https://api.agicto.cn/v1
LLM_MODEL=gpt-5.6-luna
LLM_API_MODE=chat_completions
```

启动并检查：

```bash
sudo docker compose -f compose.public.yaml up -d --build
sudo docker compose -f compose.public.yaml ps
curl http://127.0.0.1:8001/api/health
```

公网容器只监听 `127.0.0.1:8001`。必须通过 Caddy 或 Nginx 提供 HTTPS，不能直接在腾讯云安全组开放 8001。`Caddyfile.public.example` 是反向代理模板；把其中域名替换为已解析到服务器公网 IP 的域名后再启用。登录 Cookie 仅允许通过 HTTPS 发送。
