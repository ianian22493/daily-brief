"""
generate_brief.py — 每日新聞簡報生成腳本
GitHub Actions 每天 01:00 UTC（台灣 09:00）自動執行
使用 Gemini + Google Search 生成當日新聞，並重新產生 index.html
"""

import json, os, re
from datetime import datetime, timezone, timedelta, date, timedelta
from itertools import groupby

TZ_TW = timezone(timedelta(hours=8))

# ── 動物 Emoji 輪換表（月份 × 星期幾，0=週一 … 6=週日）──
MONTH_ANIMALS = {
    1:  ["🐻‍❄️","🐧","🦭","🦣","🐺","🦊","🐹"],
    2:  ["🐰","🐱","🐶","🐻","🐼","🐨","🦝"],
    3:  ["🐣","🐥","🦋","🐝","🐸","🐇","🦔"],
    4:  ["🐸","🐇","🐿️","🦔","🦥","🦦","🦡"],
    5:  ["🦌","🐺","🦊","🐻","🦝","🐗","🦡"],
    6:  ["🐬","🐋","🦈","🐙","🐠","🐡","🦑"],
    7:  ["🦁","🐯","🦒","🐘","🦏","🦓","🐆"],
    8:  ["🦀","🐢","🦭","🦞","🦐","🐡","🐠"],
    9:  ["🦊","🦝","🐿️","🦡","🐻","🦌","🐺"],
    10: ["🦉","🦇","🐈‍⬛","🦊","🐺","🦝","🐻"],
    11: ["🦔","🐿️","🦡","🦦","🦥","🐻","🐹"],
    12: ["🦌","🐻‍❄️","🐧","🦭","🦊","🐺","🐹"],
}
MONTH_ICONS = {
    1:"❄️", 2:"🧧", 3:"🌸", 4:"🌿", 5:"🌺", 6:"☀️",
    7:"🌊", 8:"🌻", 9:"🥮", 10:"🍁", 11:"🍂", 12:"🎄"
}
WEEKDAY_ZH = ["一","二","三","四","五","六","日"]
MONTH_ZH   = ["","一月","二月","三月","四月","五月","六月",
              "七月","八月","九月","十月","十一月","十二月"]

# ── 特殊日期提醒（月, 日）──
SPECIAL_DATES = {
    (11,  7): {"label": "你的生日",   "today_msg": "生日快樂！🎉",       "emoji": "🎂"},
    ( 4, 14): {"label": "老婆的生日", "today_msg": "記得好好慶祝 💑",    "emoji": "🎂"},
    ( 1,  4): {"label": "結婚紀念日", "today_msg": "紀念日快樂 💍",       "emoji": "💍"},
    ( 4, 26): {"label": "媽媽的生日", "today_msg": "記得打電話祝福 🌸",  "emoji": "🎂"},
    ( 8,  8): {"label": "爸爸的生日", "today_msg": "記得打電話祝福 👨‍👧", "emoji": "🎂"},
    ( 6, 16): {"label": "哥哥的生日", "today_msg": "記得傳訊息祝福 🎉",  "emoji": "🎂"},
    (10, 17): {"label": "姐姐的生日", "today_msg": "記得傳訊息祝福 🎊",  "emoji": "🎂"},
}


# ════════════════════════════════════════════════════════════════════
# Gemini — 搜尋並生成新聞內容
# ════════════════════════════════════════════════════════════════════
STATE_FILE = "brief_state.json"


def load_used_facts():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"facts": []}


def save_used_fact(state, date_str, fact_title):
    state["facts"] = [e for e in state["facts"] if e.get("date") != date_str]
    state["facts"].append({"date": date_str, "title": fact_title})
    state["facts"].sort(key=lambda e: e["date"])
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_news(date_str, weekday_zh, used_facts_state):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("未設定環境變數 GEMINI_API_KEY")

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)

    all_titles = [e["title"] for e in used_facts_state.get("facts", [])]
    if all_titles:
        avoid_block = (
            "\n\n⚠️ 冷知識注意事項（非常重要）：以下是過去所有已出現過的冷知識主題，"
            "請絕對不要重複或使用相似的事實，必須選擇全新的主題：\n"
            + "\n".join(f"- {t}" for t in all_titles)
        )
    else:
        avoid_block = ""

    prompt = f"""今天是 {date_str}（星期{weekday_zh}）。

你是繁體中文新聞編輯，請搜尋今天（{date_str}）最新的國際新聞，撰寫每日簡報。

任務：
1. 選出今天最重要的 5 則全球新聞（涵蓋政治、衝突、經濟、社會、科技，優先選有即時新聞的）
2. 撰寫 1 則有趣的冷知識（科學、歷史、自然等皆可）{avoid_block}

新聞格式要求：
- 標題：15–30 字，精確描述事件核心，主詞清楚
- 內文：2–4 句話，說明背景、事件經過與影響
- 使用繁體中文，語氣中立客觀
- 若為昨日已報導但今日有新進展的事件，標題前加「📌 更新｜」

冷知識格式要求：
- 標題：10–20 字，有趣的事實陳述句
- 內文：2–3 句話，說明詳情與為何有趣

請輸出純 JSON，不含任何 markdown 標記、說明文字或 code block：
{{"news":[{{"title":"...","body":"..."}},{{"title":"...","body":"..."}},{{"title":"...","body":"..."}},{{"title":"...","body":"..."}},{{"title":"...","body":"..."}}],"fact":{{"title":"...","body":"..."}}}}"""

    import time

    def try_generate(model, contents, config=None, label=""):
        for attempt in range(3):
            try:
                if config:
                    resp = client.models.generate_content(model=model, contents=contents, config=config)
                else:
                    resp = client.models.generate_content(model=model, contents=contents)
                return resp.text
            except Exception as e:
                msg = str(e)
                if "503" in msg and attempt < 2:
                    wait = 20 * (attempt + 1)
                    print(f"  ⏳ {label} 503 繁忙，{wait}秒後重試（第{attempt+1}次）...")
                    time.sleep(wait)
                else:
                    raise
        return None

    text = None
    errors = []

    try:
        text = try_generate(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            ),
            label="gemini-2.5-flash+search"
        )
        print("  ✓ gemini-2.5-flash + google_search")
    except Exception as e:
        errors.append(f"gemini-2.5-flash+search: {e}")

    if text is None:
        try:
            text = try_generate(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
                label="gemini-2.5-flash-lite+search"
            )
            print("  ✓ gemini-2.5-flash-lite + google_search")
        except Exception as e:
            errors.append(f"gemini-2.5-flash-lite: {e}")

    if text is None:
        try:
            text = try_generate(
                model="gemini-2.5-flash",
                contents=prompt + "\n\n（本次無法搜尋最新資料，請以訓練資料中最近的知識回答，每則標題末加上「⚠️」）",
                label="gemini-2.5-flash-fallback"
            )
            print("  ⚠ gemini-2.5-flash fallback（無搜尋）")
        except Exception as e:
            errors.append(f"gemini-2.5-flash fallback: {e}")

    if text is None:
        raise RuntimeError("所有 Gemini 嘗試均失敗：" + "; ".join(errors))

    text = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"^```\s*",     "", text,          flags=re.MULTILINE)
    text = text.strip()
    text = re.sub(r"\[\d+\]", "", text)

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON 解析失敗（{e}），改用無搜尋模式重試...")
        retry_text = try_generate(
            model="gemini-2.5-flash",
            contents=prompt + "\n\n重要：只輸出純 JSON，不含任何引用標記、括號數字或額外說明。",
            label="gemini-2.5-flash-json-retry"
        )
        if retry_text is None:
            raise
        retry_text = re.sub(r"^```json\s*", "", retry_text.strip(), flags=re.MULTILINE)
        retry_text = re.sub(r"^```\s*",     "", retry_text,          flags=re.MULTILINE)
        retry_text = re.sub(r"\[\d+\]",     "", retry_text)
        retry_text = retry_text.strip()
        m2 = re.search(r"\{.*\}", retry_text, re.DOTALL)
        if m2:
            retry_text = m2.group()
        return json.loads(retry_text)


# ════════════════════════════════════════════════════════════════════
# HTML 生成：單日 brief 頁面（Yuzu Brief 設計）
# ════════════════════════════════════════════════════════════════════
DASHBOARD_URL  = "https://ianian22493.github.io/investment-dashboard/"
PHOTOSHOP_URL  = "https://ianian22493.github.io/photoshop/"

