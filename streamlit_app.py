from datetime import date
from difflib import SequenceMatcher
import json
import re
import os

# ==========================================
# CampusMatch V5
# 校園失物招領智慧媒合系統
# ==========================================

DATA_FILE = "campusmatch.json"
MIN_SCORE = 40
MAX_TEXT_LENGTH = 100

WEIGHTS = {
    "name": 0.25,
    "category": 0.20,
    "color": 0.15,
    "location": 0.15,
    "date": 0.10,
    "description": 0.15,
}

CATEGORIES = [
    "電子產品", "證件", "文具",
    "衣物", "水壺", "雨傘", "其他"
]

LABELS = {
    "name": "物品名稱相似",
    "category": "物品類別相同",
    "color": "顏色相近",
    "location": "地點相近",
    "date": "拾獲與遺失日期接近",
    "description": "物品描述相似",
}

found_items = []
lost_items = []


# ==========================================
# 第一組：文字與日期處理模組
# 負責：鄭騏皓
# ==========================================

def normalize_text(value):
    """標準化文字並移除空白。"""
    if not isinstance(value, str):
        return ""

    return re.sub(r"\s+", "", value.strip().casefold())


def text_similarity(a, b):
    """缺失資料回傳 None，不列入權重計算。"""
    a = normalize_text(a)
    b = normalize_text(b)

    if not a or not b:
        return None

    if a == b:
        return 1.0

    if a in b or b in a:
        return 0.9

    return SequenceMatcher(None, a, b).ratio()


def parse_date(value):
    """嚴格驗證 YYYY-MM-DD 日期格式。"""
    if not isinstance(value, str):
        raise ValueError("日期必須是 YYYY-MM-DD 格式")

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("日期格式必須是 YYYY-MM-DD")

    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期不存在") from exc

    if parsed.isoformat() != value:
        raise ValueError("日期格式不正確")

    if parsed > date.today():
        raise ValueError("日期不能晚於今天")

    return parsed


def date_similarity(a, b):
    try:
        d1 = parse_date(a)
        d2 = parse_date(b)
    except (ValueError, TypeError):
        return None

    days = abs((d1 - d2).days)
    return max(0.0, 1.0 - days / 30.0)


# ==========================================
# 第二組：智慧媒合模組
# 負責：林奕杰
# ==========================================

def match_items(lost, found):
    """依照雙方都有提供的特徵計算媒合分數。"""

    features = {
        "name": text_similarity(
            lost.get("name"), found.get("name")
        ),

        "category": (
            float(lost["category"] == found["category"])
            if lost.get("category") and found.get("category")
            else None
        ),

        "color": text_similarity(
            lost.get("color"), found.get("color")
        ),

        "location": text_similarity(
            lost.get("location"), found.get("location")
        ),

        "date": date_similarity(
            lost.get("date"), found.get("date")
        ),

        "description": text_similarity(
            lost.get("description"), found.get("description")
        ),
    }

    available_weight = sum(
        WEIGHTS[key]
        for key, value in features.items()
        if value is not None
    )

    if available_weight == 0:
        return 0, ["沒有足夠資料進行比對"], features

    raw_score = sum(
        WEIGHTS[key] * value
        for key, value in features.items()
        if value is not None
    ) / available_weight

    # 少於三項有效特徵時，限制最高分數
    reliable_features = sum(
        value is not None for value in features.values()
    )

    if reliable_features < 3:
        raw_score = min(raw_score, 0.49)

    score = round(raw_score * 100)

    reasons = [
        LABELS[key]
        for key, value in features.items()
        if value is not None and value >= 0.65
    ]

    if not reasons:
        reasons = ["沒有明顯相符特徵，建議人工確認"]

    return score, reasons, features


