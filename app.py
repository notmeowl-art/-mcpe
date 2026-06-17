"""FireMC Shop — Flask + SQLite port of the original React/Supabase app.

Run:
    pip install flask
    python app.py
Then open http://localhost:5000

The first user that registers becomes the admin automatically.
"""
import os
import sqlite3
import secrets
import hashlib
from datetime import datetime
from functools import wraps
from flask import (
    Flask, g, request, redirect, url_for, render_template,
    session, flash, abort, jsonify,
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "firemc.db")
SERVER_IP = "Play.firemc.fun"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-prod-" + secrets.token_hex(8))


# ---------- DB ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          coins INTEGER NOT NULL DEFAULT 100,
          role TEXT NOT NULL DEFAULT 'user',  -- admin | moderator | user
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT 'kits',
          price INTEGER NOT NULL DEFAULT 10,
          image_url TEXT,
          badge TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
          item_name TEXT NOT NULL,
          price INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',  -- pending|confirmed|cancelled
          minecraft_username TEXT,
          contact TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS earn_links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          url TEXT NOT NULL,
          coins INTEGER NOT NULL DEFAULT 5,
          wait_seconds INTEGER NOT NULL DEFAULT 30,
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS earn_clicks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          link_id INTEGER NOT NULL REFERENCES earn_links(id) ON DELETE CASCADE,
          started_at TEXT NOT NULL DEFAULT (datetime('now')),
          completed_at TEXT,
          coins_awarded INTEGER
        );
        """
    )

    # Seed items if empty
    cur = db.execute("SELECT COUNT(*) AS c FROM items")
    if cur.fetchone()["c"] == 0:
        seed = [
            ("VIP Rank", "VIP tag, /fly in lobby, 5 /sethome, colored chat", "ranks", 50, "/static/img/item-rank.png", "Starter"),
            ("MVP Rank", "MVP tag, /fly anywhere, 10 /sethome, daily crate key", "ranks", 150, "/static/img/item-rank.png", "Popular"),
            ("LEGEND Rank", "All perks, private vault, custom prefix, monthly bonus", "ranks", 500, "/static/img/item-rank.png", "Best Value"),
            ("Starter Kit", "Iron sword, iron armor set, bread x16, cobble x64", "kits", 30, "/static/img/item-kit.png", None),
            ("PvP Kit", "Diamond sword Sharp III, diamond armor Prot II, golden apples", "kits", 100, "/static/img/item-kit.png", "Hot"),
            ("God Kit", "Netherite full set Prot IV, Sharp V sword, god apples x16", "kits", 250, "/static/img/item-kit.png", "Endgame"),
            ("Sharpness V Sword", "Diamond sword, Sharpness V, Unbreaking III, Fire Aspect II", "weapons", 60, "/static/img/item-sword.png", None),
            ("Power V Bow", "Power V, Punch II, Infinity, Unbreaking III", "weapons", 50, "/static/img/item-bow.png", None),
            ("Prot IV Armor Set", "Diamond full set, Protection IV, Unbreaking III, Thorns II", "weapons", 120, "/static/img/item-armor.png", "Set"),
        ]
        db.executemany(
            "INSERT INTO items(name,description,category,price,image_url,badge) VALUES (?,?,?,?,?,?)",
            seed,
        )

    cur = db.execute("SELECT COUNT(*) AS c FROM earn_links")
    if cur.fetchone()["c"] == 0:
        db.executemany(
            "INSERT INTO earn_links(title,url,coins,wait_seconds) VALUES (?,?,?,?)",
            [
                ("Visit our partner site", "https://example.com", 5, 20),
                ("Watch a 30s ad", "https://example.com/ad", 10, 30),
            ],
        )

    db.commit()
    db.close()


# ---------- Auth helpers ----------
def hash_password(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.scrypt(pw.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=32)
    return f"{salt}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(stored, hash_password(pw, salt))


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


@app.context_processor
def inject_globals():
    u = current_user()
    return {
        "user": u,
        "is_admin": bool(u and u["role"] == "admin"),
        "server_ip": SERVER_IP,
    }


def login_required(fn):
    @wraps(fn)
    def w(*a, **kw):
        if not current_user():
            return redirect(url_for("auth", next=request.path))
        return fn(*a, **kw)
    return w


def admin_required(fn):
    @wraps(fn)
    def w(*a, **kw):
        u = current_user()
        if not u or u["role"] != "admin":
            abort(403)
        return fn(*a, **kw)
    return w


# ---------- Routes ----------
@app.route("/")
def index():
    db = get_db()
    cat = request.args.get("cat", "recommended")
    q = request.args.get("q", "").strip()
    sql = "SELECT * FROM items"
    args: list = []
    where = []
    if cat != "recommended":
        where.append("category=?")
        args.append(cat)
    if q:
        where.append("LOWER(name) LIKE ?")
        args.append(f"%{q.lower()}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY category, price"
    items = db.execute(sql, args).fetchall()
    cats = [r["category"] for r in db.execute("SELECT DISTINCT category FROM items ORDER BY category")]
    return render_template("index.html", items=items, categories=cats, active_cat=cat, search=q)


@app.route("/auth", methods=["GET", "POST"])
def auth():
    if request.method == "POST":
        mode = request.form.get("mode", "login")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Email and password required.", "error")
            return redirect(url_for("auth"))
        db = get_db()
        if mode == "signup":
            try:
                count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
                role = "admin" if count == 0 else "user"
                db.execute(
                    "INSERT INTO users(email,password_hash,role) VALUES (?,?,?)",
                    (email, hash_password(password), role),
                )
                db.commit()
            except sqlite3.IntegrityError:
                flash("Email already registered.", "error")
                return redirect(url_for("auth"))
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("auth"))
        else:  # login
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                flash("Invalid credentials.", "error")
                return redirect(url_for("auth"))
            session["uid"] = row["id"]
            return redirect(request.args.get("next") or url_for("index"))
    return render_template("auth.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/buy/<int:item_id>", methods=["GET", "POST"])
@login_required
def buy(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        abort(404)
    u = current_user()
    if request.method == "POST":
        mc = request.form.get("mc", "").strip()
        contact = request.form.get("contact", "").strip()
        if not mc or not contact:
            flash("Minecraft username and contact required.", "error")
            return redirect(url_for("buy", item_id=item_id))
        if u["coins"] < item["price"]:
            flash("Not enough coins.", "error")
            return redirect(url_for("index"))
        db.execute("UPDATE users SET coins = coins - ? WHERE id=?", (item["price"], u["id"]))
        db.execute(
            "INSERT INTO orders(user_id,item_id,item_name,price,minecraft_username,contact) VALUES (?,?,?,?,?,?)",
            (u["id"], item["id"], item["name"], item["price"], mc, contact),
        )
        db.commit()
        flash(f"Order placed for {item['name']}.", "success")
        return redirect(url_for("orders"))
    return render_template("buy.html", item=item)


@app.route("/orders")
@login_required
def orders():
    db = get_db()
    u = current_user()
    if u["role"] == "admin":
        rows = db.execute(
            "SELECT o.*, u.email AS user_email FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.created_at DESC"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC", (u["id"],)
        ).fetchall()
    return render_template("orders.html", orders=rows)


@app.route("/orders/<int:order_id>/<action>", methods=["POST"])
@admin_required
def order_action(order_id, action):
    db = get_db()
    o = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not o:
        abort(404)
    if action == "confirm" and o["status"] == "pending":
        db.execute("UPDATE orders SET status='confirmed' WHERE id=?", (order_id,))
    elif action == "cancel" and o["status"] == "pending":
        db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
        db.execute("UPDATE users SET coins = coins + ? WHERE id=?", (o["price"], o["user_id"]))
    db.commit()
    return redirect(url_for("orders"))


# ---- Earn ----
@app.route("/earn")
@login_required
def earn():
    db = get_db()
    links = db.execute("SELECT * FROM earn_links WHERE active=1 ORDER BY coins DESC").fetchall()
    return render_template("earn.html", links=links)


@app.route("/earn/<int:link_id>/start", methods=["POST"])
@login_required
def earn_start(link_id):
    db = get_db()
    link = db.execute("SELECT * FROM earn_links WHERE id=? AND active=1", (link_id,)).fetchone()
    if not link:
        return jsonify({"error": "unavailable"}), 404
    u = current_user()
    cur = db.execute(
        "INSERT INTO earn_clicks(user_id,link_id) VALUES (?,?)", (u["id"], link_id)
    )
    db.commit()
    return jsonify({"click_id": cur.lastrowid, "url": link["url"], "wait_seconds": link["wait_seconds"]})


@app.route("/earn/complete/<int:click_id>", methods=["POST"])
@login_required
def earn_complete(click_id):
    db = get_db()
    u = current_user()
    click = db.execute("SELECT * FROM earn_clicks WHERE id=?", (click_id,)).fetchone()
    if not click or click["user_id"] != u["id"]:
        return jsonify({"error": "invalid"}), 400
    if click["completed_at"]:
        return jsonify({"error": "already"}), 400
    link = db.execute("SELECT * FROM earn_links WHERE id=?", (click["link_id"],)).fetchone()
    started = datetime.fromisoformat(click["started_at"])
    if (datetime.utcnow() - started).total_seconds() < link["wait_seconds"]:
        return jsonify({"error": "too soon"}), 400
    db.execute(
        "UPDATE earn_clicks SET completed_at=datetime('now'), coins_awarded=? WHERE id=?",
        (link["coins"], click_id),
    )
    db.execute("UPDATE users SET coins = coins + ? WHERE id=?", (link["coins"], u["id"]))
    db.commit()
    return jsonify({"coins": link["coins"]})


# ---- Leaderboard ----
@app.route("/leaderboard")
def leaderboard():
    db = get_db()
    rows = db.execute("SELECT email, coins FROM users ORDER BY coins DESC LIMIT 20").fetchall()
    return render_template("leaderboard.html", rows=rows)


# ---- Admin ----
@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    items = db.execute("SELECT * FROM items ORDER BY category, price").fetchall()
    users = db.execute("SELECT id,email,coins,role FROM users ORDER BY coins DESC").fetchall()
    links = db.execute("SELECT * FROM earn_links ORDER BY created_at DESC").fetchall()
    return render_template("admin.html", items=items, users=users, links=links)


@app.route("/admin/item/save", methods=["POST"])
@admin_required
def admin_item_save():
    db = get_db()
    f = request.form
    iid = f.get("id", "").strip()
    data = (
        f.get("name", "").strip(),
        f.get("description", "").strip(),
        f.get("category", "kits").strip(),
        int(f.get("price", "10") or 10),
        f.get("image_url", "").strip() or None,
        f.get("badge", "").strip() or None,
    )
    if iid:
        db.execute(
            "UPDATE items SET name=?,description=?,category=?,price=?,image_url=?,badge=? WHERE id=?",
            (*data, int(iid)),
        )
    else:
        db.execute(
            "INSERT INTO items(name,description,category,price,image_url,badge) VALUES (?,?,?,?,?,?)",
            data,
        )
    db.commit()
    return redirect(url_for("admin"))


@app.route("/admin/item/<int:item_id>/delete", methods=["POST"])
@admin_required
def admin_item_delete(item_id):
    db = get_db()
    db.execute("DELETE FROM items WHERE id=?", (item_id,))
    db.commit()
    return redirect(url_for("admin"))


@app.route("/admin/user/<int:user_id>/role", methods=["POST"])
@admin_required
def admin_user_role(user_id):
    role = request.form.get("role", "user")
    if role not in ("admin", "moderator", "user"):
        abort(400)
    db = get_db()
    db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    db.commit()
    return redirect(url_for("admin"))


@app.route("/admin/user/<int:user_id>/coins", methods=["POST"])
@admin_required
def admin_user_coins(user_id):
    amount = int(request.form.get("amount", "0") or 0)
    db = get_db()
    db.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE id=?", (amount, user_id))
    db.commit()
    return redirect(url_for("admin"))


@app.route("/admin/link/save", methods=["POST"])
@admin_required
def admin_link_save():
    db = get_db()
    f = request.form
    lid = f.get("id", "").strip()
    data = (
        f.get("title", "").strip(),
        f.get("url", "").strip(),
        int(f.get("coins", "5") or 5),
        int(f.get("wait_seconds", "30") or 30),
        1 if f.get("active") else 0,
    )
    if lid:
        db.execute(
            "UPDATE earn_links SET title=?,url=?,coins=?,wait_seconds=?,active=? WHERE id=?",
            (*data, int(lid)),
        )
    else:
        db.execute(
            "INSERT INTO earn_links(title,url,coins,wait_seconds,active) VALUES (?,?,?,?,?)",
            data,
        )
    db.commit()
    return redirect(url_for("admin"))


@app.route("/admin/link/<int:link_id>/delete", methods=["POST"])
@admin_required
def admin_link_delete(link_id):
    db = get_db()
    db.execute("DELETE FROM earn_links WHERE id=?", (link_id,))
    db.commit()
    return redirect(url_for("admin"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