# Yuzu SVG logo（Y 融入柚子切片）
YUZU_LOGO_LG = """<svg width="36" height="36" viewBox="0 0 34 34" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="lg1" cx="38%" cy="28%" r="72%">
      <stop offset="0%" stop-color="#f0d050"/>
      <stop offset="100%" stop-color="#a06010"/>
    </radialGradient>
  </defs>
  <circle cx="17" cy="17" r="17" fill="url(#lg1)"/>
  <circle cx="17" cy="17" r="11.5" fill="none" stroke="rgba(255,255,255,.45)" stroke-width="1.2"/>
  <circle cx="17" cy="17" r="2.8" fill="rgba(255,255,255,.75)"/>
  <line x1="17" y1="14.2" x2="10.5" y2="7.5" stroke="rgba(255,255,255,.7)" stroke-width="1.4" stroke-linecap="round"/>
  <line x1="17" y1="14.2" x2="23.5" y2="7.5" stroke="rgba(255,255,255,.7)" stroke-width="1.4" stroke-linecap="round"/>
  <line x1="17" y1="14.2" x2="17"   y2="23"  stroke="rgba(255,255,255,.7)" stroke-width="1.4" stroke-linecap="round"/>
  <line x1="17" y1="5.5"  x2="17"   y2="14.2" stroke="rgba(255,255,255,.2)" stroke-width="1" stroke-linecap="round"/>
  <line x1="6.8" y1="22.5" x2="12.5" y2="18.5" stroke="rgba(255,255,255,.2)" stroke-width="1" stroke-linecap="round"/>
  <line x1="27.2" y1="22.5" x2="21.5" y2="18.5" stroke="rgba(255,255,255,.2)" stroke-width="1" stroke-linecap="round"/>
</svg>"""

YUZU_LOGO_SM = """<svg width="28" height="28" viewBox="0 0 34 34" fill="none">
  <defs>
    <radialGradient id="lg2" cx="38%" cy="28%" r="72%">
      <stop offset="0%" stop-color="#f0d050"/>
      <stop offset="100%" stop-color="#a06010"/>
    </radialGradient>
  </defs>
  <circle cx="17" cy="17" r="17" fill="url(#lg2)"/>
  <circle cx="17" cy="17" r="11.5" fill="none" stroke="rgba(255,255,255,.45)" stroke-width="1.2"/>
  <circle cx="17" cy="17" r="2.8"  fill="rgba(255,255,255,.75)"/>
  <line x1="17" y1="14.2" x2="10.5" y2="7.5"  stroke="rgba(255,255,255,.7)" stroke-width="1.4" stroke-linecap="round"/>
  <line x1="17" y1="14.2" x2="23.5" y2="7.5"  stroke="rgba(255,255,255,.7)" stroke-width="1.4" stroke-linecap="round"/>
  <line x1="17" y1="14.2" x2="17"   y2="23"   stroke="rgba(255,255,255,.7)" stroke-width="1.4" stroke-linecap="round"/>
</svg>"""


def get_special_day_banner(dt):
    from datetime import timedelta
    today_key = (dt.month, dt.day)
    tom       = (dt + timedelta(days=1))
    tom_key   = (tom.month, tom.day)

    if today_key in SPECIAL_DATES:
        info = SPECIAL_DATES[today_key]
        return (
            f'<div class="special-banner special-banner--today">'
            f'<div class="banner-emoji">{info["emoji"]}</div>'
            f'<div class="banner-text">'
            f'<div class="banner-title">今天是{info["label"]}！</div>'
            f'<div class="banner-sub">{info["today_msg"]}</div>'
            f'</div></div>'
        )
    elif tom_key in SPECIAL_DATES:
        info = SPECIAL_DATES[tom_key]
        return (
            f'<div class="special-banner special-banner--tomorrow">'
            f'<div class="banner-emoji">🔔</div>'
            f'<div class="banner-text">'
            f'<div class="banner-title">明天是{info["label"]}（{tom.month}/{tom.day}）</div>'
            f'<div class="banner-sub">記得提前準備喔～</div>'
            f'</div></div>'
        )
    return ""


# 每則新聞的 accent 色
NEWS_ACCENT_COLORS = ["#1b2d4f", "#2563eb", "#0891b2", "#7c3aed", "#b45309"]