def show_matches(lost, candidates=None):
    """顯示遺失物與開放中拾獲物的媒合結果。"""

    if candidates is None:
        candidates = found_items

    candidates = [
        item for item in candidates
        if item.get("status") == "open"
    ]

    print("\n" + "=" * 45)
    print("智慧媒合結果")
    print("=" * 45)

    if not candidates:
        print("目前沒有開放中的拾獲物可以比對。")
        return

    results = []

    for found in candidates:
        score, reasons, features = match_items(lost, found)

        # 排除低於最低推薦分數的結果
        if score < MIN_SCORE:
            continue

        results.append({
            "item": found,
            "score": score,
            "reasons": reasons,
            "features": features,
        })

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    if not results:
        print(f"目前沒有達到 {MIN_SCORE} 分的媒合結果。")
        return

    for rank, result in enumerate(results, 1):
        found = result["item"]
        score = result["score"]

        if score >= 80:
            verdict = "高度符合，建議優先人工確認"
        elif score >= 60:
            verdict = "可能符合，建議進一步確認"
        else:
            verdict = "部分特徵相似"

        print(f"\n第 {rank} 名：{found['name']}")
        print(f"類別：{found['category']}")
        print(f"顏色：{found.get('color') or '未提供'}")
        print(f"地點：{found['location']}")
        print(f"日期：{found['date']}")
        print(f"相似度分數：{score}/100")
        print(f"媒合判斷：{verdict}")

        print("推薦理由：")
        for reason in result["reasons"]:
            print("  -", reason)

        print("各項特徵分數：")

        for key, value in result["features"].items():
            display = (
                "未提供"
                if value is None
                else f"{value * 100:.1f}%"
            )
            print(f"  {key}: {display}")

    print("\n提醒：媒合分數僅供參考，仍須人工確認。")


# ==========================================
# 第三組：使用者操作與顯示模組
# 負責：張駿莛
# ==========================================

def input_text(prompt, required=False):
    """限制輸入長度及處理空白資料。"""

    while True:
        value = input(prompt).strip()

        if required and not value:
            print("此欄位不能空白。")
            continue

        if len(value) > MAX_TEXT_LENGTH:
            print(f"輸入不可超過 {MAX_TEXT_LENGTH} 個字元。")
            continue

        return value


def input_item(kind):
    print("\n" + "=" * 45)
    print(
        "【登記撿到的物品】"
        if kind == "found"
        else "【登記遺失的物品】"
    )
    print("=" * 45)

    name = input_text("物品名稱：", required=True)

    print("\n物品類別：")

    for i, category in enumerate(CATEGORIES, 1):
        print(f"{i}. {category}")

    while True:
        choice = input("請輸入類別編號（1-7）：").strip()

        if choice.isdigit() and 1 <= int(choice) <= 7:
            category = CATEGORIES[int(choice) - 1]
            break

        print("輸入錯誤，請輸入 1 到 7。")

    color = input_text(
        "物品顏色（不知道可直接 Enter）："
    )

    location = input_text(
        "遺失／拾獲地點：",
        required=True
    )

    while True:
        item_date = input("日期（YYYY-MM-DD）：").strip()

        try:
            parse_date(item_date)
            break
        except ValueError as exc:
            print("日期錯誤：", exc)

    description = input_text(
        "其他特徵或描述："
    )

    return {
        "name": name,
        "category": category,
        "color": color,
        "location": location,
        "date": item_date,
        "description": description,
        "status": "open",
    }


def is_duplicate(item, items):
    """檢查是否已經有相同資料。"""

    fields = [
        "name", "category", "color",
        "location", "date", "description"
    ]

    return any(
        all(
            normalize_text(existing.get(key, "")) ==
            normalize_text(item.get(key, ""))
            for key in fields
        )
        for existing in items
    )


def list_items(items, title):
    print(f"\n【{title}】")

    if not items:
        print("目前沒有資料。")
        return

    for i, item in enumerate(items, 1):
        print(
            f"{i}. {item.get('name', '未命名')} | "
            f"{item.get('category', '未分類')} | "
            f"{item.get('color') or '未提供'} | "
            f"{item.get('location', '未提供')} | "
            f"{item.get('date', '未提供')} | "
            f"狀態：{item.get('status', 'open')}"
        )


def update_found_status():
    """管理拾獲物領回及結案狀態。"""

    list_items(found_items, "所有拾獲物")

    if not found_items:
        return

    choice = input("請輸入要修改的拾獲物編號：").strip()

    if not choice.isdigit():
        print("編號錯誤。")
        return

    index = int(choice) - 1

    if not 0 <= index < len(found_items):
        print("找不到該筆資料。")
        return

    print("1. open（尚未領回）")
    print("2. claimed（已經領回）")
    print("3. closed（已結案）")

    status_choice = input("請選擇新狀態：").strip()

    status_map = {
        "1": "open",
        "2": "claimed",
        "3": "closed",
    }

    if status_choice not in status_map:
        print("狀態選擇錯誤。")
        return

    found_items[index]["status"] = status_map[status_choice]

    save_data()
    print("物品狀態更新成功！")


