from datetime import date, datetime
from difflib import SequenceMatcher
import json
import os
import re
import shutil
import uuid

# ============================================================
# CampusMatch V6.1
# 校園失物招領智慧媒合系統
# ============================================================

DATA_FILE = "campusmatch.json"
BACKUP_FILE = "campusmatch.backup.json"
TEMP_FILE = DATA_FILE + ".tmp"

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
    "電子產品",
    "證件",
    "文具",
    "衣物",
    "水壺",
    "雨傘",
    "其他"
]

LABELS = {
    "name": "物品名稱相似",
    "category": "物品類別相同",
    "color": "顏色相近",
    "location": "地點相近",
    "date": "日期接近",
    "description": "物品描述相似",
}

FOUND_STATUSES = ["open", "claimed", "closed"]
LOST_STATUSES = ["open", "closed"]

STATUS_LABELS = {
    "open": "處理中",
    "claimed": "已領回",
    "closed": "已結案",
}

# 全域資料
found_items = []
lost_items = []
data_loaded = False


# ============================================================
# 第一組：文字與日期處理模組
# 負責：鄭騏皓
# ============================================================

def normalize_text(value):
    """標準化文字並移除空白。"""

    if not isinstance(value, str):
        return ""

    return re.sub(r"\s+", "", value.strip().casefold())


def text_similarity(a, b):
    """計算兩段文字的相似度。"""

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
    """計算日期接近程度。"""

    try:
        d1 = parse_date(a)
        d2 = parse_date(b)

    except (ValueError, TypeError):
        return None

    days = abs((d1 - d2).days)

    return max(0.0, 1.0 - days / 30.0)


def generate_item_id():
    """產生唯一物品編號。"""

    return "ITEM-" + uuid.uuid4().hex[:10].upper()


def current_time():
    """取得目前時間。"""

    return datetime.now().isoformat(timespec="seconds")


# ============================================================
# 第二組：智慧媒合模組
# 負責：林奕杰
# 功能：特徵比對、分數計算、推薦排序
# ============================================================

def match_items(lost, found):
    """
    根據雙方都有提供的特徵計算相似度。

    回傳：
    score：媒合分數
    reasons：推薦理由
    features：各項特徵分數
    reliable_features：有效特徵數量
    """

    features = {
        "name": text_similarity(
            lost.get("name"),
            found.get("name")
        ),

        "category": (
            float(lost["category"] == found["category"])
            if lost.get("category") and found.get("category")
            else None
        ),

        "color": text_similarity(
            lost.get("color"),
            found.get("color")
        ),

        "location": text_similarity(
            lost.get("location"),
            found.get("location")
        ),

        "date": date_similarity(
            lost.get("date"),
            found.get("date")
        ),

        "description": text_similarity(
            lost.get("description"),
            found.get("description")
        ),
    }

    # 計算有效特徵的總權重
    available_weight = sum(
        WEIGHTS[key]
        for key, value in features.items()
        if value is not None
    )

    # 沒有足夠資料
    if available_weight == 0:
        return (
            0,
            ["沒有足夠資料進行比對"],
            features,
            0
        )

    # 計算加權平均分數
    raw_score = sum(
        WEIGHTS[key] * value
        for key, value in features.items()
        if value is not None
    ) / available_weight

    # 計算有效特徵數量
    reliable_features = sum(
        value is not None
        for value in features.values()
    )

    # 有效特徵少於三項時限制最高分數
    if reliable_features < 3:
        raw_score = min(raw_score, 0.49)

    score = round(raw_score * 100)

    # 產生推薦理由
    reasons = [
        LABELS[key]
        for key, value in features.items()
        if value is not None and value >= 0.65
    ]

    if not reasons:
        reasons = [
            "沒有明顯相符特徵，建議人工確認"
        ]

    return (
        score,
        reasons,
        features,
        reliable_features
    )


