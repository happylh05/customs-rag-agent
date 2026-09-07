import hashlib
import hmac
import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import defaultdict, deque

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import app


COOKIE_NAME = "customs_session"
SESSION_TTL = int(os.getenv("PUBLIC_SESSION_HOURS", "12")) * 3600
LOGIN_WINDOW = 15 * 60
LOGIN_LIMIT = 8
attempts: dict[str, deque[float]] = defaultdict(deque)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"公网版缺少必需环境变量：{name}")
    return value


AUTH_USERNAME = _required("PUBLIC_AUTH_USERNAME")
AUTH_PASSWORD_HASH = _required("PUBLIC_AUTH_PASSWORD_HASH")
SESSION_SECRET = _required("PUBLIC_SESSION_SECRET").encode()


def _b64(value: bytes) -> str:
    return urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str) -> bool:
    try:
        algorithm, iterations, salt_text, expected_text = AUTH_PASSWORD_HASH.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt_text), int(iterations))
        return hmac.compare_digest(_b64(actual), expected_text)
    except (TypeError, ValueError):
        return False


def make_session() -> str:
    expires = str(int(time.time()) + SESSION_TTL)
    nonce = secrets.token_urlsafe(12)
    payload = f"{AUTH_USERNAME}|{expires}|{nonce}"
    signature = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return _b64(payload.encode()) + "." + signature


def valid_session(value: str | None) -> bool:
    if not value or "." not in value:
        return False
    encoded, supplied = value.rsplit(".", 1)
    try:
        payload = _unb64(encoded).decode()
        username, expires, _ = payload.split("|", 2)
        expected = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
        return username == AUTH_USERNAME and int(expires) >= int(time.time()) and hmac.compare_digest(expected, supplied)
    except (UnicodeDecodeError, ValueError):
        return False


@app.middleware("http")
async def require_public_login(request: Request, call_next):
    if request.url.path in {"/login", "/api/health"}:
        return await call_next(request)
    if valid_session(request.cookies.get(COOKIE_NAME)):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "请先登录"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(error: int = 0):
    message = '<p class="error">用户名或密码错误，请稍后重试。</p>' if error else ""
    return HTMLResponse(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>登录｜报关智能体</title><style>
    *{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(145deg,#eff6ff,#ecfeff);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#102a43}}.card{{width:min(92vw,420px);padding:38px;border:1px solid #d9e8f5;border-radius:22px;background:#fffffff2;box-shadow:0 24px 70px #1453741f}}.mark{{display:grid;place-items:center;width:52px;height:52px;border-radius:15px;background:#075985;color:white;font-size:25px;font-weight:800}}h1{{margin:20px 0 7px;font-size:27px}}.sub{{margin:0 0 26px;color:#627d98}}label{{display:block;margin:14px 0 7px;font-weight:650}}input{{width:100%;height:46px;border:1px solid #bcccdc;border-radius:11px;padding:0 13px;font-size:16px}}button{{width:100%;height:47px;margin-top:24px;border:0;border-radius:11px;background:#0369a1;color:white;font-size:16px;font-weight:700;cursor:pointer}}.error{{padding:10px;border-radius:9px;background:#fff1f2;color:#be123c;font-size:14px}}.foot{{margin-top:18px;color:#829ab1;font-size:12px;text-align:center}}</style></head><body><main class="card"><div class="mark">关</div><h1>报关智能体</h1><p class="sub">请输入授权账号进入安全工作台</p>{message}<form method="post" action="/login"><label for="username">账号</label><input id="username" name="username" autocomplete="username" required autofocus><label for="password">密码</label><input id="password" name="password" type="password" autocomplete="current-password" required><button type="submit">安全登录</button></form><p class="foot">HTTPS 加密传输 · 登录会话自动过期</p></main></body></html>""")


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    client = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = attempts[client]
    while bucket and bucket[0] < now - LOGIN_WINDOW:
        bucket.popleft()
    if len(bucket) >= LOGIN_LIMIT:
        raise HTTPException(status_code=429, detail="登录尝试过多，请十五分钟后再试")
    if not hmac.compare_digest(username.strip(), AUTH_USERNAME) or not verify_password(password):
        bucket.append(now)
        return RedirectResponse("/login?error=1", status_code=303)
    attempts.pop(client, None)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE_NAME, make_session(), max_age=SESSION_TTL, httponly=True, secure=True, samesite="strict", path="/")
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
