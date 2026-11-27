"""激熱ドパガキ掲示板（Flask）"""
import os
import re
import uuid
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from storage import LocalStore, get_store, new_post_key, now_iso

app = Flask(__name__)
# セッション（ログイン状態）の暗号化キー。Azure では環境変数 SECRET_KEY に入れる。
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # アップロードは 50MB まで

store = get_store()

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
    for p in posts:
        p["id"] = p["RowKey"]
        p["media_src"] = store.media_url(p["media_blob"]) if p.get("media_blob") else None
        p["liked"] = p["id"] in liked
        p["dopamine"] = int(p.get("dopamine", 0))
    return posts


@app.context_processor
def inject_user():
    return {"me": current_user()}


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
