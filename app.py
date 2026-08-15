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
MAX_USERS_LIMIT = 999999
WORD_QUOTA = 10000
# PythonAnywhere 免费版磁盘额度约 512MB，可用环境变量 FREE_STORAGE_MB 调整
FREE_STORAGE_QUOTA = int(float(os.environ.get("FREE_STORAGE_MB", "512")) * 1024 * 1024)

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


def get_admin_phone():
    phone = (os.environ.get("ADMIN_PHONE") or "").strip()
    if phone:
        return phone
    path = os.path.join(BASE_DIR, "admin_phone.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    return ""


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
    cols = [row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()]
    if "remark" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN remark TEXT NOT NULL DEFAULT ''")
    purge_old_images()
    db.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('max_users', ?)",
        (str(DEFAULT_MAX_USERS),),
    )
    db.commit()
    sync_admin_role()


def purge_old_images():
    db = get_db()
    rows = db.execute("SELECT id, state_json FROM users").fetchall()
    changed = 0
    for r in rows:
        try:
            state = json.loads(r["state_json"] or "{}")
        except Exception:
            continue
        if isinstance(state, dict) and "wordImages" in state:
            state.pop("wordImages", None)
            db.execute(
                "UPDATE users SET state_json = ? WHERE id = ?",
                (json.dumps(state, ensure_ascii=False), r["id"]),
            )
            changed += 1
    if changed:
        db.commit()


def sync_admin_role():
    phone = get_admin_phone()
    if not phone:
        return
    db = get_db()
    db.execute(
        "UPDATE users SET is_admin = CASE WHEN phone = ? THEN 1 ELSE 0 END",
        (phone,),
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
        "viewDay": None,
        "completedDays": {},
        "days": {},
    }


def validate_phone(phone):
    return bool(re.fullmatch(r"1[3-9]\d{9}", phone or ""))


def admin_password_error(password, phone):
    if len(password) < 12:
        return "管理员密码至少 12 位"
    missing = []
    if not any(c.isupper() for c in password):
        missing.append("大写字母")
    if not any(c.islower() for c in password):
        missing.append("小写字母")
    if not any(c.isdigit() for c in password):
        missing.append("数字")
    if not any(not c.isalnum() for c in password):
        missing.append("符号")
    if missing:
        return "管理员密码需要包含：" + "、".join(missing)
    if phone and phone in password:
        return "管理员密码不能包含手机号"
    if re.search(r"(19|20)\d{2}", password):
        return "管理员密码避免使用生日、年份等易猜内容"
    return None


def get_global_corrections():
    raw = get_setting("global_corrections", "{}")
    try:
        value = json.loads(raw) if isinstance(raw, str) else {}
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


def set_global_corrections(value):
    set_setting("global_corrections", json.dumps(value, ensure_ascii=False))


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

    admin_phone = get_admin_phone()
    is_admin = 1 if admin_phone and phone == admin_phone else 0
    if is_admin:
        err = admin_password_error(password, phone)
        if err:
            return jsonify({"error": err}), 400
    elif len(password) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400

    db = get_db()
    if user_by_phone(phone):
        return jsonify({"error": "这个手机号已经注册过了"}), 409

    max_users = int(get_setting("max_users", str(DEFAULT_MAX_USERS)))
    if max_users > 0:
        count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count >= max_users:
            return jsonify({"error": f"注册名额已满（最多 {max_users} 人）"}), 403

    token = secrets.token_urlsafe(32)
    created = now_iso()
    db.execute(
        "INSERT INTO users (phone, password_hash, is_admin, state_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            phone,
            generate_password_hash(password),
            is_admin,
            json.dumps(default_state(), ensure_ascii=False),
            created,
        ),
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


@app.post("/api/change-password")
def change_password():
    user = require_user()
    if not user:
        return jsonify({"error": "未登录"}), 401
    data = request.get_json(silent=True) or {}
    old_password = str(data.get("old_password", ""))
    new_password = str(data.get("new_password", ""))
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], old_password):
        return jsonify({"error": "当前密码不对"}), 400
    if user["is_admin"]:
        err = admin_password_error(new_password, row["phone"])
        if err:
            return jsonify({"error": err}), 400
    elif len(new_password) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400
    get_db().execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user["id"]),
    )
    get_db().commit()
    return jsonify({"ok": True})


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


@app.get("/api/corrections")
def get_corrections():
    user = require_user()
    if not user:
        return jsonify({"error": "未登录"}), 401
    return jsonify({"global": get_global_corrections()})


@app.get("/api/admin/users")
def admin_users():
    user = require_user()
    if not user or not user["is_admin"]:
        return jsonify({"error": "没有管理员权限"}), 403
    rows = get_db().execute(
        "SELECT id, phone, remark, is_admin, created_at, state_json FROM users ORDER BY id"
    ).fetchall()
    max_users = int(get_setting("max_users", str(DEFAULT_MAX_USERS)))
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    users = []
    total_word_count = 0
    for r in rows:
        try:
            state = json.loads(r["state_json"] or "{}")
        except Exception:
            state = {}
        if not isinstance(state, dict):
            state = {}
        blocks = [b for b in (state.get("blocks") or []) if isinstance(b, dict)]
        block_count = len(blocks)
        word_count = sum(len(b.get("words") or []) for b in blocks)
        total_word_count += word_count
        users.append(
            {
                "id": r["id"],
                "phone": r["phone"],
                "remark": r["remark"] or "",
                "is_admin": bool(r["is_admin"]),
                "created_at": r["created_at"],
                "block_count": block_count,
                "word_count": word_count,
            }
        )
    return jsonify(
        {
            "max_users": max_users,
            "registered_count": len(users),
            "db_size": db_size,
            "free_quota": FREE_STORAGE_QUOTA,
            "total_word_count": total_word_count,
            "word_quota": WORD_QUOTA,
            "global_corrections": get_global_corrections(),
            "users": users,
        }
    )


@app.post("/api/admin/users/<int:user_id>/remark")
def admin_set_remark(user_id):
    user = require_user()
    if not user or not user["is_admin"]:
        return jsonify({"error": "没有管理员权限"}), 403
    target = get_db().execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "用户不存在"}), 404
    data = request.get_json(silent=True) or {}
    remark = str(data.get("remark", "")).strip()[:80]
    get_db().execute("UPDATE users SET remark = ? WHERE id = ?", (remark, user_id))
    get_db().commit()
    return jsonify({"ok": True, "remark": remark})


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


@app.post("/api/admin/global-corrections")
def admin_global_corrections():
    user = require_user()
    if not user or not user["is_admin"]:
        return jsonify({"error": "没有管理员权限"}), 403
    data = request.get_json(silent=True) or {}
    word = str(data.get("word", "")).strip().lower()
    zh = str(data.get("zh", "")).strip()
    if not word or len(word) > 100:
        return jsonify({"error": "单词格式不对"}), 400
    if len(zh) > 200:
        return jsonify({"error": "释义太长"}), 400
    corrections = get_global_corrections()
    if zh:
        corrections[word] = zh
    else:
        corrections.pop(word, None)
    set_global_corrections(corrections)
    return jsonify({"ok": True, "global_corrections": corrections})


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
    if max_users < 0 or max_users > MAX_USERS_LIMIT:
        return jsonify({"error": "名额需为 0（不限）或 1 到 999999"}), 400
    set_setting("max_users", max_users)
    return jsonify({"ok": True, "max_users": max_users})


with app.app_context():
    init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))
    app.run(host="0.0.0.0", port=port, debug=False)
