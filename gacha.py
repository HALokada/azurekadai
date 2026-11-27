"""ドーパミンガチャの景品と確率。"""
import random

# レア度ごとの確率（合計 100）
RARITIES = [
    ("N", 50),
    ("R", 30),
    ("SR", 15),
    ("SSR", 4.5),
    ("UR", 0.5),
]

# 景品：id は CSS のクラス名にもなる
# kind = frame（アイコンの枠） / button（自分が押すドーパミンボタンの色）
ITEMS = {
    "frame_silver":  {"kind": "frame",  "rarity": "N",   "name": "シルバー枠"},
    "button_ice":    {"kind": "button", "rarity": "N",   "name": "アイスボタン"},
    "frame_neon":    {"kind": "frame",  "rarity": "R",   "name": "ネオン枠"},
    "button_toxic":  {"kind": "button", "rarity": "R",   "name": "トキシックボタン"},
    "frame_fire":    {"kind": "frame",  "rarity": "SR",  "name": "ファイア枠"},
    "button_gold":   {"kind": "button", "rarity": "SR",  "name": "ゴールドボタン"},
    "frame_rainbow": {"kind": "frame",  "rarity": "SSR", "name": "レインボー枠"},
    "button_rainbow": {"kind": "button", "rarity": "SSR", "name": "レインボーボタン"},
    "frame_galaxy":  {"kind": "frame",  "rarity": "UR",  "name": "銀河枠"},
}


def draw():
    """ガチャを 1 回引いて景品の id を返す。"""
    rarity = random.choices([r for r, _ in RARITIES], weights=[w for _, w in RARITIES])[0]
    return random.choice([i for i, item in ITEMS.items() if item["rarity"] == rarity])
