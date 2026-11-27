"""激熱ドパガキ掲示板（Flask）"""
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import gacha
from storage import LocalStore, get_store, new_post_key, now_iso

app = Flask(__name__)
# セッション（ログイン状態）の暗号化キー。Azure では環境変数 SECRET_KEY に入れる。
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # アップロードは 50MB まで

store = get_store()

JST = timezone(timedelta(hours=9))


def to_jst(iso):
    return datetime.fromisoformat(iso).astimezone(JST)


def today_jst():
    return datetime.now(JST).strftime("%Y-%m-%d")


@app.template_filter("jst")
def jst_filter(iso):
    """投稿時間を日本時間で表示する。"""
    try:
        return to_jst(iso).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return iso

NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
POST_ID_RE = re.compile(r"^[0-9]{13}-[0-9a-f]{8}$")
MEDIA_TYPES = {
    "image": {"png", "jpg", "jpeg", "gif", "webp"},
    "video": {"mp4", "webm", "mov"},
    "audio": {"mp3", "wav", "ogg", "m4a"},
}


def current_user():
    return session.get("user")


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() and not store.get_user(current_user()):
            # ログイン情報はあるのにユーザーが見つからない（データが消えたときなど）→ ログアウト扱い
            session.clear()
        if not current_user():
            if request.is_json or request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def check_post_id(post_id):
    if not POST_ID_RE.match(post_id):
        abort(404)


def decorate(posts):
    """テンプレートで使いやすい形にする（ファイルの URL、自分がいいね済みか）。"""
    me = current_user()
    liked = set(store.liked_post_ids(me)) if me else set()
    frames = {}
    for a in {p["author"] for p in posts}:
        u = store.get_user(a)
        frames[a] = (u or {}).get("equipped_frame", "")
    for p in posts:
        p["frame"] = frames.get(p["author"], "")
        p["id"] = p["RowKey"]
        p["media_src"] = store.media_url(p["media_blob"]) if p.get("media_blob") else None
        p["liked"] = p["id"] in liked
        p["dopamine"] = int(p.get("dopamine", 0))
    return posts


@app.context_processor
def inject_user():
    me = current_user()
    user = store.get_user(me) if me else None
    if me and not user:
        session.clear()
        me = None
    return {
        "me": me,
        "my_frame": (user or {}).get("equipped_frame", ""),
        "my_button": (user or {}).get("equipped_button", ""),
        "gacha_ready": bool(user) and user.get("last_gacha") != today_jst(),
        # 投稿した直後だけ演出を出す
        "just_posted": session.pop("just_posted", False),
    }


# ---------------------------------------------------------------------------
# ページ
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    tab = request.args.get("tab", "recommend")
    posts = store.list_posts()
    if tab == "following":
        if not current_user():
            return redirect(url_for("login", next="/?tab=following"))
        follow = set(store.following(current_user()))
        posts = [p for p in posts if p["author"] in follow]
    else:
        tab = "recommend"
        # おすすめ：ドーパミンが多い順（同じなら新しい順）
        posts.sort(key=lambda p: -int(p.get("dopamine", 0)))
    return render_template("index.html", posts=decorate(posts), tab=tab)


@app.route("/me")
@login_required
def my_page():
    me = current_user()
    mine = [p for p in store.list_posts(limit=1000) if p["author"] == me]
    liked = [store.get_post(pid) for pid in store.liked_post_ids(me)]
    liked = sorted([p for p in liked if p], key=lambda p: p["RowKey"])
    return render_template(
        "me.html", posts=decorate(mine), liked=decorate(liked),
        following=store.following(me), followers=store.follower_count(me),
        total=sum(int(p.get("dopamine", 0)) for p in mine),
    )


@app.route("/u/<name>")
def user_page(name):
    if not NAME_RE.match(name) or not store.get_user(name):
        abort(404)
    if name == current_user():
        return redirect(url_for("my_page"))
    posts = [p for p in store.list_posts(limit=1000) if p["author"] == name]
    is_following = bool(current_user()) and name in store.following(current_user())
    return render_template(
        "user.html", name=name, posts=decorate(posts), is_following=is_following,
        frame=store.get_user(name).get("equipped_frame", ""),
        followers=store.follower_count(name),
        total=sum(int(p.get("dopamine", 0)) for p in posts),
    )


# ---------------------------------------------------------------------------
# ログイン・登録
# ---------------------------------------------------------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        pw = request.form.get("password", "")
        if not NAME_RE.match(name):
            flash("ユーザー名は半角英数字と _ で 3〜20 文字にしてね")
        elif len(pw) < 6:
            flash("パスワードは 6 文字以上にしてね")
        elif store.get_user(name):
            flash("その名前はもう使われてるよ")
        else:
            store.create_user(name, generate_password_hash(pw))
            session["user"] = name
            return redirect(url_for("index"))
    return render_template("auth.html", mode="signup")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        pw = request.form.get("password", "")
        user = store.get_user(name) if NAME_RE.match(name) else None
        if user and check_password_hash(user["password_hash"], pw):
            session["user"] = name
            nxt = request.args.get("next", "/")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
        flash("ユーザー名かパスワードが違うよ")
    return render_template("auth.html", mode="login")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# 投稿