def build_brief_html(data, dt):
    date_str       = dt.strftime("%Y-%m-%d")
    date_zh        = f"{dt.year}年{dt.month}月{dt.day}日"
    year_zh        = f"{dt.year}年"
    md_zh          = f"{dt.month}月{dt.day}日"
    weekday        = WEEKDAY_ZH[dt.weekday()]
    animal         = MONTH_ANIMALS[dt.month][dt.weekday()]
    special_banner = get_special_day_banner(dt)

    # 新聞 HTML
    news_html = ""
    for i, item in enumerate(data["news"][:5], 1):
        ac = NEWS_ACCENT_COLORS[i - 1]
        news_html += f"""
      <div class="ni" style="--ac:{ac}">
        <div class="ni-n"><div class="ni-num">{i}</div></div>
        <div class="ni-body">
          <div class="ni-title">{item['title']}</div>
          <div class="ni-text">{item['body']}</div>
        </div>
      </div>"""

    fact = data["fact"]

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Yuzu Brief — {date_zh}</title>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,400&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=Noto+Serif+TC:wght@700;900&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
    :root {{
      --bg:    #F7F6F2;
      --bg2:   #EDEBE4;
      --navy:  #1b2d4f;
      --navy2: #0f1d34;
      --ink:   #1a1a1a;
      --ink2:  #555555;
      --ink3:  #9ca3af;
      --border:#E8E4DC;
      --gold:  #b8922e;
      --gold-l:#e8c84a;
      --gold-bg:#fdf8ec;
      --gold-b:#e8cf85;
    }}
    body {{ background:var(--bg); color:var(--ink); font-family:'DM Sans','Noto Sans TC',sans-serif; min-height:100vh; }}

    /* Reading bar */
    #rbar {{ position:fixed; top:0; left:0; z-index:400; height:3px; width:0%; background:linear-gradient(90deg,var(--navy) 0%,#4d9cf8 100%); transition:width .08s linear; }}

    /* Top nav */
    .topnav {{ position:sticky; top:0; z-index:300; height:52px; padding:0 28px; background:rgba(243,239,231,.92); backdrop-filter:blur(18px); -webkit-backdrop-filter:blur(18px); border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; }}
    .tn-brand {{ display:flex; align-items:center; gap:11px; text-decoration:none; }}
    .tn-name {{ font-size:14px; font-weight:700; color:var(--ink); }}
    .tn-sub {{ font-size:9px; color:var(--ink3); letter-spacing:.12em; text-transform:uppercase; margin-top:1px; }}
    .tn-links {{ display:flex; gap:22px; }}
    .tn-link {{ font-size:12px; color:var(--ink3); text-decoration:none; letter-spacing:.04em; transition:color .15s; }}
    .tn-link:hover, .tn-link.cur {{ color:var(--ink); }}

    /* Hero */
    .hero {{ background:var(--navy2); position:relative; overflow:hidden; }}
    .hero-bg {{ position:absolute; inset:0; pointer-events:none; overflow:hidden; }}
    .hero-bg svg {{ position:absolute; inset:0; width:100%; height:100%; opacity:.06; }}
    .hero-inner {{ max-width:720px; margin:0 auto; padding:52px 32px 0; position:relative; z-index:1; }}
    .hero-layout {{ display:flex; flex-direction:row; justify-content:space-between; align-items:flex-start; gap:16px; }}
    .hero-left {{ flex:1; min-width:0; }}
    .hero-eyebrow {{ font-size:10px; font-weight:600; letter-spacing:.22em; text-transform:uppercase; color:rgba(255,255,255,.28); margin-bottom:18px; display:flex; align-items:center; gap:12px; }}
    .hero-eyebrow::before {{ content:''; width:18px; height:1px; background:rgba(255,255,255,.2); display:inline-block; }}
    .hero-date {{ font-family:'Playfair Display','Noto Serif TC',serif; font-weight:900; color:#fff; line-height:1.0; }}
    .hero-date .yr {{ display:block; font-size:clamp(14px,2vw,18px); font-weight:400; font-style:italic; color:rgba(255,255,255,.38); margin-bottom:4px; }}
    .hero-date .md {{ display:block; font-size:clamp(28px,6vw,56px); letter-spacing:-.03em; }}
    .hero-weekday {{ margin-top:20px; display:inline-flex; align-items:center; gap:10px; flex-wrap:wrap; }}
    .hero-badge {{ background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.16); border-radius:20px; padding:5px 18px; font-size:12px; color:rgba(255,255,255,.6); font-weight:500; white-space:nowrap; }}
    .hero-slogan {{ font-size:12px; color:rgba(255,255,255,.55); letter-spacing:.05em; }}
    .hero-animal {{ width:88px; height:88px; background:rgba(255,255,255,.07); border:1.5px solid rgba(255,255,255,.13); border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:48px; line-height:1; flex-shrink:0; margin-top:4px; }}
    @media(max-width:640px){{ .hero-inner {{ padding:40px 20px 0; }} .hero-animal {{ width:68px; height:68px; font-size:38px; }} .hero-slogan {{ display:none; }} .body-wrap {{ padding:0 16px 64px; }} }}
    .hero-rule {{ margin-top:36px; height:1px; background:linear-gradient(90deg,rgba(201,168,76,.5) 0%,rgba(201,168,76,.0) 60%); }}
    .hero-sections {{ display:flex; gap:0; padding:13px 0; }}
    .hs-item {{ font-size:10px; font-weight:600; letter-spacing:.14em; text-transform:uppercase; color:rgba(255,255,255,.55); padding-right:22px; margin-right:22px; border-right:1px solid rgba(255,255,255,.15); display:flex; align-items:center; gap:6px; }}
    .hs-item:last-child {{ border-right:none; }}
    .hs-item.hi {{ color:rgba(255,255,255,.9); }}

    /* Body */
    .body-wrap {{ max-width:720px; margin:0 auto; padding:0 24px 80px; }}
    .a-sec {{ padding:44px 0; border-bottom:1px solid var(--border); }}
    .a-sec:last-child {{ border-bottom:none; }}
    .sec-head {{ display:flex; align-items:center; gap:14px; margin-bottom:28px; }}
    .sec-icon {{ font-size:20px; }}
    .sec-label {{ font-size:11px; font-weight:700; letter-spacing:.16em; text-transform:uppercase; color:var(--ink3); white-space:nowrap; }}
    .sec-rule {{ flex:1; height:1px; background:var(--border); }}
    hr {{ border:none; border-top:1px solid #EAEAEA; margin:32px 0; }}

    /* News */
    .news-list {{ display:flex; flex-direction:column; gap:14px; }}
    .ni {{ --ac:#1b2d4f; display:grid; grid-template-columns:52px 1fr; padding:22px 20px 22px 16px; background:#ffffff; border-radius:14px; border:1px solid #EDEAE4; box-shadow:0 2px 8px rgba(0,0,0,.04); transition:opacity .5s ease, transform .3s ease, box-shadow .3s ease; }}
    .ni:hover {{ transform:translateY(-2px); box-shadow:0 6px 20px rgba(0,0,0,.07); }}
    .ni:hover .ni-title {{ color:var(--ac); }}
    .ni:hover .ni-num {{ opacity:.38; }}
    .ni-num {{ font-family:'Playfair Display',serif; font-size:44px; font-weight:900; line-height:1; color:var(--ac); opacity:.14; letter-spacing:-.03em; transition:opacity .2s; padding-top:4px; text-align:center; }}
    .ni-title {{ font-family:'Playfair Display','Noto Serif TC',serif; font-size:clamp(17px,2.5vw,19px); font-weight:700; line-height:1.45; color:var(--ink); margin-bottom:12px; text-wrap:pretty; transition:color .2s ease; border-left:3px solid #D0CBBD; padding-left:10px; }}
    .ni-text {{ font-size:15px; line-height:1.85; color:var(--ink2); text-wrap:pretty; padding-left:13px; }}
    .ni-lead {{ display:block; padding-left:14px; border-left:2.5px solid var(--ac); font-size:15px; font-weight:500; line-height:1.8; color:var(--ink2); margin-bottom:12px; }}

    /* Fact */
    .fact-wrap {{ background:var(--navy); border-radius:20px; overflow:hidden; position:relative; }}
    .fact-wrap::before {{ content:''; position:absolute; right:-60px; top:-60px; width:220px; height:220px; border-radius:50%; background:radial-gradient(circle,rgba(201,168,76,.12) 0%,transparent 65%); pointer-events:none; }}
    .fact-inner {{ display:grid; grid-template-columns:6px 1fr; }}
    .fact-stripe {{ background:linear-gradient(180deg,var(--gold-l),rgba(184,146,46,.2)); }}
    .fact-content {{ padding:34px 36px; }}
    .fact-kicker {{ font-size:10px; font-weight:700; letter-spacing:.18em; text-transform:uppercase; color:var(--gold-l); margin-bottom:14px; display:flex; align-items:center; gap:8px; }}
    .fact-kicker::before {{ content:''; display:inline-block; width:18px; height:1px; background:var(--gold); }}
    .fact-title {{ font-family:'Playfair Display','Noto Serif TC',serif; font-size:clamp(22px,3vw,28px); font-weight:700; color:#fff; margin-bottom:18px; line-height:1.3; }}
    .fact-body {{ font-size:15px; line-height:2; color:rgba(255,255,255,.78); }}
    .fact-animal {{ position:absolute; right:28px; bottom:24px; font-size:48px; opacity:.1; line-height:1; }}

    /* Special banner */
    .special-banner {{ display:flex; align-items:center; gap:16px; border-radius:14px; padding:18px 24px; margin-bottom:0; }}
    .special-banner--today {{ background:linear-gradient(135deg,#ff6b9d 0%,#ff8c42 100%); box-shadow:0 4px 20px rgba(255,107,157,0.35); }}
    .special-banner--tomorrow {{ background:linear-gradient(135deg,#fffbea 0%,#fff0c0 100%); border:1.5px solid #ffd54f; }}
    .banner-emoji {{ font-size:40px; line-height:1; flex-shrink:0; }}
    .banner-title {{ font-size:17px; font-weight:800; line-height:1.3; }}
    .banner-sub {{ font-size:13px; margin-top:4px; }}
    .special-banner--today .banner-title {{ color:#fff; }}
    .special-banner--today .banner-sub {{ color:rgba(255,255,255,.85); }}
    .special-banner--tomorrow .banner-title {{ color:#7a4e00; }}
    .special-banner--tomorrow .banner-sub {{ color:#a06500; }}

    /* Footer */
    .site-footer {{ max-width:720px; margin:0 auto; padding:24px 24px 52px; border-top:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:14px; }}
    .sf-brand {{ display:flex; align-items:center; gap:10px; }}
    .sf-name {{ font-size:12px; font-weight:600; color:var(--ink3); }}
    .sf-date {{ font-size:11px; color:var(--ink3); margin-top:1px; }}
    .sf-links {{ display:flex; gap:20px; }}
    .sf-links a {{ font-size:12px; color:var(--ink3); text-decoration:none; transition:color .15s; }}
    .sf-links a:hover {{ color:var(--ink); }}

    /* Animations */
    .js-animate .reveal {{ opacity:0; transform:translateY(16px); }}
    .js-animate .ni {{ opacity:0; transform:translateY(16px); }}
    .js-animate .fact-wrap {{ opacity:0; transform:translateY(16px); }}
    .reveal, .ni, .fact-wrap {{ transition:opacity .5s ease, transform .5s ease; }}
    .reveal.in, .ni.in, .fact-wrap.in {{ opacity:1 !important; transform:translateY(0) !important; }}

    /* FAB dock */
    .fab-dock {{ position:fixed; bottom:28px; right:28px; z-index:999; display:flex; flex-direction:column; align-items:flex-end; gap:10px; }}
    .yuzu-fab {{ display:flex; align-items:center; gap:12px; background:linear-gradient(135deg,#bf9618 0%,#f5e264 42%,#c8a020 100%); color:#1b2d4f; text-decoration:none; padding:10px 18px 10px 10px; border-radius:50px; font-family:'DM Sans','Noto Sans TC',sans-serif; box-shadow:0 2px 0 rgba(255,255,255,.4) inset,0 6px 24px rgba(160,122,18,.55),0 2px 5px rgba(0,0,0,.14); transition:transform .25s cubic-bezier(.34,1.56,.64,1),box-shadow .25s; animation:fab-glow 3s ease-in-out infinite; }}
    .yuzu-fab:hover {{ transform:translateY(-4px) scale(1.04); box-shadow:0 2px 0 rgba(255,255,255,.4) inset,0 14px 40px rgba(160,122,18,.72),0 2px 8px rgba(0,0,0,.18); animation:none; }}
    .yuzu-fab-cam {{ display:flex; align-items:center; gap:12px; background:linear-gradient(145deg,#2d2d2d 0%,#1e1e1e 55%,#141414 100%); color:rgba(255,255,255,.93); text-decoration:none; padding:10px 18px 10px 10px; border-radius:50px; font-family:'DM Sans','Noto Sans TC',sans-serif; box-shadow:0 1px 0 rgba(255,255,255,.1) inset,0 6px 22px rgba(0,0,0,.45),0 2px 6px rgba(0,0,0,.2); border:1px solid rgba(255,255,255,.1); transition:transform .25s cubic-bezier(.34,1.56,.64,1),box-shadow .25s; }}
    .yuzu-fab-cam:hover {{ transform:translateY(-4px) scale(1.04); box-shadow:0 1px 0 rgba(255,255,255,.16) inset,0 14px 38px rgba(0,0,0,.6),0 2px 8px rgba(0,0,0,.28); color:#fff; border-color:rgba(255,255,255,.2); }}
    .yuzu-fab-icon {{ flex-shrink:0; width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; }}
    .yuzu-fab-cam .yuzu-fab-icon {{ background:rgba(255,255,255,.1); }}
    .yuzu-fab .yuzu-fab-icon {{ background:rgba(27,45,79,.16); }}
    .yuzu-fab-text {{ display:flex; flex-direction:column; line-height:1; }}
    .yuzu-fab-name {{ font-size:13px; font-weight:800; letter-spacing:.01em; }}
    .yuzu-fab-sub  {{ font-size:9px; font-weight:600; opacity:.55; letter-spacing:.12em; text-transform:uppercase; margin-top:3px; }}
    .yuzu-fab-arr  {{ font-size:16px; font-weight:300; opacity:.45; margin-left:4px; transition:transform .2s,opacity .2s; }}
    .yuzu-fab:hover .yuzu-fab-arr, .yuzu-fab-cam:hover .yuzu-fab-arr {{ transform:translateX(3px); opacity:.9; }}
    @keyframes fab-glow {{
      0%,100% {{ box-shadow:0 2px 0 rgba(255,255,255,.4) inset,0 6px 24px rgba(160,122,18,.55),0 2px 5px rgba(0,0,0,.14); }}
      50%      {{ box-shadow:0 2px 0 rgba(255,255,255,.4) inset,0 6px 42px rgba(160,122,18,.82),0 2px 5px rgba(0,0,0,.14); }}
    }}
  </style>
</head>
<body>

<div id="rbar"></div>

{special_banner}

<!-- Nav -->
<nav class="topnav">
  <a class="tn-brand" href="index.html">
    {YUZU_LOGO_LG}
    <div>
      <div class="tn-name">Yuzu Brief</div>
      <div class="tn-sub">Daily News</div>
    </div>
  </a>
  <div class="tn-links">
    <a class="tn-link" href="{DASHBOARD_URL}" target="_blank">Yuzu Finance</a>
    <a class="tn-link cur" href="#">Yuzu Brief</a>
  </div>
</nav>

<!-- Hero -->
<div class="hero">
  <div class="hero-bg">
    <svg viewBox="0 0 800 380" preserveAspectRatio="xMidYMid slice" fill="none">
      <circle cx="700" cy="50" r="200" stroke="white" stroke-width="1"/>
      <circle cx="700" cy="50" r="130" stroke="white" stroke-width="1"/>
      <circle cx="700" cy="50" r="60"  stroke="white" stroke-width="1"/>
      <circle cx="100" cy="320" r="150" stroke="white" stroke-width=".7"/>
      <line x1="700" y1="50" x2="540" y2="190" stroke="white" stroke-width=".6"/>
      <line x1="700" y1="50" x2="860" y2="190" stroke="white" stroke-width=".6"/>
      <line x1="700" y1="50" x2="700" y2="230" stroke="white" stroke-width=".6"/>
    </svg>
  </div>
  <div class="hero-inner">
    <div class="hero-layout">
      <div class="hero-left">
        <div class="hero-eyebrow">Yuzu Brief · Daily News</div>
        <div class="hero-date">
          <span class="yr">{year_zh}</span>
          <span class="md">{md_zh}</span>
        </div>
        <div class="hero-weekday">
          <span class="hero-badge">星期{weekday}</span>
          <span class="hero-slogan">用五分鐘，掌握今天的世界</span>
        </div>
      </div>
      <div class="hero-animal">{animal}</div>
    </div>
    <div class="hero-rule"></div>
    <div class="hero-sections">
      <div class="hs-item hi"><span>🌍</span> 全球五大新聞</div>
      <div class="hs-item" style="color:rgba(255,255,255,.75)"><span>🧠</span> 每日冷知識</div>
    </div>
  </div>
</div>

<!-- Body -->
<div class="body-wrap">

  <div class="a-sec reveal">
    <div class="sec-head">
      <span class="sec-icon">🌍</span>
      <span class="sec-label">全球五大新聞</span>
      <div class="sec-rule"></div>
    </div>
    <div class="news-list">
{news_html}
    </div>
  </div>

  <div class="a-sec reveal">
    <div class="sec-head">
      <span class="sec-icon">🧠</span>
      <span class="sec-label">每日冷知識</span>
      <div class="sec-rule"></div>
    </div>
    <div class="fact-wrap">
      <div class="fact-inner">
        <div class="fact-stripe"></div>
        <div class="fact-content">
          <div class="fact-kicker">Today's Fun Fact</div>
          <div class="fact-title">{fact['title']}</div>
          <div class="fact-body">{fact['body']}</div>
        </div>
      </div>
      <div class="fact-animal">{animal}</div>
    </div>
  </div>

</div>

<!-- Footer -->
<footer class="site-footer">
  <div class="sf-brand">
    {YUZU_LOGO_SM}
    <div>
      <div class="sf-name">Yuzu Brief · Daily News</div>
      <div class="sf-date">{date_str}</div>
    </div>
  </div>
  <div class="sf-links">
    <a href="index.html">← 所有簡報</a>
    <a href="{DASHBOARD_URL}" target="_blank">Yuzu Finance →</a>
  </div>
</footer>

<!-- FAB dock -->
<div class="fab-dock">
  <a class="yuzu-fab-cam" href="{PHOTOSHOP_URL}" target="_blank">
    <div class="yuzu-fab-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg></div>
    <div class="yuzu-fab-text">
      <div class="yuzu-fab-name">Yuzu Photoshop</div>
      <div class="yuzu-fab-sub">圖片風格工具</div>
    </div>
    <div class="yuzu-fab-arr">›</div>
  </a>
  <a class="yuzu-fab" href="{DASHBOARD_URL}" target="_blank">
    <div class="yuzu-fab-icon"><svg width="26" height="26" viewBox="0 0 34 34" fill="none"><defs><radialGradient id="fg" cx="38%" cy="28%" r="72%"><stop offset="0%" stop-color="#fffbe8"/><stop offset="100%" stop-color="#7a4800"/></radialGradient></defs><circle cx="17" cy="17" r="17" fill="url(#fg)"/><circle cx="17" cy="17" r="11.5" fill="none" stroke="rgba(27,45,79,.3)" stroke-width="1.2"/><circle cx="17" cy="17" r="2.8" fill="rgba(27,45,79,.6)"/><line x1="17" y1="14.2" x2="10.5" y2="7.5" stroke="rgba(27,45,79,.7)" stroke-width="1.4" stroke-linecap="round"/><line x1="17" y1="14.2" x2="23.5" y2="7.5" stroke="rgba(27,45,79,.7)" stroke-width="1.4" stroke-linecap="round"/><line x1="17" y1="14.2" x2="17" y2="23" stroke="rgba(27,45,79,.7)" stroke-width="1.4" stroke-linecap="round"/></svg></div>
    <div class="yuzu-fab-text">
      <div class="yuzu-fab-name">Yuzu Finance</div>
      <div class="yuzu-fab-sub">投資儀表板</div>
    </div>
    <div class="yuzu-fab-arr">›</div>
  </a>
</div>

<script>
window.addEventListener('scroll', function() {{
  var d = document.documentElement;
  document.getElementById('rbar').style.width =
    Math.min((d.scrollTop / (d.scrollHeight - d.clientHeight)) * 100, 100) + '%';
}});

document.body.classList.add('js-animate');

var secObs = new IntersectionObserver(function(entries) {{
  entries.forEach(function(e) {{ if (e.isIntersecting) {{ e.target.classList.add('in'); secObs.unobserve(e.target); }} }});
}}, {{ threshold: 0, rootMargin: '0px 0px -40px 0px' }});
document.querySelectorAll('.reveal').forEach(function(el) {{ secObs.observe(el); }});

var listObs = new IntersectionObserver(function(entries) {{
  entries.forEach(function(e) {{
    if (!e.isIntersecting) return;
    e.target.querySelectorAll('.ni').forEach(function(item, i) {{
      setTimeout(function() {{ item.classList.add('in'); }}, i * 100);
    }});
    e.target.querySelectorAll('.fact-wrap').forEach(function(c) {{
      setTimeout(function() {{ c.classList.add('in'); }}, 150);
    }});
    listObs.unobserve(e.target);
  }});
}}, {{ threshold: 0, rootMargin: '0px 0px -40px 0px' }});
document.querySelectorAll('.a-sec').forEach(function(el) {{ listObs.observe(el); }});

setTimeout(function() {{
  document.querySelectorAll('.reveal:not(.in)').forEach(function(el) {{ el.classList.add('in'); }});
  document.querySelectorAll('.ni:not(.in)').forEach(function(el, i) {{
    setTimeout(function() {{ el.classList.add('in'); }}, i * 60);
  }});
  document.querySelectorAll('.fact-wrap:not(.in)').forEach(function(el) {{ el.classList.add('in'); }});
}}, 900);
</script>
</body>
</html>"""


# ════════════════════════════════════════════════════════════════════
# index.html 生成（掃描所有 YYYY-MM-DD.html，重建首頁）
# ════════════════════════════════════════════════════════════════════
def build_index_html(repo_dir):
    today  = datetime.now(TZ_TW).date()
    cutoff = today - timedelta(days=13)

    files = sorted(
        [f for f in os.listdir(repo_dir) if re.match(r"^\d{4}-\d{2}-\d{2}\.html$", f)],
        reverse=True
    )

    def get_info(filename):
        d = datetime.strptime(filename[:10], "%Y-%m-%d").date()
        headline, sub = "點擊閱讀", ""
        try:
            with open(os.path.join(repo_dir, filename), encoding="utf-8") as f:
                content = f.read()
            titles = re.findall(r'class="news-title">(.*?)</div>', content)
            if not titles:
                titles = re.findall(r'class="ni-title">(.*?)</div>', content)
            titles = [re.sub(r"<[^>]+>", "", t).replace("📌 更新｜", "").strip() for t in titles]
            if titles:
                headline = titles[0][:38] + ("…" if len(titles[0]) > 38 else "")
            if len(titles) >= 3:
                sub = " · ".join(t[:16] + ("…" if len(t) > 16 else "") for t in titles[1:3])
        except Exception:
            pass
        return {
            "filename": filename, "date": d,
            "day": d.day, "month": d.month, "year": d.year,
            "month_key": f"{d.year}-{d.month:02d}",
            "month_label": f"{d.year}年{d.month}月",
            "weekday_zh": WEEKDAY_ZH[d.weekday()],
            "headline": headline, "sub": sub,
            "is_recent": d >= cutoff,
            "is_current_month": (d.year == today.year and d.month == today.month),
        }

    infos = [get_info(f) for f in files]

    def make_row(item):
        return (
            f'<a href="{item["filename"]}" class="brief-row">'
            f'<div class="brief-date-badge">'
            f'<div class="badge-day">{item["day"]}</div>'
            f'<div class="badge-weekday">週{item["weekday_zh"]}</div>'
            f'</div>'
            f'<div class="brief-info">'
            f'<div class="brief-info-title">{item["headline"]}</div>'
            f'<div class="brief-info-sub">{item["sub"]}</div>'
            f'</div>'
            f'<div class="brief-arrow">›</div>'
            f'</a>'
        )

    recent_rows = "\n".join(make_row(i) for i in infos if i["is_recent"])
    if not recent_rows:
        recent_rows = '<div class="empty-hint">尚無近期簡報</div>'

    month_cards  = ""
    month_panels = ""
    month_groups = []
    for mk, items in groupby(infos, key=lambda x: x["month_key"]):
        items = list(items)
        y, m = int(mk[:4]), int(mk[5:])
        month_groups.append({
            "key": mk, "label": items[0]["month_label"],
            "year": y, "month": m, "count": len(items),
            "items": items,
            "is_current": items[0]["is_current_month"],
        })

    for g in month_groups:
        badge  = '<div class="month-card-ongoing">進行中</div>' if g["is_current"] else ""
        cls    = " month-card--current" if g["is_current"] else ""
        animal = MONTH_ICONS[g["month"]]
        month_cards += (
            f'<div class="month-card m{g["month"]}{cls}" data-month="{g["key"]}" onclick="toggleMonth(\'{g["key"]}\')">'
            f'{badge}'
            f'<div class="month-card-animal">{animal}</div>'
            f'<div class="month-card-year">{g["year"]}</div>'
            f'<div class="month-card-name">{MONTH_ZH[g["month"]]}</div>'
            f'<div class="month-card-count">{g["count"]}篇</div>'
            f'</div>\n'
        )
        rows = "\n".join(make_row(i) for i in g["items"])
        month_panels += (
            f'<div class="month-panel" id="panel-{g["key"]}">'
            f'<div class="month-panel-header">'
            f'<span class="month-panel-title">{g["label"]}</span>'
            f'<button class="month-panel-close" onclick="toggleMonth(\'{g["key"]}\')">✕ 收起</button>'
            f'</div>{rows}</div>\n'
        )

    today_animal = MONTH_ANIMALS[today.month][today.weekday()]
    today_info   = infos[0] if infos else None
    cta_href     = today_info["filename"] if today_info else "#"

    # Weekday EN abbreviation
    wd_en = ["MON","TUE","WED","THU","FRI","SAT","SUN"]

    def make_row_new(item):
        wd = wd_en[item["date"].weekday()]
        return (
            f'<a href="{item["filename"]}" class="brief-row">'
            f'<div class="brief-date-block">'
            f'<div class="bdb-day">{item["day"]}</div>'
            f'<div class="bdb-wd">{wd}</div>'
            f'</div>'
            f'<div class="brief-text">'
            f'<div class="brief-info-title">{item["headline"]}</div>'
            f'<div class="brief-info-sub">{item["sub"]}</div>'
            f'</div>'
            f'<div class="brief-row-arrow">›</div>'
            f'</a>'
        )

    recent_rows_new = "\n".join(make_row_new(i) for i in infos if i["is_recent"])
    if not recent_rows_new:
        recent_rows_new = '<div class="empty-hint">尚無近期簡報</div>'

    # Featured card (today)
    featured_date_zh = f"{today_info['year']}年{today_info['month']}月{today_info['day']}日 · 星期{today_info['weekday_zh']}" if today_info else ""
    featured_headline = today_info['headline'] if today_info else ""
    featured_animal2  = MONTH_ANIMALS[today.month][today.weekday()]

    # Month panels new style
    month_panels_new = ""
    for g in month_groups:
        rows = "\n".join(make_row_new(i) for i in g["items"])
        month_panels_new += (
            f'<div class="month-panel" id="panel-{g["key"]}">'
            f'<div class="mp-head">'
            f'<div class="mp-title">{g["label"]}</div>'
            f'<button class="mp-close" onclick="toggleMonth(\'{g["key"]}\')">✕ 收起</button>'
            f'</div>'
            f'<div class="mp-rows">{rows}</div>'
            f'</div>\n'
        )

    brief_total   = sum(g["count"] for g in month_groups)
    current_label = f"{today.year}年{today.month}月"

    yuzu_logo_index = """<svg width="34" height="34" viewBox="0 0 34 34" fill="none">
      <defs><radialGradient id="lgi" cx="38%" cy="28%" r="72%"><stop offset="0%" stop-color="#f0d050"/><stop offset="100%" stop-color="#a06010"/></radialGradient></defs>
      <circle cx="17" cy="17" r="17" fill="url(#lgi)"/>
      <circle cx="17" cy="17" r="11.5" fill="none" stroke="rgba(255,255,255,.45)" stroke-width="1.2"/>
      <circle cx="17" cy="17" r="2.8" fill="rgba(255,255,255,.75)"/>
      <line x1="17" y1="14.2" x2="10.5" y2="7.5" stroke="rgba(255,255,255,.7)" stroke-width="1.4" stroke-linecap="round"/>
      <line x1="17" y1="14.2" x2="23.5" y2="7.5" stroke="rgba(255,255,255,.7)" stroke-width="1.4" stroke-linecap="round"/>
      <line x1="17" y1="14.2" x2="17"   y2="23"  stroke="rgba(255,255,255,.7)" stroke-width="1.4" stroke-linecap="round"/>
      <line x1="17" y1="5.5"  x2="17"   y2="14.2" stroke="rgba(255,255,255,.2)" stroke-width="1" stroke-linecap="round"/>
      <line x1="6.8" y1="22.5" x2="12.5" y2="18.5" stroke="rgba(255,255,255,.2)" stroke-width="1" stroke-linecap="round"/>
      <line x1="27.2" y1="22.5" x2="21.5" y2="18.5" stroke="rgba(255,255,255,.2)" stroke-width="1" stroke-linecap="round"/>
    </svg>"""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Yuzu Brief — 每日簡報</title>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,400&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
    :root {{ --bg:#f2ede4; --bg2:#e9e3d8; --navy:#1b2d4f; --navy2:#0f1d34; --ink:#0f172a; --ink2:#374151; --ink3:#94a3b8; --border:#dcd5c4; --gold:#b8922e; --gold-l:#e8c84a; }}
    body {{ background:var(--bg); font-family:'DM Sans','Noto Sans TC',sans-serif; color:var(--ink); min-height:100vh; }}
    .topnav {{ height:56px; padding:0 32px; background:rgba(242,237,228,.93); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px); border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:200; }}
    .tn-brand {{ display:flex; align-items:center; gap:11px; text-decoration:none; }}
    .tn-name {{ font-size:15px; font-weight:700; color:var(--ink); }}
    .tn-sub  {{ font-size:9px; color:var(--ink3); letter-spacing:.12em; text-transform:uppercase; margin-top:1px; }}
    .tn-fin  {{ font-size:12px; color:var(--ink3); text-decoration:none; letter-spacing:.04em; transition:color .15s; }}
    .tn-fin:hover {{ color:var(--ink); }}
    .hero {{ background:var(--navy2); padding:0 32px; position:relative; overflow:hidden; }}
    .hero-bg-text {{ position:absolute; bottom:-20px; left:-10px; font-family:'Playfair Display',serif; font-size:clamp(120px,20vw,200px); font-weight:900; color:rgba(255,255,255,.03); line-height:1; letter-spacing:-.04em; pointer-events:none; user-select:none; white-space:nowrap; }}
    .hero-circles {{ position:absolute; top:-100px; right:-100px; width:480px; height:480px; pointer-events:none; }}
    .hero-inner {{ max-width:700px; margin:0 auto; padding:52px 0 0; display:grid; grid-template-columns:1fr auto; gap:20px; align-items:flex-start; position:relative; z-index:1; }}
    .hero-eyebrow {{ font-size:9px; font-weight:600; letter-spacing:.22em; text-transform:uppercase; color:rgba(255,255,255,.28); margin-bottom:14px; display:flex; align-items:center; gap:10px; }}
    .hero-eyebrow::before {{ content:''; width:16px; height:1px; background:rgba(255,255,255,.2); flex-shrink:0; }}
    .hero-title {{ font-family:'Playfair Display',serif; font-size:clamp(30px,6vw,52px); font-weight:900; color:#fff; line-height:1.05; letter-spacing:-.03em; margin-bottom:20px; }}
    .hero-title em {{ font-style:italic; color:rgba(255,255,255,.55); }}
    .hero-cta {{ display:inline-flex; align-items:center; gap:10px; background:linear-gradient(135deg,rgba(201,168,76,.25),rgba(201,168,76,.1)); border:1.5px solid rgba(201,168,76,.4); color:rgba(255,255,255,.85); text-decoration:none; padding:11px 24px; border-radius:30px; font-size:13px; font-weight:600; transition:all .2s; }}
    .hero-cta:hover {{ background:linear-gradient(135deg,rgba(201,168,76,.35),rgba(201,168,76,.18)); transform:translateY(-1px); }}
    .hero-animal {{ width:100px; height:100px; flex-shrink:0; background:rgba(255,255,255,.07); border:1.5px solid rgba(255,255,255,.13); border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:56px; line-height:1; margin-top:6px; }}
    @media(max-width:440px){{ .hero-animal {{ display:none; }} }}
    .hero-bottom {{ max-width:700px; margin:0 auto; border-top:1px solid rgba(255,255,255,.07); padding:14px 0; display:flex; align-items:center; justify-content:space-between; position:relative; z-index:1; }}
    .hero-bottom::before {{ content:''; position:absolute; top:0; left:0; right:60%; height:1px; background:linear-gradient(90deg,rgba(201,168,76,.5),transparent); }}
    .hb-stat {{ font-size:10px; color:rgba(255,255,255,.3); letter-spacing:.08em; }}
    .hb-stat strong {{ color:rgba(255,255,255,.6); }}
    .content {{ max-width:700px; margin:0 auto; padding:32px 32px 80px; }}
    .featured {{ background:var(--navy); border-radius:20px; overflow:hidden; margin-bottom:20px; text-decoration:none; color:inherit; display:grid; grid-template-columns:1fr auto; transition:transform .2s,box-shadow .2s; box-shadow:0 4px 24px rgba(15,29,52,.18); }}
    .featured:hover {{ transform:translateY(-3px); box-shadow:0 12px 40px rgba(15,29,52,.28); }}
    .featured-body {{ padding:28px 32px; }}
    .featured-eyebrow {{ font-size:9px; font-weight:700; letter-spacing:.18em; text-transform:uppercase; color:rgba(201,168,76,.8); margin-bottom:12px; display:flex; align-items:center; gap:8px; }}
    .featured-eyebrow::before {{ content:''; width:14px; height:1px; background:rgba(201,168,76,.5); }}
    .featured-date {{ font-family:'Playfair Display',serif; font-size:clamp(20px,3.5vw,28px); font-weight:700; color:#fff; margin-bottom:10px; line-height:1.2; }}
    .featured-headline {{ font-size:13px; line-height:1.7; color:rgba(255,255,255,.5); display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
    .featured-tag {{ margin-top:16px; display:inline-flex; align-items:center; gap:6px; font-size:11px; font-weight:600; color:rgba(201,168,76,.9); letter-spacing:.04em; }}
    .featured-side {{ background:rgba(255,255,255,.04); border-left:1px solid rgba(255,255,255,.06); padding:28px 24px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; min-width:80px; }}
    .featured-animal {{ font-size:40px; line-height:1; }}
    .featured-weekday {{ font-size:10px; color:rgba(255,255,255,.3); letter-spacing:.08em; text-transform:uppercase; }}
    .section-head {{ display:flex; align-items:center; gap:12px; margin-bottom:18px; }}
    .sh-label {{ font-size:10px; font-weight:700; letter-spacing:.16em; text-transform:uppercase; color:var(--ink3); }}
    .sh-rule  {{ flex:1; height:1px; background:var(--border); }}
    .brief-list {{ display:flex; flex-direction:column; gap:2px; }}
    .brief-row {{ display:grid; grid-template-columns:56px 1fr 20px; align-items:center; gap:16px; padding:14px 16px; border-radius:12px; text-decoration:none; color:inherit; background:#fff; border:1px solid var(--border); transition:all .15s; }}
    .brief-row:hover {{ background:#faf7f2; border-color:var(--navy); transform:translateX(3px); }}
    .brief-date-block {{ display:flex; flex-direction:column; align-items:center; }}
    .bdb-day {{ font-family:'Playfair Display',serif; font-size:28px; font-weight:900; line-height:1; color:var(--navy); letter-spacing:-.02em; }}
    .bdb-wd  {{ font-size:9px; color:var(--ink3); letter-spacing:.08em; text-transform:uppercase; margin-top:1px; }}
    .brief-text {{ min-width:0; }}
    .brief-info-title {{ font-size:14px; font-weight:600; color:var(--ink); line-height:1.4; margin-bottom:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .brief-info-sub   {{ font-size:11px; color:var(--ink3); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .brief-row-arrow  {{ color:var(--border); font-size:18px; transition:color .15s,transform .15s; }}
    .brief-row:hover .brief-row-arrow {{ color:var(--navy); transform:translateX(2px); }}
    .month-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
    .month-card {{ border-radius:16px; padding:20px 16px 16px; cursor:pointer; position:relative; overflow:hidden; transition:transform .18s,box-shadow .18s; border:1.5px solid transparent; }}
    .month-card.m1  {{ background:linear-gradient(145deg,#263c55,#162535); }}
    .month-card.m2  {{ background:linear-gradient(145deg,#44224a,#2c1532); }}
    .month-card.m3  {{ background:linear-gradient(145deg,#224530,#142c1e); }}
    .month-card.m4  {{ background:linear-gradient(145deg,#364820,#202e12); }}
    .month-card.m5  {{ background:linear-gradient(145deg,#4a2c18,#30190c); }}
    .month-card.m6  {{ background:linear-gradient(145deg,#184444,#0e2c2c); }}
    .month-card.m7  {{ background:linear-gradient(145deg,#1a2c6a,#0e1a48); }}
    .month-card.m8  {{ background:linear-gradient(145deg,#483010,#301f08); }}
    .month-card.m9  {{ background:linear-gradient(145deg,#4a2e22,#301c14); }}
    .month-card.m10 {{ background:linear-gradient(145deg,#4c2418,#34160e); }}
    .month-card.m11 {{ background:linear-gradient(145deg,#383228,#24201a); }}
    .month-card.m12 {{ background:linear-gradient(145deg,#1e3850,#121f30); }}
    .month-card:hover {{ transform:translateY(-3px); box-shadow:0 10px 30px rgba(15,29,52,.35); }}
    .month-card.active {{ border-color:rgba(201,168,76,.5); }}
    .month-card--current {{ filter:brightness(1.25) !important; }}
    .month-card-ongoing {{ display:inline-flex; align-items:center; gap:5px; background:rgba(110,211,130,.15); border:1px solid rgba(110,211,130,.35); border-radius:20px; padding:3px 10px; font-size:9px; font-weight:700; color:#7de89a; margin-bottom:10px; letter-spacing:.06em; }}
    .month-card-ongoing::before {{ content:''; width:5px; height:5px; border-radius:50%; background:#7de89a; animation:pulse 1.5s ease-in-out infinite; flex-shrink:0; }}
    @keyframes pulse {{ 0%,100%{{opacity:1;}} 50%{{opacity:.3;}} }}
    .month-card-animal {{ font-size:26px; line-height:1; margin-bottom:8px; }}
    .month-card-year   {{ font-size:10px; color:rgba(255,255,255,.38); letter-spacing:.08em; }}
    .month-card-name   {{ font-family:'Playfair Display',serif; font-size:20px; font-weight:700; color:#fff; margin:4px 0 3px; }}
    .month-card-count  {{ font-size:11px; color:rgba(255,255,255,.38); }}
    .month-panel {{ display:none; border-radius:14px; overflow:hidden; margin-top:10px; border:1px solid var(--border); background:#fff; }}
    .month-panel.open {{ display:block; }}
    .mp-head {{ display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid var(--border); background:var(--navy); }}
    .mp-title {{ font-size:14px; font-weight:700; color:#fff; }}
    .mp-close {{ background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.15); border-radius:20px; cursor:pointer; font-size:11px; color:rgba(255,255,255,.6); padding:4px 12px; transition:background .12s; }}
    .mp-close:hover {{ background:rgba(255,255,255,.2); }}
    .mp-rows {{ padding:10px 12px; display:flex; flex-direction:column; gap:2px; }}
    .site-footer {{ max-width:700px; margin:0 auto; padding:20px 32px 48px; border-top:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; }}
    .sf-brand {{ display:flex; align-items:center; gap:10px; }}
    .sf-name  {{ font-size:12px; font-weight:600; color:var(--ink3); }}
    .sf-links {{ display:flex; gap:18px; }}
    .sf-links a {{ font-size:12px; color:var(--ink3); text-decoration:none; transition:color .15s; }}
    .sf-links a:hover {{ color:var(--ink); }}
    .empty-hint {{ color:#bbb; font-size:13px; padding:16px 8px; }}

    /* FAB dock */
    .fab-dock {{ position:fixed; bottom:28px; right:28px; z-index:999; display:flex; flex-direction:column; align-items:flex-end; gap:10px; }}
    .yuzu-fab {{ display:flex; align-items:center; gap:12px; background:linear-gradient(135deg,#bf9618 0%,#f5e264 42%,#c8a020 100%); color:#1b2d4f; text-decoration:none; padding:10px 18px 10px 10px; border-radius:50px; font-family:'DM Sans','Noto Sans TC',sans-serif; box-shadow:0 2px 0 rgba(255,255,255,.4) inset,0 6px 24px rgba(160,122,18,.55),0 2px 5px rgba(0,0,0,.14); transition:transform .25s cubic-bezier(.34,1.56,.64,1),box-shadow .25s; animation:fab-glow 3s ease-in-out infinite; }}
    .yuzu-fab:hover {{ transform:translateY(-4px) scale(1.04); box-shadow:0 2px 0 rgba(255,255,255,.4) inset,0 14px 40px rgba(160,122,18,.72),0 2px 8px rgba(0,0,0,.18); animation:none; }}
    .yuzu-fab-cam {{ display:flex; align-items:center; gap:12px; background:linear-gradient(145deg,#2d2d2d 0%,#1e1e1e 55%,#141414 100%); color:rgba(255,255,255,.93); text-decoration:none; padding:10px 18px 10px 10px; border-radius:50px; font-family:'DM Sans','Noto Sans TC',sans-serif; box-shadow:0 1px 0 rgba(255,255,255,.1) inset,0 6px 22px rgba(0,0,0,.45),0 2px 6px rgba(0,0,0,.2); border:1px solid rgba(255,255,255,.1); transition:transform .25s cubic-bezier(.34,1.56,.64,1),box-shadow .25s; }}
    .yuzu-fab-cam:hover {{ transform:translateY(-4px) scale(1.04); box-shadow:0 1px 0 rgba(255,255,255,.16) inset,0 14px 38px rgba(0,0,0,.6),0 2px 8px rgba(0,0,0,.28); color:#fff; border-color:rgba(255,255,255,.2); }}
    .yuzu-fab-icon {{ flex-shrink:0; width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; }}
    .yuzu-fab-cam .yuzu-fab-icon {{ background:rgba(255,255,255,.1); }}
    .yuzu-fab .yuzu-fab-icon {{ background:rgba(27,45,79,.16); }}
    .yuzu-fab-text {{ display:flex; flex-direction:column; line-height:1; }}
    .yuzu-fab-name {{ font-size:13px; font-weight:800; letter-spacing:.01em; }}
    .yuzu-fab-sub  {{ font-size:9px; font-weight:600; opacity:.55; letter-spacing:.12em; text-transform:uppercase; margin-top:3px; }}
    .yuzu-fab-arr  {{ font-size:16px; font-weight:300; opacity:.45; margin-left:4px; transition:transform .2s,opacity .2s; }}
    .yuzu-fab:hover .yuzu-fab-arr, .yuzu-fab-cam:hover .yuzu-fab-arr {{ transform:translateX(3px); opacity:.9; }}
    @keyframes fab-glow {{
      0%,100% {{ box-shadow:0 2px 0 rgba(255,255,255,.4) inset,0 6px 24px rgba(160,122,18,.55),0 2px 5px rgba(0,0,0,.14); }}
      50%      {{ box-shadow:0 2px 0 rgba(255,255,255,.4) inset,0 6px 42px rgba(160,122,18,.82),0 2px 5px rgba(0,0,0,.14); }}
    }}
  </style>
</head>
<body>
<nav class="topnav">
  <div class="tn-brand">
    {yuzu_logo_index}
    <div><div class="tn-name">Yuzu Brief</div><div class="tn-sub">Daily News</div></div>
  </div>
  <a class="tn-fin" href="{DASHBOARD_URL}" target="_blank">Yuzu Finance →</a>
</nav>
<div class="hero">
  <div class="hero-bg-text">YUZU</div>
  <svg class="hero-circles" viewBox="0 0 480 480" fill="none">
    <circle cx="380" cy="100" r="200" stroke="rgba(255,255,255,.04)" stroke-width="1"/>
    <circle cx="380" cy="100" r="130" stroke="rgba(255,255,255,.05)" stroke-width="1"/>
    <circle cx="380" cy="100" r="60"  stroke="rgba(201,168,76,.08)"  stroke-width="1"/>
    <line x1="380" y1="100" x2="220" y2="240" stroke="rgba(255,255,255,.03)" stroke-width="1"/>
    <line x1="380" y1="100" x2="540" y2="240" stroke="rgba(255,255,255,.03)" stroke-width="1"/>
    <line x1="380" y1="100" x2="380" y2="280" stroke="rgba(255,255,255,.03)" stroke-width="1"/>
  </svg>
  <div class="hero-inner">
    <div>
      <div class="hero-eyebrow">Yuzu Brief · Daily News</div>
      <div class="hero-title">用五分鐘<br><em>掌握今天的世界</em></div>
      <a href="{cta_href}" class="hero-cta">閱讀今日簡報 →</a>
    </div>
    <div class="hero-animal">{today_animal}</div>
  </div>
  <div class="hero-bottom">
    <div class="hb-stat">共 <strong>{brief_total}</strong> 篇簡報 · <strong>{current_label}</strong></div>
    <div class="hb-stat">每天早上 09:00 更新</div>
  </div>
</div>
<div class="content">
  <a href="{cta_href}" class="featured">
    <div class="featured-body">
      <div class="featured-eyebrow">今日簡報</div>
      <div class="featured-date">{featured_date_zh}</div>
      <div class="featured-headline">{featured_headline}</div>
      <div class="featured-tag">立即閱讀 →</div>
    </div>
    <div class="featured-side">
      <div class="featured-animal">{featured_animal2}</div>
      <div class="featured-weekday">今日</div>
    </div>
  </a>
  <div class="section-head" style="margin-top:32px;">
    <div class="sh-label">最近 14 天</div><div class="sh-rule"></div>
  </div>
  <div class="brief-list">{recent_rows_new}</div>
  <div class="section-head" style="margin-top:40px;">
    <div class="sh-label">歷史簡報</div><div class="sh-rule"></div>
  </div>
  <div class="month-grid">
{month_cards}
  </div>
{month_panels_new}
</div>
<footer class="site-footer">
  <div class="sf-brand">{yuzu_logo_index}<div class="sf-name">Yuzu Brief</div></div>
  <div class="sf-links"><a href="{DASHBOARD_URL}" target="_blank">Yuzu Finance →</a></div>
</footer>

<!-- FAB dock -->
<div class="fab-dock">
  <a class="yuzu-fab-cam" href="{PHOTOSHOP_URL}" target="_blank">
    <div class="yuzu-fab-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg></div>
    <div class="yuzu-fab-text">
      <div class="yuzu-fab-name">Yuzu Photoshop</div>
      <div class="yuzu-fab-sub">圖片風格工具</div>
    </div>
    <div class="yuzu-fab-arr">›</div>
  </a>
  <a class="yuzu-fab" href="{DASHBOARD_URL}" target="_blank">
    <div class="yuzu-fab-icon"><svg width="24" height="24" viewBox="0 0 34 34" fill="none"><defs><radialGradient id="fg2" cx="38%" cy="28%" r="72%"><stop offset="0%" stop-color="#fffbe8"/><stop offset="100%" stop-color="#7a4800"/></radialGradient></defs><circle cx="17" cy="17" r="17" fill="url(#fg2)"/><circle cx="17" cy="17" r="11.5" fill="none" stroke="rgba(27,45,79,.3)" stroke-width="1.2"/><circle cx="17" cy="17" r="2.8" fill="rgba(27,45,79,.6)"/><line x1="17" y1="14.2" x2="10.5" y2="7.5" stroke="rgba(27,45,79,.7)" stroke-width="1.4" stroke-linecap="round"/><line x1="17" y1="14.2" x2="23.5" y2="7.5" stroke="rgba(27,45,79,.7)" stroke-width="1.4" stroke-linecap="round"/><line x1="17" y1="14.2" x2="17" y2="23" stroke="rgba(27,45,79,.7)" stroke-width="1.4" stroke-linecap="round"/></svg></div>
    <div class="yuzu-fab-text">
      <div class="yuzu-fab-name">Yuzu Finance</div>
      <div class="yuzu-fab-sub">投資儀表板</div>
    </div>
    <div class="yuzu-fab-arr">›</div>
  </a>
</div>

<script>
  var activeMonth = null;
  function toggleMonth(key) {{
    var card  = document.querySelector('.month-card[data-month="' + key + '"]');
    var panel = document.getElementById('panel-' + key);
    if (!card || !panel) return;
    if (activeMonth && activeMonth !== key) {{
      var pc = document.querySelector('.month-card[data-month="' + activeMonth + '"]');
      var pp = document.getElementById('panel-' + activeMonth);
      if (pc) pc.classList.remove('active');
      if (pp) pp.classList.remove('open');
    }}
    var isOpen = panel.classList.contains('open');
    card.classList.toggle('active', !isOpen);
    panel.classList.toggle('open', !isOpen);
    activeMonth = isOpen ? null : key;
    if (!isOpen) setTimeout(function() {{ panel.scrollIntoView({{ behavior:'smooth', block:'nearest' }}); }}, 50);
  }}
</script>
</body>
</html>"""


# ════════════════════════════════════════════════════════════════════
# Backfill：把所有舊版 HTML 套上新設計（一次性補跑）
# ════════════════════════════════════════════════════════════════════
def backfill_all(repo_dir="."):
    """解析所有現有 YYYY-MM-DD.html 的內容，用新版模板重新輸出"""
    files = sorted(
        [f for f in os.listdir(repo_dir) if re.match(r"^\d{4}-\d{2}-\d{2}\.html$", f)]
    )
    print(f"🔄 Backfill 開始，共 {len(files)} 個檔案")
    ok = skip = 0

    for filename in files:
        filepath = os.path.join(repo_dir, filename)
        date_str = filename[:10]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ_TW)
            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            # 嘗試解析新版（ni-title / ni-text）或舊版（news-title / news-body）
            titles = re.findall(r'class="ni-title">(.*?)</div>', content, re.DOTALL)
            bodies = re.findall(r'class="ni-text">(.*?)</div>', content, re.DOTALL)
            if not titles:
                titles = re.findall(r'class="news-title">(.*?)</div>', content, re.DOTALL)
                bodies = re.findall(r'class="news-body">(.*?)</div>', content, re.DOTALL)

            fact_titles = re.findall(r'class="fact-title">(.*?)</div>', content, re.DOTALL)
            fact_bodies = re.findall(r'class="fact-body">(.*?)</div>', content, re.DOTALL)

            if len(titles) < 3 or not fact_titles:
                print(f"  ⚠ {filename} 內容不足，略過")
                skip += 1
                continue

            news = [{"title": t.strip(), "body": b.strip()}
                    for t, b in zip(titles[:5], bodies[:5])]
            data = {"news": news, "fact": {"title": fact_titles[0].strip(),
                                           "body": fact_bodies[0].strip() if fact_bodies else ""}}

            new_html = build_brief_html(data, dt)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_html)
            print(f"  ✓ {filename}")
            ok += 1

        except Exception as e:
            print(f"  ✗ {filename} 失敗：{e}")
            skip += 1

    print(f"✅ Backfill 完成：{ok} 個更新，{skip} 個略過")


# ════════════════════════════════════════════════════════════════════
# 主程式
# ════════════════════════════════════════════════════════════════════
def main():
    # 若設定 BACKFILL=true，只補跑舊文章設計，不呼叫 Gemini
    if os.environ.get("BACKFILL") == "true":
        backfill_all(".")
        index_html = build_index_html(".")
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(index_html)
        print("  ✓ index.html 已重建")
        return

    now      = datetime.now(TZ_TW)
    dt       = now.date()
    date_str = dt.strftime("%Y-%m-%d")
    weekday  = WEEKDAY_ZH[dt.weekday()]

    print(f"📰 {date_str}（星期{weekday}）每日簡報生成開始")

    used_facts_state = load_used_facts()
    used_count = len(used_facts_state.get("facts", []))
    print(f"  📚 歷史冷知識紀錄：{used_count} 筆（生成時將全部排除）")

    print("  呼叫 Gemini + Google Search...")
    data = fetch_news(date_str, weekday, used_facts_state)
    fact_title = data['fact']['title']
    print(f"  ✓ 取得 {len(data['news'])} 則新聞，冷知識：{fact_title[:25]}…")

    html_file  = f"{date_str}.html"
    brief_html = build_brief_html(data, now)
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(brief_html)
    print(f"  ✓ {html_file} 已生成")

    save_used_fact(used_facts_state, date_str, fact_title)
    print(f"  ✓ brief_state.json 已更新（共 {used_count + 1} 筆冷知識紀錄）")

    index_html = build_index_html(".")
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(index_html)
    brief_count = len([ff for ff in os.listdir('.') if re.match(r'^\d{4}-\d{2}-\d{2}\.html$', ff)])
    print(f"  ✓ index.html 已重建（掃描 {brief_count} 份簡報）")

    print(f"✅ 完成！今日動物：{MONTH_ANIMALS[dt.month][dt.weekday()]}")


if __name__ == "__main__":
    main()
