import os

from fastapi.testclient import TestClient


os.environ["PUBLIC_AUTH_USERNAME"] = "customs-user"
os.environ["PUBLIC_SESSION_SECRET"] = "test-session-secret-that-is-long-enough"
os.environ["PUBLIC_AUTH_PASSWORD_HASH"] = (
    "pbkdf2_sha256$1$dGVzdC1zYWx0$"
    "uR-sV8Y_DUTzSX7AHwSBt5IO0MUZrwBRm2GwmW8aoCo"
)

from app_public import app


def test_anonymous_browser_is_redirected():
    client = TestClient(app, base_url="https://testserver")
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_anonymous_api_is_rejected():
    client = TestClient(app, base_url="https://testserver")
    response = client.get("/api/documents")
    assert response.status_code == 401


def test_wrong_password_returns_to_login():
    client = TestClient(app, base_url="https://testserver")
    response = client.post(
        "/login",
        data={"username": "customs-user", "password": "wrong"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=1"