def get_match_results(lost, candidates=None):
    """
    取得符合條件的媒合結果。

    只推薦 status 為 open 的拾獲物。
    並依照分數由高至低排序。
    """

    if candidates is None:
        candidates = found_items

    results = []

    for found in candidates:

        # 排除已領回或已結案的物品
        if found.get("status") != "open":
            continue

        score, reasons, features, count = match_items(
            lost,
            found
        )

        # 排除低於最低推薦分數的結果
        if score < MIN_SCORE:
            continue

        results.append({
            "item": found,
            "score": score,
            "reasons": reasons,
            "features": features,
            "feature_count": count,
        })

    # 分數高的排在前面
    results.sort(
        key=lambda result: result["score"],
        reverse=True
    )

    return results


def show_matches(lost, candidates=None):
    """
    顯示智慧媒合結果。

    包含：
    1. 物品基本資訊
    2. 相似度分數
    3. 媒合判斷
    4. 推薦理由
    5. 各項特徵分數
    """

    results = get_match_results(
        lost,
        candidates
    )

    print("\n" + "=" * 55)
    print("                 智慧媒合結果")
    print("=" * 55)

    if not results:

        print("目前沒有符合推薦條件的拾獲物。")
        print("建議確認資料，或稍後再次搜尋。")

        return

    print(f"找到 {len(results)} 筆可能符合的資料。")

    for rank, result in enumerate(results, 1):

        found = result["item"]
        score = result["score"]

        # 判斷媒合程度
        if score >= 80:
            verdict = "高度符合"

        elif score >= 60:
            verdict = "可能符合"

        else:
            verdict = "部分符合"

        # 判斷資料完整度
        if result["feature_count"] >= 5:
            completeness = "資料完整度高"

        elif result["feature_count"] >= 3:
            completeness = "資料完整度一般"

        else:
            completeness = "資料不足"

        print("\n" + "-" * 55)

        print(f"第 {rank} 名：{found['name']}")

        print(
            f"物品編號："
            f"{found.get('item_id', '無')}"
        )

        print(f"類別：{found['category']}")

        print(
            f"顏色："
            f"{found.get('color') or '未提供'}"
        )

        print(f"地點：{found['location']}")
        print(f"日期：{found['date']}")

        print("\n【媒合分析】")

        print(f"相似度：{score}/100")
        print(f"媒合判斷：{verdict}")
        print(f"資料完整度：{completeness}")

        print(
            f"有效特徵："
            f"{result['feature_count']}/6"
        )

        print("\n【推薦理由】")

        for reason in result["reasons"]:
            print("  +", reason)

        print("\n【各項特徵分數】")

        for key, value in result["features"].items():

            display = (
                "未提供"
                if value is None
                else f"{value * 100:.1f}%"
            )

            print(
                f"  {LABELS[key]}：{display}"
            )

    print("\n" + "=" * 55)

    print(
        "提醒：媒合分數僅供參考，"
        "仍須人工確認物品是否相符。"
    )


# ============================================================
# 第二組模組結束
# ============================================================


# ============================================================
# 第三組：使用者操作與顯示模組
# 負責：張駿莛
# 功能：輸入、搜尋、修改、刪除及資料顯示
# ============================================================


def input_text(prompt, required=False):
    """
    限制使用者輸入長度及處理空白資料。
    """

    while True:

        value = input(prompt).strip()

        if required and not value:
            print("此欄位不能空白，請重新輸入。")
            continue

        if len(value) > MAX_TEXT_LENGTH:
            print(
                f"輸入不可超過 "
                f"{MAX_TEXT_LENGTH} 個字元。"
            )
            continue

        return value


def input_category():
    """
    顯示物品類別並讓使用者選擇。
    """

    print("\n【請選擇物品類別】")

    for i, category in enumerate(CATEGORIES, 1):
        print(f"{i}. {category}")

    while True:

        choice = input(
            "\n請輸入類別編號（1-7）："
        ).strip()

        if choice.isdigit():

            index = int(choice)

            if 1 <= index <= len(CATEGORIES):
                return CATEGORIES[index - 1]

        print("輸入錯誤，請輸入 1 到 7。")


