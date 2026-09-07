import getpass
import hashlib
import secrets
from base64 import urlsafe_b64encode


def b64(value: bytes) -> str:
    return urlsafe_b64encode(value).decode().rstrip("=")


password = getpass.getpass("请输入公网版登录密码：")
confirm = getpass.getpass("请再次输入密码：")
if password != confirm:
    raise SystemExit("两次输入的密码不一致")
if len(password) < 12:
    raise SystemExit("密码至少需要 12 个字符")
salt = secrets.token_bytes(18)
iterations = 600_000
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
print(f"pbkdf2_sha256${iterations}${b64(salt)}${b64(digest)}")
