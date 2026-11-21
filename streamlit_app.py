import streamlit as st
import pandas as pd
import math
from pathlib import Path

from datetime import date
from difflib import SequenceMatcher
import json
import re
import os

from datetime import date
from difflib import SequenceMatcher
import json
import os
import re
import pandas as pd
import streamlit as st

# ==========================================
# CampusMatch V5 - Streamlit 網頁版
# 校園失物招領智慧媒合系統
# ==========================================

st.set_page_config(
    page_title="CampusMatch V5 校園失物招領系統",
    page_icon="🔍",
    layout="wide",
)

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

FEATURE_NAMES = {
    "name": "物品名稱",
    "category": "物品類別",
    "color": "物品顏色",
    "location": "地點",
    "date": "日期",
    "description": "物品描述",
}


# ==========================================
# 第一組：文字與日期處理模組
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
# ==========================================

def match_items(lost, found):
    """依照雙方都有提供的特徵計算媒合分數。"""
    features = {
        "name": text_similarity(lost.get("name"), found.get("name")),
        "category": (
            float(lost["category"] == found["category"])
            if lost.get("category") and found.get("category")
            else None
        ),
        "color": text_similarity(lost.get("color"), found.get("color")),
        "location": text_similarity(lost.get("location"), found.get("location")),
        "date": date_similarity(lost.get("date"), found.get("date")),
        "description": text_similarity(lost.get("description"), found.get("description")),
    }

    available_weight = sum(
        WEIGHTS[key] for key, value in features.items() if value is not None
    )

    if available_weight == 0:
        return 0, ["沒有足夠資料進行比對"], features

    raw_score = sum(
        WEIGHTS[key] * value for key, value in features.items() if value is not None
    ) / available_weight

    reliable_features = sum(value is not None for value in features.values())
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