def delete_item(items, title):
    """刪除指定物品資料。"""

    list_items(items, title)

    if not items:
        return

    choice = input("請輸入要刪除的編號：").strip()

    if not choice.isdigit():
        print("編號錯誤。")
        return

    index = int(choice) - 1

    if not 0 <= index < len(items):
        print("找不到該筆資料。")
        return

    confirm = input("確定要刪除嗎？(y/n)：").strip().lower()

    if confirm == "y":
        items.pop(index)
        save_data()
        print("資料刪除成功！")
    else:
        print("已取消刪除。")


# ==========================================
# 第四組：主程式與系統整合模組
# 負責：王柏倫
# ==========================================

def load_data():
    """從 JSON 載入資料。"""

    global found_items, lost_items

    if not os.path.exists(DATA_FILE):
        found_items = []
        lost_items = []
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("資料格式錯誤")

        found = data.get("found_items", [])
        lost = data.get("lost_items", [])

        if not isinstance(found, list) or not isinstance(lost, list):
            raise ValueError("物品清單格式錯誤")

        # 避免載入不完整或格式錯誤的資料
        required_fields = {
            "name", "category", "color",
            "location", "date", "description", "status"
        }

        for item in found + lost:
            if (
                not isinstance(item, dict)
                or not required_fields.issubset(item)
                or not all(
                    isinstance(item[key], str)
                    for key in required_fields
                )
            ):
                raise ValueError("物品資料格式錯誤")

            if item["status"] not in (
                {"open", "claimed", "closed"}
                if item in found
                else {"open", "closed"}
            ):
                raise ValueError("物品狀態錯誤")

            parse_date(item["date"])

        found_items = found
        lost_items = lost

        print("資料載入成功！")

    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print("資料載入失敗：", exc)
        print("請檢查 JSON 檔案，避免覆蓋原始資料。")
        found_items = []
        lost_items = []


def save_data():
    """將資料保存至 JSON 檔案。"""

    data = {
        "found_items": found_items,
        "lost_items": lost_items,
    }

    temp_file = DATA_FILE + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=4
            )

        os.replace(temp_file, DATA_FILE)

    except OSError as exc:
        print("資料儲存失敗：", exc)


def main():
    load_data()

    print("=" * 50)
    print("CampusMatch V5 校園失物招領智慧媒合系統")
    print("=" * 50)

    while True:
        print("\n請選擇功能：")
        print("1. 登記撿到的物品")
        print("2. 登記遺失的物品並立即媒合")
        print("3. 查看所有拾獲物")
        print("4. 查看所有遺失物")
        print("5. 修改拾獲物狀態")
        print("6. 刪除拾獲物")
        print("7. 刪除遺失物")
        print("8. 結束系統")

        choice = input("請輸入選項（1-8）：").strip()

        if choice == "1":
            item = input_item("found")

            if is_duplicate(item, found_items):
                print("發現重複的拾獲物資料，取消登記。")
                continue

            found_items.append(item)
            save_data()

            print("\n拾獲物登記成功！")

            # 只比對新拾獲物與尚未結案的遺失物
            for lost in lost_items:
                if lost.get("status") == "open":
                    print(f"\n比對遺失物：{lost['name']}")
                    show_matches(lost, [item])

        elif choice == "2":
            item = input_item("lost")

            if is_duplicate(item, lost_items):
                print("發現重複的遺失物資料，取消登記。")
                continue

            lost_items.append(item)
            save_data()

            print("\n遺失物登記成功！")
            show_matches(item)

        elif choice == "3":
            list_items(found_items, "所有拾獲物")

        elif choice == "4":
            list_items(lost_items, "所有遺失物")

        elif choice == "5":
            update_found_status()

        elif choice == "6":
            delete_item(found_items, "所有拾獲物")

        elif choice == "7":
            delete_item(lost_items, "所有遺失物")

        elif choice == "8":
            save_data()
            print("\n感謝使用 CampusMatch V5！")
            break

        else:
            print("選項錯誤，請輸入 1 到 8。")


if __name__ == "__main__":
    main()