def input_item(kind):
    """
    登記拾獲物或遺失物。

    kind:
        found = 拾獲物
        lost = 遺失物
    """

    print("\n" + "=" * 50)

    if kind == "found":
        print("              登記拾獲物")

    else:
        print("              登記遺失物")

    print("=" * 50)

    # 物品名稱
    name = input_text(
        "物品名稱：",
        required=True
    )

    # 物品類別
    category = input_category()

    # 顏色
    color = input_text(
        "物品顏色（不知道可直接 Enter）："
    )

    # 地點
    location = input_text(
        "遺失／拾獲地點：",
        required=True
    )

    # 日期驗證
    while True:

        item_date = input(
            "日期（YYYY-MM-DD）："
        ).strip()

        try:

            parse_date(item_date)
            break

        except ValueError as exc:

            print("日期錯誤：", exc)

    # 其他描述
    description = input_text(
        "其他特徵或描述（可空白）："
    )

    # 建立物品資料
    item = {
        "item_id": generate_item_id(),
        "name": name,
        "category": category,
        "color": color,
        "location": location,
        "date": item_date,
        "description": description,
        "status": "open",
        "created_at": current_time(),
    }

    return item


def is_duplicate(item, items):
    """
    檢查是否有完全相同的物品資料。

    避免使用者重複登記。
    """

    fields = [
        "name",
        "category",
        "color",
        "location",
        "date",
        "description"
    ]

    return any(
        all(
            normalize_text(existing.get(key, "")) ==
            normalize_text(item.get(key, ""))
            for key in fields
        )
        for existing in items
    )


def find_item(items, choice):
    """
    透過物品編號或清單序號尋找資料。
    """

    # 優先使用唯一編號搜尋
    for item in items:

        if item.get("item_id") == choice:
            return item

    # 也允許使用清單序號
    if choice.isdigit():

        index = int(choice) - 1

        if 0 <= index < len(items):
            return items[index]

    return None


def list_items(items, title):
    """
    顯示物品清單。
    """

    print("\n" + "=" * 55)
    print(f"【{title}】")
    print("=" * 55)

    if not items:

        print("目前沒有資料。")
        return

    for i, item in enumerate(items, 1):

        status = STATUS_LABELS.get(
            item.get("status"),
            "未知"
        )

        print(
            f"\n{i}. {item.get('name', '未命名')}"
        )

        print(
            f"   編號："
            f"{item.get('item_id', '無')}"
        )

        print(
            f"   類別："
            f"{item.get('category', '未分類')}"
        )

        print(
            f"   顏色："
            f"{item.get('color') or '未提供'}"
        )

        print(
            f"   地點："
            f"{item.get('location', '未提供')}"
        )

        print(
            f"   日期："
            f"{item.get('date', '未提供')}"
        )

        print(f"   狀態：{status}")


def search_items(items, title):
    """
    依照關鍵字及類別搜尋物品。
    """

    print("\n" + "=" * 50)
    print(f"【搜尋{title}】")
    print("=" * 50)

    keyword = input_text(
        "請輸入搜尋關鍵字：",
        required=True
    )

    filter_category = input(
        "\n是否依照物品類別篩選？(y/n)："
    ).strip().lower()

    selected_category = None

    if filter_category == "y":

        selected_category = input_category()

    results = []

    for item in items:

        # 搜尋範圍
        searchable = " ".join([
            item.get("name", ""),
            item.get("color", ""),
            item.get("location", ""),
            item.get("description", ""),
        ])

        # 關鍵字比對
        if (
            normalize_text(keyword)
            not in normalize_text(searchable)
        ):
            continue

        # 類別篩選
        if (
            selected_category
            and item.get("category") != selected_category
        ):
            continue

        results.append(item)

    print(f"\n搜尋完成，共找到 {len(results)} 筆資料。")

    list_items(
        results,
        "搜尋結果"
    )


