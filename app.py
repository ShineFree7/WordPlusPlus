# -*- coding: utf-8 -*-
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone

from flask import Flask, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "official.db")
DEFAULT_MAX_USERS = 7

app = Flask(__name__)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            state_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    db.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('max_users', ?)",
        (str(DEFAULT_MAX_USERS),),
    )
    db.commit()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_setting(name, default=None):
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (name,)).fetchone()
    return row["value"] if row else default


def set_setting(name, value):
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (name, str(value)),
    )
    db.commit()


def user_by_phone(phone):
    return get_db().execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()


def user_by_token(token):
    if not token:
        return None
    row = get_db().execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    ).fetchone()
    return row


def require_user():
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "", 1).strip() if auth.startswith("Bearer ") else ""
    user = user_by_token(token)
    if not user:
        return None
    return {"id": user["id"], "phone": user["phone"], "is_admin": bool(user["is_admin"]), "token": token}


def default_state():
    return {
        "startDate": "",
        "blocks": [],
        "nextBlockId": 1,
        "wordImages": {},
        "viewDay": None,
        "completedDays": {},
        "days": {},
    }


def validate_phone(phone):
    return bool(re.fullmatch(r"1[3-9]\d{9}", phone or ""))


@app.route("/")
def index():
    path = os.path.join(BASE_DIR, "index.html")
    if not os.path.exists(path):
        return "index.html missing", 500
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    phone = str(data.get("phone", "")).strip()
    password = str(data.get("password", ""))

    if not validate_phone(phone):
        return jsonify({"error": "请输入正确的 11 位手机号"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400

    db = get_db()
    if user_by_phone(phone):
        return jsonify({"error": "这个手机号已经注册过了"}), 409

    max_users = int(get_setting("max_users", str(DEFAULT_MAX_USERS)))
    count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count >= max_users:
        return jsonify({"error": f"注册名额已满（最多 {max_users} 人）"}), 403

    is_admin = 1 if count == 0 else 0
    token = secrets.token_urlsafe(32)
    created = now_iso()
    db.execute(
        "INSERT INTO users (phone, password_hash, is_admin, state_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (phone, generate_password_hash(password), is_admin, json.dumps(default_state(), ensure_ascii=False), created),
    )
    user_id = db.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone()["id"]
    db.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, user_id, created))
    db.commit()
    return jsonify({"token": token, "user": {"phone": phone, "is_admin": bool(is_admin)}})


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    phone = str(data.get("phone", "")).strip()
    password = str(data.get("password", ""))
    user = user_by_phone(phone)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "手机号或密码不对"}), 401
    token = secrets.token_urlsafe(32)
    db = get_db()
    db.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, user["id"], now_iso()))
    db.commit()
    return jsonify({"token": token, "user": {"phone": user["phone"], "is_admin": bool(user["is_admin"])}})


@app.post("/api/logout")
def logout():
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "", 1).strip() if auth.startswith("Bearer ") else ""
    if token:
        get_db().execute("DELETE FROM sessions WHERE token = ?", (token,))
        get_db().commit()
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    user = require_user()
    if not user:
        return jsonify({"error": "未登录"}), 401
    return jsonify({"user": {"phone": user["phone"], "is_admin": user["is_admin"]}})


@app.get("/api/state")
def get_state():
    user = require_user()
    if not user:
        return jsonify({"error": "未登录"}), 401
    row = get_db().execute("SELECT state_json FROM users WHERE id = ?", (user["id"],)).fetchone()
    try:
        state = json.loads(row["state_json"] or "{}")
    except Exception:
        state = default_state()
    return jsonify({"state": state})


@app.post("/api/state")
def save_state():
    user = require_user()
    if not user:
        return jsonify({"error": "未登录"}), 401
    data = request.get_json(silent=True) or {}
    state = data.get("state")
    if not isinstance(state, dict):
        return jsonify({"error": "数据格式不对"}), 400
    db = get_db()
    db.execute(
        "UPDATE users SET state_json = ? WHERE id = ?",
        (json.dumps(state, ensure_ascii=False), user["id"]),
    )
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/admin/users")
def admin_users():
    user = require_user()
    if not user or not user["is_admin"]:
        return jsonify({"error": "没有管理员权限"}), 403
    rows = get_db().execute(
        "SELECT id, phone, is_admin, created_at FROM users ORDER BY id"
    ).fetchall()
    max_users = int(get_setting("max_users", str(DEFAULT_MAX_USERS)))
    return jsonify(
        {
            "max_users": max_users,
            "users": [
                {
                    "id": r["id"],
                    "phone": r["phone"],
                    "is_admin": bool(r["is_admin"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
        }
    )


@app.post("/api/admin/users/<int:user_id>/delete")
def admin_delete_user(user_id):
    user = require_user()
    if not user or not user["is_admin"]:
        return jsonify({"error": "没有管理员权限"}), 403
    target = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "用户不存在"}), 404
    if target["id"] == user["id"]:
        return jsonify({"error": "不能删除自己的账号"}), 400
    db = get_db()
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/admin/settings")
def admin_settings():
    user = require_user()
    if not user or not user["is_admin"]:
        return jsonify({"error": "没有管理员权限"}), 403
    data = request.get_json(silent=True) or {}
    max_users = data.get("max_users")
    try:
        max_users = int(max_users)
    except Exception:
        return jsonify({"error": "名额数量格式不对"}), 400
    if max_users < 1 or max_users > 100:
        return jsonify({"error": "名额需在 1 到 100 之间"}), 400
    set_setting("max_users", max_users)
    return jsonify({"ok": True, "max_users": max_users})


with app.app_context():
    init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))
    app.run(host="0.0.0.0", port=port, debug=False)
