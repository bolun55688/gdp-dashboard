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

from datetime import date
from difflib import SequenceMatcher
import json
import os
import re
import pandas as pd
import streamlit as st

# ==========================================
# CampusMatch V5 - 精緻版 UI
# 校園失物招領智慧媒合系統
# ==========================================

st.set_page_config(
    page_title="國立彰化師範大學校園失物招領系統",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 輕量自訂樣式：美化卡片、標籤與留白
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2.5rem;
        }
        .hero-banner {
            background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
            color: #ffffff;
            padding: 1.35rem 1.6rem;
            border-radius: 14px;
            margin-bottom: 1.2rem;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.12);
        }
        .hero-banner h1 {
            color: #ffffff !important;
            font-size: 1.65rem !important;
            margin: 0 0 0.35rem 0 !important;
            padding: 0 !important;
        }
        .hero-banner p {
            color: #dbeafe;
            margin: 0;
            font-size: 0.95rem;
        }
        .badge-high {
            display: inline-block;
            background: #dcfce7;
            color: #166534;
            font-weight: 600;
            padding: 0.2rem 0.65rem;
            border-radius: 999px;
            font-size: 0.82rem;
        }
        .badge-mid {
            display: inline-block;
            background: #fef9c3;
            color: #854d0e;
            font-weight: 600;
            padding: 0.2rem 0.65rem;
            border-radius: 999px;
            font-size: 0.82rem;
        }
        .badge-low {
            display: inline-block;
            background: #ffedd5;
            color: #9a3412;
            font-weight: 600;
            padding: 0.2rem 0.65rem;
            border-radius: 999px;
            font-size: 0.82rem;
        }
        .compare-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 0.75rem 0.95rem;
            margin-top: 0.5rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
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

STATUS_LABELS = {
    "open": "開放中／尋找中",
    "claimed": "已領回",
    "closed": "已結案",
}


# ==========================================
# 第一組：文字與日期處理模組
# ==========================================