# ---------------------------------------------------------------------------
@app.route("/post", methods=["POST"])
@login_required
def create_post():
    title = request.form.get("title", "").strip()[:100]
    body = request.form.get("body", "").strip()[:2000]
    if not title:
        flash("タイトルを入れてね")
        return redirect(request.referrer or url_for("index"))

    post = {
        "RowKey": new_post_key(), "author": current_user(),
        "title": title, "body": body, "created_at": now_iso(), "dopamine": 0,
    }
    f = request.files.get("media")
    if f and f.filename:
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        kind = next((k for k, exts in MEDIA_TYPES.items() if ext in exts), None)
        if not kind:
            flash("画像・動画・音楽ファイルだけ投稿できるよ")
            return redirect(request.referrer or url_for("index"))
        blob = f"{uuid.uuid4().hex}.{ext}"
        store.save_media(blob, f.read(), f.mimetype or "application/octet-stream")
        post["media_blob"] = blob
        post["media_kind"] = kind

    store.add_post(post)
    session["just_posted"] = True
    return redirect(url_for("index", tab="recommend"))


@app.route("/post/<post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    check_post_id(post_id)
    post = store.get_post(post_id)
    if not post or post["author"] != current_user():
        abort(403)
    if post.get("media_blob"):
        store.delete_media(post["media_blob"])
    store.delete_post(post_id)
    return redirect(url_for("my_page"))


# ---------------------------------------------------------------------------
# ドーパミン（いいね）とフォロー
# ---------------------------------------------------------------------------
@app.route("/api/post/<post_id>/dopamine", methods=["POST"])
@login_required
def toggle_dopamine(post_id):
    check_post_id(post_id)
    post = store.get_post(post_id)
    if not post:
        return jsonify(error="not found"), 404
    me = current_user()
    count = int(post.get("dopamine", 0))
    if store.has_liked(post_id, me):
        store.remove_like(post_id, me)
        count = max(0, count - 1)
        liked = False
    else:
        store.add_like(post_id, me)
        count += 1
        liked = True
    store.update_post({"RowKey": post_id, "dopamine": count})
    return jsonify(liked=liked, dopamine=count)


@app.route("/u/<name>/follow", methods=["POST"])
@login_required
def toggle_follow(name):
    if not NAME_RE.match(name) or not store.get_user(name) or name == current_user():
        abort(404)
    if name in store.following(current_user()):
        store.unfollow(current_user(), name)
    else:
        store.follow(current_user(), name)
    return redirect(url_for("user_page", name=name))


# ---------------------------------------------------------------------------
# ランキング
# ---------------------------------------------------------------------------
@app.route("/ranking")
def ranking():
    tab = request.args.get("tab", "today")
    posts = store.list_posts(limit=1000)
    kings = []
    if tab == "king":
        totals = {}
        for p in posts:
            totals[p["author"]] = totals.get(p["author"], 0) + int(p.get("dopamine", 0))
        frames = {a: (store.get_user(a) or {}).get("equipped_frame", "") for a in totals}
        kings = sorted(
            ({"name": a, "total": t, "frame": frames[a]} for a, t in totals.items() if t > 0),
            key=lambda k: -k["total"],
        )[:20]
        posts = []
    else:
        if tab == "today":
            today = today_jst()
            posts = [p for p in posts if to_jst(p["created_at"]).strftime("%Y-%m-%d") == today]
        else:
            tab = "all"
        posts = [p for p in posts if int(p.get("dopamine", 0)) > 0]
        posts = decorate(sorted(posts, key=lambda p: -int(p.get("dopamine", 0)))[:20])
    return render_template("ranking.html", tab=tab, posts=posts, kings=kings)


# ---------------------------------------------------------------------------
# ガチャ（1 日 1 回）
# ---------------------------------------------------------------------------
def owned_items(user):
    try:
        return json.loads(user.get("items") or "[]")
    except ValueError:
        return []


@app.route("/gacha")
@login_required
def gacha_page():
    user = store.get_user(current_user())
    owned = owned_items(user)
    items = [dict(item, id=i, owned=i in owned) for i, item in gacha.ITEMS.items()]
    return render_template(
        "gacha.html", items=items, rarities=gacha.RARITIES,
        equipped={user.get("equipped_frame", ""), user.get("equipped_button", "")},
    )


@app.route("/api/gacha", methods=["POST"])
@login_required
def gacha_draw():
    me = current_user()
    user = store.get_user(me)
    if user.get("last_gacha") == today_jst():
        return jsonify(error="今日はもう引いたよ！また明日！"), 429
    item_id = gacha.draw()
    owned = owned_items(user)
    duplicate = item_id in owned
    if not duplicate:
        owned.append(item_id)
    store.update_user(me, {"last_gacha": today_jst(), "items": json.dumps(owned)})
    return jsonify(id=item_id, duplicate=duplicate, **gacha.ITEMS[item_id])


@app.route("/gacha/equip", methods=["POST"])
@login_required
def gacha_equip():
    me = current_user()
    item_id = request.form.get("item", "")
    kind = request.form.get("kind", "")
    if kind not in ("frame", "button"):
        abort(400)
    if item_id:  # 空なら外す
        item = gacha.ITEMS.get(item_id)
        if not item or item["kind"] != kind or item_id not in owned_items(store.get_user(me)):
            abort(400)
    store.update_user(me, {f"equipped_{kind}": item_id})
    return redirect(url_for("gacha_page"))


# パソコンで試すときだけ使う（Azure では Blob Storage の URL を使う）
@app.route("/local-media/<path:name>")
def local_media(name):
    if not isinstance(store, LocalStore):
        abort(404)
    return send_from_directory(store.media_dir, name)


@app.errorhandler(413)
def too_large(_):
    flash("ファイルが大きすぎるよ（50MB まで）")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
