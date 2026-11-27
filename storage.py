"""データの保存場所をまとめたファイル。

- Azure 上：環境変数 AZURE_STORAGE_CONNECTION_STRING があれば
  Azure Table Storage（投稿・ユーザー・いいね・フォロー）と
  Azure Blob Storage（画像・動画・音楽）に保存する。
- 自分のパソコン：環境変数がなければ local_data フォルダに保存する（テスト用）。
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

CONN_STR = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
MEDIA_CONTAINER = "media"


def new_post_key():
    """新しい投稿ほど先に並ぶように、時間を逆にしたキーを作る。"""
    inverted = 10**13 - int(time.time() * 1000)
    return f"{inverted:013d}-{uuid.uuid4().hex[:8]}"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Azure 版
# ---------------------------------------------------------------------------
class AzureStore:
    def __init__(self, conn_str):
        from azure.core.exceptions import ResourceExistsError
        from azure.data.tables import TableServiceClient
        from azure.storage.blob import BlobServiceClient

        self._tables = TableServiceClient.from_connection_string(conn_str)
        self._blobs = BlobServiceClient.from_connection_string(conn_str)
        self.users = self._tables.create_table_if_not_exists("users")
        self.posts = self._tables.create_table_if_not_exists("posts")
        self.likes = self._tables.create_table_if_not_exists("likes")
        self.follows = self._tables.create_table_if_not_exists("follows")
        self.media = self._blobs.get_container_client(MEDIA_CONTAINER)
        try:
            self.media.create_container()
        except ResourceExistsError:
            pass

    # --- ユーザー ---
    def get_user(self, name):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return dict(self.users.get_entity("user", name))
        except ResourceNotFoundError:
            return None

    def create_user(self, name, password_hash):
        self.users.create_entity({
            "PartitionKey": "user", "RowKey": name,
            "password_hash": password_hash, "created_at": now_iso(),
        })

    def update_user(self, name, fields):
        self.users.update_entity({"PartitionKey": "user", "RowKey": name, **fields}, mode="merge")

    # --- 投稿 ---
    def add_post(self, post):
        self.posts.create_entity({"PartitionKey": "post", **post})

    def get_post(self, post_id):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return dict(self.posts.get_entity("post", post_id))
        except ResourceNotFoundError:
            return None

    def list_posts(self, limit=100):
        items = self.posts.query_entities("PartitionKey eq 'post'", results_per_page=limit)
        out = []
        for e in items:
            out.append(dict(e))
            if len(out) >= limit:
                break
        return out

    def update_post(self, post):
        self.posts.update_entity({"PartitionKey": "post", **post}, mode="merge")

    def delete_post(self, post_id):
        self.posts.delete_entity("post", post_id)
        for e in list(self.likes.query_entities(f"PartitionKey eq '{post_id}'")):
            self.likes.delete_entity(e["PartitionKey"], e["RowKey"])
            self.likes.delete_entity("u_" + e["RowKey"], post_id)

    # --- いいね（ドーパミン） ---
    # likes テーブルに 2 通り保存する：投稿ごと（PK=投稿ID）と ユーザーごと（PK=u_ユーザー名）
    def has_liked(self, post_id, user):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            self.likes.get_entity(post_id, user)
            return True
        except ResourceNotFoundError:
            return False

    def add_like(self, post_id, user):
        self.likes.upsert_entity({"PartitionKey": post_id, "RowKey": user})
        self.likes.upsert_entity({"PartitionKey": "u_" + user, "RowKey": post_id})

    def remove_like(self, post_id, user):
        self.likes.delete_entity(post_id, user)
        self.likes.delete_entity("u_" + user, post_id)

    def liked_post_ids(self, user):
        return [e["RowKey"] for e in self.likes.query_entities(f"PartitionKey eq 'u_{user}'")]

    # --- フォロー ---
    def follow(self, follower, followee):
        self.follows.upsert_entity({"PartitionKey": follower, "RowKey": followee})

    def unfollow(self, follower, followee):
        self.follows.delete_entity(follower, followee)

    def following(self, follower):
        return [e["RowKey"] for e in self.follows.query_entities(f"PartitionKey eq '{follower}'")]

    def follower_count(self, name):
        return sum(1 for _ in self.follows.query_entities(f"RowKey eq '{name}'"))

    # --- ファイル（画像・動画・音楽） ---
    def save_media(self, blob_name, data, content_type):
        from azure.storage.blob import ContentSettings
        self.media.upload_blob(
            blob_name, data, overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    def delete_media(self, blob_name):
        try:
            self.media.delete_blob(blob_name)
        except Exception:
            pass

    def media_url(self, blob_name):
        """1 日だけ見られる URL（SAS）を作る。コンテナを公開しなくてよい。"""
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas
        sas = generate_blob_sas(
            account_name=self._blobs.account_name,
            container_name=MEDIA_CONTAINER,
            blob_name=blob_name,
            account_key=self._blobs.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(days=1),
        )
        return f"{self.media.url}/{blob_name}?{sas}"


# ---------------------------------------------------------------------------
# ローカル版（パソコンで試すとき用）
# ---------------------------------------------------------------------------
class LocalStore:
    def __init__(self, folder):
        self.folder = folder
        self.media_dir = os.path.join(folder, "media")
        os.makedirs(self.media_dir, exist_ok=True)
        self.path = os.path.join(folder, "db.json")
        self.lock = threading.Lock()
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.db = json.load(f)
        else:
            self.db = {"users": {}, "posts": {}, "likes": [], "follows": []}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.db, f, ensure_ascii=False, indent=1)

    def get_user(self, name):
        u = self.db["users"].get(name)
        return dict(u, RowKey=name) if u else None

    def create_user(self, name, password_hash):
        with self.lock:
            if name in self.db["users"]:
                raise ValueError("exists")
            self.db["users"][name] = {"password_hash": password_hash, "created_at": now_iso()}
            self._save()

    def update_user(self, name, fields):
        with self.lock:
            self.db["users"][name].update(fields)
            self._save()

    def add_post(self, post):
        with self.lock:
            self.db["posts"][post["RowKey"]] = post
            self._save()

    def get_post(self, post_id):
        p = self.db["posts"].get(post_id)
        return dict(p) if p else None

    def list_posts(self, limit=100):
        keys = sorted(self.db["posts"])[:limit]
        return [dict(self.db["posts"][k]) for k in keys]

    def update_post(self, post):
        with self.lock:
            self.db["posts"][post["RowKey"]].update(post)
            self._save()

    def delete_post(self, post_id):
        with self.lock:
            self.db["posts"].pop(post_id, None)
            self.db["likes"] = [l for l in self.db["likes"] if l[0] != post_id]
            self._save()

    def has_liked(self, post_id, user):
        return [post_id, user] in self.db["likes"]

    def add_like(self, post_id, user):
        with self.lock:
            if [post_id, user] not in self.db["likes"]:
                self.db["likes"].append([post_id, user])
            self._save()

    def remove_like(self, post_id, user):
        with self.lock:
            self.db["likes"] = [l for l in self.db["likes"] if l != [post_id, user]]
            self._save()

    def liked_post_ids(self, user):
        return [l[0] for l in self.db["likes"] if l[1] == user]

    def follow(self, follower, followee):
        with self.lock:
            if [follower, followee] not in self.db["follows"]:
                self.db["follows"].append([follower, followee])
            self._save()

    def unfollow(self, follower, followee):
        with self.lock:
            self.db["follows"] = [f for f in self.db["follows"] if f != [follower, followee]]
            self._save()

    def following(self, follower):
        return [f[1] for f in self.db["follows"] if f[0] == follower]

    def follower_count(self, name):
        return sum(1 for f in self.db["follows"] if f[1] == name)

    def save_media(self, blob_name, data, content_type):
        with open(os.path.join(self.media_dir, blob_name), "wb") as f:
            f.write(data)

    def delete_media(self, blob_name):
        try:
            os.remove(os.path.join(self.media_dir, blob_name))
        except OSError:
            pass

    def media_url(self, blob_name):
        return f"/local-media/{blob_name}"


def get_store():
    if CONN_STR:
        print("[storage] Azure Storage を使います", flush=True)
        return AzureStore(CONN_STR)
    # Azure 上なのに接続文字列がないときは、ログに目立つ警告を出す
    if os.environ.get("WEBSITE_SITE_NAME"):
        print("[storage] 警告: AZURE_STORAGE_CONNECTION_STRING がありません。"
              "データはデプロイのたびに消えます！", flush=True)
    return LocalStore(os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_data"))