def update_found_status():
    """
    修改拾獲物狀態。

    open = 尚未領回
    claimed = 已經領回
    closed = 已結案
    """

    list_items(
        found_items,
        "所有拾獲物"
    )

    if not found_items:
        return

    choice = input(
        "\n請輸入物品編號或清單序號："
    ).strip()

    item = find_item(
        found_items,
        choice
    )

    if item is None:

        print("找不到該筆資料。")
        return

    print("\n【目前物品資訊】")

    print(f"物品名稱：{item['name']}")

    print(
        f"目前狀態："
        f"{STATUS_LABELS.get(item['status'], '未知')}"
    )

    print("\n【請選擇新狀態】")

    print("1. open（尚未領回）")
    print("2. claimed（已經領回）")
    print("3. closed（已結案）")

    status_map = {
        "1": "open",
        "2": "claimed",
        "3": "closed",
    }

    status_choice = input(
        "\n請輸入選項（1-3）："
    ).strip()

    if status_choice not in status_map:

        print("狀態選擇錯誤。")
        return

    old_status = item["status"]

    new_status = status_map[status_choice]

    item["status"] = new_status

    # 儲存失敗時還原原始狀態
    if not save_data():

        item["status"] = old_status

        print("更新失敗，已還原原本狀態。")
        return

    print("\n物品狀態更新成功！")

    print(
        f"新狀態："
        f"{STATUS_LABELS[new_status]}"
    )


def delete_item(items, title):
    """
    刪除指定物品資料。

    刪除前要求使用者再次確認。
    """

    list_items(
        items,
        title
    )

    if not items:
        return

    choice = input(
        "\n請輸入物品編號或清單序號："
    ).strip()

    item = find_item(
        items,
        choice
    )

    if item is None:

        print("找不到該筆資料。")
        return

    print("\n【即將刪除的物品】")

    print(f"名稱：{item['name']}")

    print(f"編號：{item.get('item_id', '無')}")

    confirm = input(
        "\n確定要刪除這筆資料嗎？(y/n)："
    ).strip().lower()

    if confirm != "y":

        print("已取消刪除。")
        return

    # 暫時移除
    items.remove(item)

    # 儲存成功才完成刪除
    if save_data():

        print("\n資料刪除成功！")

    else:

        # 儲存失敗則還原
        items.append(item)

        print("儲存失敗，已還原原始資料。")


# ============================================================
# 第三組模組結束
# ============================================================


# ============================================================
# 第四組：資料管理模組
# 負責：王柏倫
# 功能：JSON 載入、驗證、儲存與備份
# ============================================================


def validate_item(item, item_type):
    """
    驗證單筆物品資料。

    檢查：
    1. 是否為字典
    2. 必要欄位是否存在
    3. 欄位型態是否正確
    4. 物品名稱及地點是否空白
    5. 類別是否正確
    6. 狀態是否正確
    7. 日期是否有效
    """

    required_fields = {
        "name",
        "category",
        "color",
        "location",
        "date",
        "description",
        "status"
    }

    if not isinstance(item, dict):
        raise ValueError("物品資料必須是字典")

    if not required_fields.issubset(item):
        raise ValueError("物品缺少必要欄位")

    # 驗證欄位型態
    for key in required_fields:

        if not isinstance(item[key], str):
            raise ValueError(
                f"欄位 {key} 必須是文字"
            )

    # 驗證名稱
    if not item["name"].strip():
        raise ValueError("物品名稱不能空白")

    if len(item["name"]) > MAX_TEXT_LENGTH:
        raise ValueError("物品名稱超過長度限制")

    # 驗證類別
    if item["category"] not in CATEGORIES:
        raise ValueError("物品類別錯誤")

    # 驗證地點
    if not item["location"].strip():
        raise ValueError("物品地點不能空白")

    if len(item["location"]) > MAX_TEXT_LENGTH:
        raise ValueError("物品地點超過長度限制")

    # 驗證其他文字長度
    for key in ["color", "description"]:

        if len(item[key]) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"{key} 超過長度限制"
            )

    # 驗證狀態
    allowed_status = (
        FOUND_STATUSES
        if item_type == "found"
        else LOST_STATUSES
    )

    if item["status"] not in allowed_status:
        raise ValueError("物品狀態錯誤")

    # 驗證日期
    parse_date(item["date"])

    # 舊版本資料沒有 ID 時自動補上
    if not item.get("item_id"):

        item["item_id"] = generate_item_id()

    if not isinstance(item["item_id"], str):
        raise ValueError("物品編號格式錯誤")

    if not item["item_id"].strip():
        raise ValueError("物品編號不能空白")

    # 舊版本資料沒有建立時間時自動補上
    if not item.get("created_at"):

        item["created_at"] = current_time()

    if not isinstance(item["created_at"], str):
        raise ValueError("建立時間格式錯誤")