def normalize_text(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", "", value.strip().casefold())


def text_similarity(a, b):
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
# 第二組：智慧媒合與卡片渲染模組
# ==========================================

def match_items(lost, found):
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


def get_match_results(lost, candidates, min_score=MIN_SCORE):
    open_candidates = [item for item in candidates if item.get("status") == "open"]
    results = []
    for found in open_candidates:
        score, reasons, features = match_items(lost, found)
        if score >= min_score:
            results.append({
                "item": found,
                "score": score,
                "reasons": reasons,
                "features": features,
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results, len(open_candidates)


def render_matches_ui(lost, candidates, min_score=MIN_SCORE, on_claim_callback=None):
    st.subheader("🎯 智慧媒合結果")
    results, open_count = get_match_results(lost, candidates, min_score=min_score)

    if open_count == 0:
        st.info("目前沒有開放中的拾獲物可以比對。")
        return

    if not results:
        st.warning(f"目前沒有達到 {min_score} 分的媒合結果，可嘗試調低分數門檻或補充物品描述。")
        return

    for rank, result in enumerate(results, 1):
        found = result["item"]
        score = result["score"]

        if score >= 80:
            badge_html = '<span class="badge-high">高度符合・建議優先確認</span>'
        elif score >= 60:
            badge_html = '<span class="badge-mid">可能符合・建議進一步核對</span>'
        else:
            badge_html = '<span class="badge-low">部分相似・人工確認</span>'

        with st.container(border=True):
            top_left, top_right = st.columns([3.5, 1.3])

            with top_left:
                st.markdown(f"#### #{rank} {found['name']} &nbsp; {badge_html}", unsafe_allow_html=True)
                st.caption(f"類別：{found['category']} | 拾獲地點：{found['location']} | 日期：{found['date']}")
                st.markdown("**推薦理由：** " + "、".join(result["reasons"]))

            with top_right:
                st.metric("媒合分數", f"{score} / 100")
                st.progress(min(max(score / 100, 0.0), 1.0))

            st.markdown(
                f"""
                <div class="compare-box">
                    <strong>欄位對照：</strong><br>
                    • <b>顏色</b>：遺失「{lost.get('color') or '未填'}」 vs. 拾獲「{found.get('color') or '未填'}」<br>
                    • <b>地點</b>：遺失「{lost.get('location') or '未填'}」 vs. 拾獲「{found.get('location') or '未填'}」<br>
                    • <b>描述</b>：遺失「{lost.get('description') or '無'}」 vs. 拾獲「{found.get('description') or '無'}」
                </div>
                """,
                unsafe_allow_html=True,
            )

            col_a, col_b = st.columns([3, 1])
            with col_a:
                with st.expander("展開各特徵相似度明細"):
                    detail_rows = [
                        {
                            "特徵項目": FEATURE_NAMES[key],
                            "權重": f"{int(WEIGHTS[key] * 100)}%",
                            "相似度": "未提供" if val is None else f"{val * 100:.1f}%",
                        }
                        for key, val in result["features"].items()
                    ]
                    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

            with col_b:
                if on_claim_callback is not None:
                    if st.button("標記為已領回", key=f"claim_{rank}_{found['name']}_{found['date']}", use_container_width=True):
                        on_claim_callback(found)

    st.caption("提醒：媒合分數僅供參考，領回前仍須由管理人員或當事人核對細節。")


# ==========================================
# 第三組：資料讀寫、表單與表格模組
# ==========================================

def is_duplicate(item, items):
    fields = ["name", "category", "color", "location", "date", "description"]
    return any(
        all(
            normalize_text(existing.get(key, "")) == normalize_text(item.get(key, ""))
            for key in fields
        )
        for existing in items
    )


def load_data():
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
    title = "📥 登記撿到的物品（拾獲物）" if kind == "found" else "📤 登記遺失的物品（遺失物）"
    st.subheader(title)

    with st.form(key=f"form_{kind}", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input(
                "物品名稱 *",
                max_chars=MAX_TEXT_LENGTH,
                placeholder="例如：黑色摺疊傘、iPad、學生證",
                help="必填，越具體越容易比對成功",
            )
            category = st.selectbox("物品類別 *", CATEGORIES)
            color = st.text_input(
                "物品顏色（選填）",
                max_chars=MAX_TEXT_LENGTH,
                placeholder="例如：黑色、透明、銀色",
            )
        with col2:
            location = st.text_input(
                "遺失／拾獲地點 *",
                max_chars=MAX_TEXT_LENGTH,
                placeholder="例如：圖書館三樓、綜合大樓、操場",
                help="必填，建議填寫建築物與樓層或區域",
            )
            item_date = st.date_input("日期 *", value=date.today(), max_value=date.today())
            description = st.text_area(
                "其他特徵或描述（選填）",
                max_chars=MAX_TEXT_LENGTH,
                height=72,
                placeholder="例如：有貼貼紙、保護殼有刮痕、附吊飾",
            )

        submitted = st.form_submit_button("送出登記", type="primary", use_container_width=True)

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
    if not items:
        st.info(empty_msg)
        return

    c1, c2, c3 = st.columns([1.4, 1.4, 2.2])
    with c1:
        status_filter = st.selectbox(
            "狀態篩選",
            ["全部", "open", "claimed", "closed"],
            format_func=lambda s: "全部狀態" if s == "全部" else f"{s}（{STATUS_LABELS.get(s, s)}）",
            key=f"status_{empty_msg}",
        )
    with c2:
        cat_filter = st.selectbox(
            "類別篩選",
            ["全部"] + CATEGORIES,
            key=f"cat_{empty_msg}",
        )
    with c3:
        keyword = st.text_input(
            "關鍵字搜尋",
            placeholder="搜尋名稱、地點或描述...",
            key=f"kw_{empty_msg}",
        )

    kw_norm = normalize_text(keyword)
    filtered = []
    for item in items:
        if status_filter != "全部" and item.get("status") != status_filter:
            continue
        if cat_filter != "全部" and item.get("category") != cat_filter:
            continue
        if kw_norm:
            haystack = normalize_text(
                f"{item.get('name', '')} {item.get('location', '')} {item.get('description', '')} {item.get('color', '')}"
            )
            if kw_norm not in haystack:
                continue
        filtered.append(item)

    if not filtered:
        st.info("沒有符合篩選條件的資料。")
        return

    rows = [
        {
            "編號": idx,
            "物品名稱": item.get("name", "未命名"),
            "類別": item.get("category", "未分類"),
            "顏色": item.get("color") or "未提供",
            "地點": item.get("location", "未提供"),
            "日期": item.get("date", "未提供"),
            "描述": item.get("description") or "無",
            "狀態": f"{item.get('status', 'open')}（{STATUS_LABELS.get(item.get('status', 'open'), '')}）",
        }
        for idx, item in enumerate(filtered, 1)
    ]

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"顯示 {len(filtered)} / {len(items)} 筆資料")


# ==========================================
# 第四組：主程式與網頁介面整合
# ==========================================

def main():
    found_items, lost_items, load_err = load_data()

    st.markdown(
        """
        <div class="hero-banner">
            <h1>🔍 國立彰化師範大學校園失物招領系統</h1>
            <p>快速登記遺失物與拾獲物，依名稱、類別、顏色、地點、日期與描述進行多維度相似度媒合</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if load_err:
        st.error(load_err)

    open_found = sum(1 for i in found_items if i.get("status") == "open")
    open_lost = sum(1 for i in lost_items if i.get("status") == "open")
    claimed_count = sum(1 for i in found_items if i.get("status") == "claimed")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("開放中拾獲物", f"{open_found} 筆")
    m2.metric("尋找中遺失物", f"{open_lost} 筆")
    m3.metric("已領回拾獲物", f"{claimed_count} 筆")
    m4.metric("媒合推薦門檻", f"{MIN_SCORE} 分")

    st.divider()

    with st.sidebar:
        st.header("功能導覽")
        menu = st.radio(
            "選擇操作項目",
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
        min_score_slider = st.slider(
            "最低顯示媒合分數",
            min_value=0,
            max_value=100,
            value=MIN_SCORE,
            step=5,
            help="調整媒合結果卡片的最低顯示分數",
        )
        with st.expander("查看權重與規則"):
            for k, w in WEIGHTS.items():
                st.write(f"- {FEATURE_NAMES[k]}：{int(w * 100)}%")
            st.caption("有效特徵少於 3 項時，分數上限為 49 分。")

    def mark_found_claimed(target_item):
        for f_item in found_items:
            if f_item is target_item:
                f_item["status"] = "claimed"
                break
        ok, err = save_data(found_items, lost_items)
        if ok:
            st.success(f"已將「{target_item.get('name')}」標記為 claimed（已領回）！")
            st.rerun()
        else:
            st.error(err)

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
                            st.markdown(f"**比對遺失物：** {lost['name']}（{lost['date']} @ {lost['location']}）")
                            render_matches_ui(lost, [item], min_score=min_score_slider)
                else:
                    st.error(err)

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
                    render_matches_ui(
                        item,
                        found_items,
                        min_score=min_score_slider,
                        on_claim_callback=mark_found_claimed,
                    )
                else:
                    st.error(err)

    elif menu == "3. 查看所有拾獲物":
        st.subheader("📦 所有拾獲物清單")
        render_items_table(found_items, "目前沒有任何拾獲物資料。")

    elif menu == "4. 查看所有遺失物":
        st.subheader("📋 所有遺失物清單")
        render_items_table(lost_items, "目前沒有任何遺失物資料。")

    elif menu == "5. 修改拾獲物狀態":
        st.subheader("🔄 修改拾獲物狀態")
        if not found_items:
            st.info("目前沒有拾獲物資料可修改。")
        else:
            options = [
                f"{i + 1}. {item['name']}（{item['category']}｜{item['location']}｜目前：{item['status']}）"
                for i, item in enumerate(found_items)
            ]
            selected = st.selectbox("選擇要修改的拾獲物", options)
            idx = options.index(selected)

            status_choices = {
                "open": "open（尚未領回）",
                "claimed": "claimed（已經領回）",
                "closed": "closed（已結案）",
            }
            new_status = st.selectbox(
                "選擇新狀態",
                list(status_choices.keys()),
                index=list(status_choices.keys()).index(found_items[idx]["status"]),
                format_func=lambda k: status_choices[k],
            )

            if st.button("更新狀態", type="primary"):
                found_items[idx]["status"] = new_status
                ok, err = save_data(found_items, lost_items)
                if ok:
                    st.success("物品狀態更新成功！")
                    st.rerun()
                else:
                    st.error(err)

    elif menu == "6. 刪除拾獲物":
        st.subheader("🗑️ 刪除拾獲物")
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

    elif menu == "7. 刪除遺失物":
        st.subheader("🗑️ 刪除遺失物")
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

    elif menu == "8. 重新比對現有遺失物":
        st.subheader("🔁 選擇已登記的遺失物進行比對")
        if not lost_items:
            st.info("目前沒有任何遺失物資料。")
        else:
            options = [
                f"{i + 1}. {item['name']}（{item['category']}｜{item['location']}｜{item['date']}）"
                for i, item in enumerate(lost_items)
            ]
            selected = st.selectbox("選擇遺失物", options)
            idx = options.index(selected)
            render_matches_ui(
                lost_items[idx],
                found_items,
                min_score=min_score_slider,
                on_claim_callback=mark_found_claimed,
            )


if __name__ == "__main__":
    main()