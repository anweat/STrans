from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SECRET = "strans-local-demo-secret"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


class AuthStore:
    def __init__(self, db_path: str | Path = "data/traffic_analysis.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL
                )
                """
            )
            row = conn.execute("SELECT username FROM system_users WHERE username = ?", (ADMIN_USERNAME,)).fetchone()
            if row is None:
                salt, password_hash = self._hash_password(ADMIN_PASSWORD)
                conn.execute(
                    """
                    INSERT INTO system_users (username, password_hash, salt, role, created_at)
                    VALUES (?, ?, ?, 'admin', ?)
                    """,
                    (ADMIN_USERNAME, password_hash, salt, datetime.now().isoformat(timespec="seconds")),
                )

    def _hash_password(self, password: str, salt: str | None = None) -> tuple[str, str]:
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
        return salt, digest.hex()

    def create_user(self, username: str, password: str) -> dict[str, Any]:
        username = username.strip()
        if not username or not password:
            raise ValueError("用户名和密码不能为空")
        if username == ADMIN_USERNAME:
            raise ValueError("该用户名已保留")
        salt, password_hash = self._hash_password(password)
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO system_users (username, password_hash, salt, role, created_at)
                    VALUES (?, ?, ?, 'user', ?)
                    """,
                    (username, password_hash, salt, datetime.now().isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在") from exc
        return {"username": username, "role": "user"}

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT username, password_hash, salt, role FROM system_users WHERE username = ?", (username.strip(),)).fetchone()
        if row is None:
            return None
        _, password_hash = self._hash_password(password, row["salt"])
        if not hmac.compare_digest(password_hash, row["password_hash"]):
            return None
        return {"username": row["username"], "role": row["role"]}

    def make_token(self, user: dict[str, Any], expires_in: int = 60 * 60 * 8) -> str:
        payload = {
            "username": user["username"],
            "role": user["role"],
            "exp": int(time.time()) + expires_in,
        }
        body = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii").rstrip("=")
        signature = hmac.new(SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{body}.{signature}"

    def verify_token(self, token: str) -> dict[str, Any] | None:
        if "." not in token:
            return None
        body, signature = token.rsplit(".", 1)
        expected = hmac.new(SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        try:
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except Exception:
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return {"username": payload.get("username"), "role": payload.get("role")}


auth_store = AuthStore()