def load_data():
    """
    從 JSON 檔案載入資料。

    如果資料格式錯誤：
    停止系統資料修改，避免覆蓋原始資料。
    """

    global found_items
    global lost_items
    global data_loaded

    # 尚無資料檔
    if not os.path.exists(DATA_FILE):

        found_items = []
        lost_items = []

        data_loaded = True

        print("\n尚無資料檔。")
        print("已建立新的空白資料庫。")

        return True

    try:

        # 讀取 JSON
        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        # 檢查最外層格式
        if not isinstance(data, dict):
            raise ValueError("資料格式錯誤")

        found = data.get("found_items", [])
        lost = data.get("lost_items", [])

        # 檢查清單格式
        if not isinstance(found, list):
            raise ValueError("拾獲物清單格式錯誤")

        if not isinstance(lost, list):
            raise ValueError("遺失物清單格式錯誤")

        # 驗證拾獲物
        for item in found:

            validate_item(
                item,
                "found"
            )

        # 驗證遺失物
        for item in lost:

            validate_item(
                item,
                "lost"
            )

        # 檢查所有物品 ID 是否重複
        all_ids = [
            item["item_id"]
            for item in found + lost
        ]

        if len(all_ids) != len(set(all_ids)):

            raise ValueError("發現重複物品編號")

        # 驗證成功後才正式更新全域資料
        found_items = found
        lost_items = lost

        data_loaded = True

        print("\n資料載入成功！")

        print(
            f"拾獲物：{len(found_items)} 筆"
        )

        print(
            f"遺失物：{len(lost_items)} 筆"
        )

        return True

    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        TypeError
    ) as exc:

        print("\n資料載入失敗：", exc)

        print(
            "系統已停止資料修改，"
            "避免覆蓋原始資料。"
        )

        data_loaded = False

        return False


def save_data():
    """
    安全儲存 JSON 資料。

    儲存流程：
    1. 檢查資料是否已成功載入
    2. 建立新的暫存檔
    3. 寫入完整 JSON
    4. 備份舊資料
    5. 將暫存檔替換成正式資料檔
    """

    if not data_loaded:

        print(
            "資料尚未成功載入，"
            "禁止儲存。"
        )

        return False

    data = {
        "found_items": found_items,
        "lost_items": lost_items,
    }

    try:

        # 第一階段：寫入暫存檔
        with open(
            TEMP_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=4
            )

            file.flush()

            os.fsync(file.fileno())

        # 第二階段：備份舊資料
        if os.path.exists(DATA_FILE):

            shutil.copy2(
                DATA_FILE,
                BACKUP_FILE
            )

        # 第三階段：替換正式檔案
        os.replace(
            TEMP_FILE,
            DATA_FILE
        )

        return True

    except OSError as exc:

        print(
            "\n資料儲存失敗：",
            exc
        )

        # 清理暫存檔
        if os.path.exists(TEMP_FILE):

            try:

                os.remove(TEMP_FILE)

            except OSError:
                pass

        return False