def get_match_results(lost, candidates):
    """計算並排序所有達到門檻的媒合結果。"""
    open_candidates = [
        item for item in candidates if item.get("status") == "open"
    ]

    results = []
    for found in open_candidates:
        score, reasons, features = match_items(lost, found)
        if score >= MIN_SCORE:
            results.append({
                "item": found,
                "score": score,
                "reasons": reasons,
                "features": features,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results, len(open_candidates)


def render_matches_ui(lost, candidates):
    """在網頁上呈現智慧媒合結果。"""
    st.subheader("智慧媒合結果")
    results, open_count = get_match_results(lost, candidates)

    if open_count == 0:
        st.info("目前沒有開放中的拾獲物可以比對。")
        return

    if not results:
        st.warning(f"目前沒有達到 {MIN_SCORE} 分的媒合結果。")
        return

    for rank, result in enumerate(results, 1):
        found = result["item"]
        score = result["score"]

        if score >= 80:
            verdict = "高度符合，建議優先人工確認"
            badge = "🟢"
        elif score >= 60:
            verdict = "可能符合，建議進一步確認"
            badge = "🟡"
        else:
            verdict = "部分特徵相似"
            badge = "🟠"

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"### {badge} 第 {rank} 名：{found['name']}")
                st.write(
                    f"**類別：** {found['category']} ｜ "
                    f"**顏色：** {found.get('color') or '未提供'} ｜ "
                    f"**地點：** {found['location']} ｜ "
                    f"**日期：** {found['date']}"
                )
                if found.get("description"):
                    st.write(f"**描述：** {found['description']}")
                st.write("**推薦理由：** " + "、".join(result["reasons"]))

            with col2:
                st.metric("相似度分數", f"{score} / 100")
                st.caption(verdict)

            with st.expander("查看各項特徵比對明細"):
                detail_rows = [
                    {
                        "特徵項目": FEATURE_NAMES[key],
                        "相似度": "未提供" if val is None else f"{val * 100:.1f}%",
                    }
                    for key, val in result["features"].items()
                ]
                st.table(pd.DataFrame(detail_rows))

    st.caption("提醒：媒合分數僅供參考，仍須人工確認。")


# ==========================================
# 第三組：資料讀寫與驗證模組
# ==========================================

def is_duplicate(item, items):
    """檢查是否已經有相同資料。"""
    fields = ["name", "category", "color", "location", "date", "description"]
    return any(
        all(
            normalize_text(existing.get(key, "")) == normalize_text(item.get(key, ""))
            for key in fields
        )
        for existing in items
    )


def load_data():
    """從 JSON 載入資料，並回傳 (found_items, lost_items, error_msg)。"""
    if not os.path.exists(DATA_FILE):
        return [], [], None

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("資料格式錯誤")

        found = data.get("found_items", [])
        lost = data.get("lost_items", [])

        if not isinstance(found, list) or not isinstance(lost, list):
            raise ValueError("物品清單格式錯誤")

        required_fields = {
            "name", "category", "color",
            "location", "date", "description", "status"
        }

        for item in found + lost:
            if (
                not isinstance(item, dict)
                or not required_fields.issubset(item)
                or not all(isinstance(item[key], str) for key in required_fields)
            ):
                raise ValueError("物品資料格式錯誤")

            valid_statuses = {"open", "claimed", "closed"} if item in found else {"open", "closed"}
            if item["status"] not in valid_statuses:
                raise ValueError("物品狀態錯誤")

            parse_date(item["date"])

        return found, lost, None

    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return [], [], f"資料載入失敗：{exc}（請檢查 {DATA_FILE}，避免覆蓋原始資料）"


def save_data(found_items, lost_items):
    """將資料保存至 JSON 檔案。"""
    data = {
        "found_items": found_items,
        "lost_items": lost_items,
    }
    temp_file = DATA_FILE + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        os.replace(temp_file, DATA_FILE)
        return True, None
    except OSError as exc:
        return False, f"資料儲存失敗：{exc}"


def render_item_form(kind):
    """渲染登記表單並回傳驗證後的物品字典（未送出或驗證失敗回傳 None）。"""
    title = "登記撿到的物品（拾獲物）" if kind == "found" else "登記遺失的物品（遺失物）"
    st.subheader(title)

    with st.form(key=f"form_{kind}", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("物品名稱 *", max_chars=MAX_TEXT_LENGTH, placeholder="例如：黑色摺疊傘、AirPods Pro")
            category = st.selectbox("物品類別 *", CATEGORIES)
            color = st.text_input("物品顏色（選填）", max_chars=MAX_TEXT_LENGTH, placeholder="例如：黑色、銀白色")
        with col2:
            location = st.text_input("遺失／拾獲地點 *", max_chars=MAX_TEXT_LENGTH, placeholder="例如：圖書館二樓、學餐")
            item_date = st.date_input("日期 *", value=date.today(), max_value=date.today())
            description = st.text_area("其他特徵或描述（選填）", max_chars=MAX_TEXT_LENGTH, height=68)

        submitted = st.form_submit_button("送出登記", type="primary")

    if not submitted:
        return None

    name_clean = name.strip()
    location_clean = location.strip()
    color_clean = color.strip()
    desc_clean = description.strip()

    if not name_clean:
        st.error("「物品名稱」不能空白。")
        return None
    if not location_clean:
        st.error("「遺失／拾獲地點」不能空白。")
        return None

    date_str = item_date.isoformat()
    try:
        parse_date(date_str)
    except ValueError as exc:
        st.error(f"日期錯誤：{exc}")
        return None

    return {
        "name": name_clean,
        "category": category,
        "color": color_clean,
        "location": location_clean,
        "date": date_str,
        "description": desc_clean,
        "status": "open",
    }


def render_items_table(items, empty_msg):
    """以網頁表格顯示物品清單。"""
    if not items:
        st.info(empty_msg)
        return

    status_filter = st.selectbox(
        "篩選狀態",
        ["全部", "open（尚未領回／尋找中）", "claimed（已領回）", "closed（已結案）"],
        key=f"filter_{empty_msg}",
    )

    filtered = items
    if status_filter != "全部":
        target_status = status_filter.split("（")[0]
        filtered = [item for item in items if item.get("status") == target_status]

    if not filtered:
        st.info("目前沒有符合該狀態的資料。")
        return

    rows = []
    for idx, item in enumerate(filtered, 1):
        rows.append({
            "編號": idx,
            "物品名稱": item.get("name", "未命名"),
            "類別": item.get("category", "未分類"),
            "顏色": item.get("color") or "未提供",
            "地點": item.get("location", "未提供"),
            "日期": item.get("date", "未提供"),
            "描述": item.get("description") or "無",
            "狀態": item.get("status", "open"),
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ==========================================
# 第四組：主程式與網頁介面整合
# ==========================================

def main():
    st.title("🔍 CampusMatch V5 校園失物招領智慧媒合系統")

    found_items, lost_items, load_err = load_data()
    if load_err:
        st.error(load_err)

    # 側邊欄導覽與即時統計
    with st.sidebar:
        st.header("功能選單")
        menu = st.radio(
            "請選擇操作項目：",
            [
                "1. 登記撿到的物品",
                "2. 登記遺失的物品並立即媒合",
                "3. 查看所有拾獲物",
                "4. 查看所有遺失物",
                "5. 修改拾獲物狀態",
                "6. 刪除拾獲物",
                "7. 刪除遺失物",
                "8. 重新比對現有遺失物",
            ],
        )
        st.divider()
        open_found = sum(1 for i in found_items if i.get("status") == "open")
        open_lost = sum(1 for i in lost_items if i.get("status") == "open")
        st.metric("開放中拾獲物", f"{open_found} 筆")
        st.metric("尋找中遺失物", f"{open_lost} 筆")

    # 1. 登記撿到的物品
    if menu == "1. 登記撿到的物品":
        item = render_item_form("found")
        if item:
            if is_duplicate(item, found_items):
                st.warning("發現重複的拾獲物資料，已取消登記。")
            else:
                found_items.append(item)
                ok, err = save_data(found_items, lost_items)
                if ok:
                    st.success("拾獲物登記成功！")
                    open_lost_list = [l for l in lost_items if l.get("status") == "open"]
                    if open_lost_list:
                        st.divider()
                        st.subheader("自動比對現有尋找中的遺失物")
                        for lost in open_lost_list:
                            st.markdown(f"#### 比對遺失物：{lost['name']}（{lost['date']} @ {lost['location']}）")
                            render_matches_ui(lost, [item])
                else:
                    st.error(err)

    # 2. 登記遺失的物品並立即媒合
    elif menu == "2. 登記遺失的物品並立即媒合":
        item = render_item_form("lost")
        if item:
            if is_duplicate(item, lost_items):
                st.warning("發現重複的遺失物資料，已取消登記。")
            else:
                lost_items.append(item)
                ok, err = save_data(found_items, lost_items)
                if ok:
                    st.success("遺失物登記成功！")
                    st.divider()
                    render_matches_ui(item, found_items)
                else:
                    st.error(err)

    # 3. 查看所有拾獲物
    elif menu == "3. 查看所有拾獲物":
        st.subheader("所有拾獲物清單")
        render_items_table(found_items, "目前沒有任何拾獲物資料。")

    # 4. 查看所有遺失物
    elif menu == "4. 查看所有遺失物":
        st.subheader("所有遺失物清單")
        render_items_table(lost_items, "目前沒有任何遺失物資料。")

    # 5. 修改拾獲物狀態
    elif menu == "5. 修改拾獲物狀態":
        st.subheader("修改拾獲物狀態")
        if not found_items:
            st.info("目前沒有拾獲物資料可修改。")
        else:
            options = [
                f"{i + 1}. {item['name']}（{item['category']}｜{item['location']}｜目前狀態：{item['status']}）"
                for i, item in enumerate(found_items)
            ]
            selected = st.selectbox("選擇要修改的拾獲物", options)
            idx = options.index(selected)

            status_labels = {
                "open": "open（尚未領回）",
                "claimed": "claimed（已經領回）",
                "closed": "closed（已結案）",
            }
            new_status = st.selectbox(
                "選擇新狀態",
                list(status_labels.keys()),
                index=list(status_labels.keys()).index(found_items[idx]["status"]),
                format_func=lambda k: status_labels[k],
            )

            if st.button("更新狀態", type="primary"):
                found_items[idx]["status"] = new_status
                ok, err = save_data(found_items, lost_items)
                if ok:
                    st.success("物品狀態更新成功！")
                    st.rerun()
                else:
                    st.error(err)

    # 6. 刪除拾獲物
    elif menu == "6. 刪除拾獲物":
        st.subheader("刪除拾獲物")
        if not found_items:
            st.info("目前沒有拾獲物資料可刪除。")
        else:
            options = [
                f"{i + 1}. {item['name']}（{item['category']}｜{item['location']}｜{item['date']}）"
                for i, item in enumerate(found_items)
            ]
            selected = st.selectbox("選擇要刪除的拾獲物", options)
            idx = options.index(selected)

            confirm = st.checkbox("我確定要永久刪除此筆拾獲物資料")
            if st.button("確認刪除拾獲物", type="primary", disabled=not confirm):
                found_items.pop(idx)
                ok, err = save_data(found_items, lost_items)
                if ok:
                    st.success("拾獲物資料刪除成功！")
                    st.rerun()
                else:
                    st.error(err)

    # 7. 刪除遺失物
    elif menu == "7. 刪除遺失物":
        st.subheader("刪除遺失物")
        if not lost_items:
            st.info("目前沒有遺失物資料可刪除。")
        else:
            options = [
                f"{i + 1}. {item['name']}（{item['category']}｜{item['location']}｜{item['date']}）"
                for i, item in enumerate(lost_items)
            ]
            selected = st.selectbox("選擇要刪除的遺失物", options)
            idx = options.index(selected)

            confirm = st.checkbox("我確定要永久刪除此筆遺失物資料")
            if st.button("確認刪除遺失物", type="primary", disabled=not confirm):
                lost_items.pop(idx)
                ok, err = save_data(found_items, lost_items)
                if ok:
                    st.success("遺失物資料刪除成功！")
                    st.rerun()
                else:
                    st.error(err)

    # 8. 重新比對現有遺失物（方便隨時查看媒合結果）
    elif menu == "8. 重新比對現有遺失物":
        st.subheader("選擇已登記的遺失物進行比對")
        if not lost_items:
            st.info("目前沒有任何遺失物資料。")
        else:
            options = [
                f"{i + 1}. {item['name']}（{item['category']}｜{item['location']}｜{item['date']}）"
                for i, item in enumerate(lost_items)
            ]
            selected = st.selectbox("選擇遺失物", options)
            idx = options.index(selected)
            render_matches_ui(lost_items[idx], found_items)


if __name__ == "__main__":
    main()