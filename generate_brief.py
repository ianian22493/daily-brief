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


# ════════════════════════════════════════════════════════════════════
# Gemini — 搜尋並生成新聞內容
# ════════════════════════════════════════════════════════════════════
def fetch_news(date_str, weekday_zh):
    """呼叫 Gemini（含 Google Search grounding）生成當日新聞 JSON"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("未設定環境變數 GEMINI_API_KEY")

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)

    # 診斷：列出可用模型（找到正確名稱後可移除）
    try:
        models = client.models.list()
        flash_models = [m.name for m in models if "flash" in m.name.lower()]
        print(f"  📋 可用 flash 模型：{flash_models[:10]}")
    except Exception as e:
        print(f"  ⚠ 無法列出模型：{e}")

    prompt = f"""今天是 {date_str}（星期{weekday_zh}）。

你是繁體中文新聞編輯，請搜尋今天（{date_str}）最新的國際新聞，撰寫每日簡報。

任務：
1. 選出今天最重要的 5 則全球新聞（涵蓋政治、衝突、經濟、社會、科技，優先選有即時新聞的）
2. 撰寫 1 則有趣的冷知識（科學、歷史、自然等皆可）

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
        """帶重試的 generate_content，503 最多重試 3 次"""
        for attempt in range(3):
            try:
                if config:
                    resp = client.models.generate_content(
                        model=model, contents=contents, config=config)
                else:
                    resp = client.models.generate_content(
                        model=model, contents=contents)
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

    # 嘗試 1：gemini-2.5-flash + Google Search grounding
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

    # 嘗試 2：gemini-2.5-flash-lite（更輕量，較少擁塞）
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

    # 嘗試 3：gemini-2.5-flash 無搜尋（最後手段）
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

    # 清除 markdown code block 包裝
    text = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"^```\s*",     "", text,          flags=re.MULTILINE)
    text = text.strip()

    # 取第一個 JSON 物件（防止 grounding metadata 混入）
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group()

    return json.loads(text)


# ════════════════════════════════════════════════════════════════════
# HTML 生成：單日 brief 頁面
# ════════════════════════════════════════════════════════════════════
DASHBOARD_URL = "https://ianian22493.github.io/investment-dashboard/"

def build_brief_html(data, dt):
    date_str = dt.strftime("%Y-%m-%d")
    date_zh  = f"{dt.year}年{dt.month}月{dt.day}日"
    weekday  = WEEKDAY_ZH[dt.weekday()]
    animal   = MONTH_ANIMALS[dt.month][dt.weekday()]

    news_html = ""
    for i, item in enumerate(data["news"][:5], 1):
        news_html += f"""
        <div class="news-item">
          <div class="news-number">{i}</div>
          <div class="news-content">
            <div class="news-title">{item['title']}</div>
            <div class="news-body">{item['body']}</div>
          </div>
        </div>"""

    fact = data["fact"]

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>每日簡報｜{date_zh}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: #f0ede8; font-family: -apple-system,"PingFang TC","Noto Sans TC","Microsoft JhengHei",sans-serif; color: #1a1a1a; min-height: 100vh; padding: 32px 16px 64px; }}
    .container {{ max-width: 680px; margin: 0 auto; }}
    .header {{ background: #1b2d4f; border-radius: 16px 16px 0 0; padding: 34px 40px 28px; position: relative; overflow: hidden; }}
    .header::before {{ content:''; position:absolute; top:-60px; right:-60px; width:220px; height:220px; border-radius:50%; background:rgba(255,255,255,0.04); pointer-events:none; }}
    .animal-badge {{ position:absolute; top:22px; right:26px; width:82px; height:82px; background:rgba(255,255,255,0.09); border:1.5px solid rgba(255,255,255,0.14); border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:50px; line-height:1; }}
    .header-text {{ padding-right: 100px; }}
    .date-main {{ font-size:28px; font-weight:700; color:#fff; line-height:1.2; letter-spacing:-0.01em; white-space:nowrap; }}
    .weekday-row {{ margin-top:10px; }}
    .weekday-badge {{ display:inline-block; background:rgba(255,255,255,0.13); border:1px solid rgba(255,255,255,0.18); border-radius:20px; padding:3px 13px; font-size:13px; font-weight:600; color:rgba(255,255,255,0.72); letter-spacing:0.05em; }}
    .header-divider {{ height:1px; background:rgba(255,255,255,0.1); margin:16px 0 12px; }}
    .header-tagline {{ font-size:13px; color:rgba(255,255,255,0.36); letter-spacing:0.04em; }}
    .body-card {{ background:#fff; border-radius:0 0 16px 16px; padding:36px 40px 40px; box-shadow:0 8px 40px rgba(0,0,0,0.08); }}
    .section {{ margin-bottom:40px; }}
    .section:last-child {{ margin-bottom:0; }}
    .section-header {{ display:flex; align-items:center; gap:10px; margin-bottom:22px; padding-bottom:14px; border-bottom:1.5px solid #f0ede8; }}
    .section-icon {{ font-size:18px; line-height:1; }}
    .section-title {{ font-size:13px; font-weight:700; letter-spacing:0.12em; text-transform:uppercase; color:#888; }}
    .news-item {{ display:flex; gap:18px; padding:18px 0; border-bottom:1px solid #f5f3f0; }}
    .news-item:last-child {{ border-bottom:none; padding-bottom:0; }}
    .news-item:first-child {{ padding-top:0; }}
    .news-number {{ flex-shrink:0; width:28px; height:28px; background:#1b2d4f; color:#fff; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; margin-top:2px; }}
    .news-content {{ flex:1; }}
    .news-title {{ font-size:15px; font-weight:700; line-height:1.4; color:#111; margin-bottom:7px; }}
    .news-body {{ font-size:14px; line-height:1.75; color:#444; }}
    .fact-card {{ background:linear-gradient(135deg,#fffbf0 0%,#fff8e1 100%); border:1.5px solid #ffe082; border-radius:12px; padding:22px 24px; position:relative; overflow:hidden; }}
    .fact-card::before {{ content:'💡'; position:absolute; right:20px; top:16px; font-size:28px; opacity:0.3; }}
    .fact-title {{ font-size:14px; font-weight:700; color:#7a5c00; margin-bottom:8px; }}
    .fact-body {{ font-size:14px; line-height:1.75; color:#5a4200; }}
    .footer {{ text-align:center; margin-top:28px; font-size:12px; color:#bbb; letter-spacing:0.05em; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="animal-badge">{animal}</div>
      <div class="header-text">
        <div class="date-main">{date_zh}</div>
        <div class="weekday-row"><span class="weekday-badge">星期{weekday}</span></div>
        <div class="header-divider"></div>
        <div class="header-tagline">用五分鐘，掌握今天的世界</div>
      </div>
    </div>
    <div class="body-card">
      <div class="section">
        <div class="section-header"><span class="section-icon">🌍</span><span class="section-title">全球五大新聞</span></div>
        {news_html}
      </div>
      <div class="section">
        <div class="section-header"><span class="section-icon">🧠</span><span class="section-title">每日冷知識</span></div>
        <div class="fact-card">
          <div class="fact-title">{fact['title']}</div>
          <div class="fact-body">{fact['body']}</div>
        </div>
      </div>
    </div>
    <div class="footer">
      <a href="index.html" style="color:#bbb;text-decoration:none;">← 返回所有簡報</a> &nbsp;·&nbsp; 柚子 Daily Brief &nbsp;·&nbsp; {date_str}
    </div>
  </div>
</body>
</html>"""


# ════════════════════════════════════════════════════════════════════
# index.html 生成（掃描所有 YYYY-MM-DD.html，重建首頁）
# ════════════════════════════════════════════════════════════════════
def build_index_html(repo_dir):
    today    = datetime.now(TZ_TW).date()
    cutoff   = today - timedelta(days=13)

    # 1. 掃描所有日期檔
    files = sorted(
        [f for f in os.listdir(repo_dir) if re.match(r"^\d{4}-\d{2}-\d{2}\.html$", f)],
        reverse=True
    )

    # 2. 萃取 metadata
    def get_info(filename):
        d = datetime.strptime(filename[:10], "%Y-%m-%d").date()
        headline, sub = "點擊閱讀", ""
        try:
            with open(os.path.join(repo_dir, filename), encoding="utf-8") as f:
                content = f.read()
            titles = re.findall(r'class="news-title">(.*?)</div>', content)
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

    # 3. Brief row HTML
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

    # 4. 月份卡 + panel
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
            f'<div class="month-card{cls}" data-month="{g["key"]}" onclick="toggleMonth(\'{g["key"]}\')">'
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

    # 今日 hero
    today_animal = MONTH_ANIMALS[today.month][today.weekday()]
    today_info   = infos[0] if infos else None
    cta_href     = today_info["filename"] if today_info else "#"
    cta_label    = f"{today_info['headline'][:20]}…" if today_info else "閱讀最新簡報"

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>柚子 Daily Brief</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#f0ede8; font-family:-apple-system,"PingFang TC","Noto Sans TC","Microsoft JhengHei",sans-serif; color:#1a1a1a; min-height:100vh; padding:32px 16px 64px; }}
    .container {{ max-width:680px; margin:0 auto; }}
    /* Hero */
    .hero {{ background:#1b2d4f; border-radius:16px; padding:40px 40px 32px; position:relative; overflow:hidden; margin-bottom:20px; }}
    .hero::before {{ content:''; position:absolute; top:-60px; right:-60px; width:220px; height:220px; border-radius:50%; background:rgba(255,255,255,0.04); pointer-events:none; }}
    .hero-animal {{ position:absolute; top:24px; right:28px; width:82px; height:82px; background:rgba(255,255,255,0.09); border:1.5px solid rgba(255,255,255,0.14); border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:50px; line-height:1; }}
    .hero-title {{ font-size:32px; font-weight:800; color:#fff; line-height:1.1; padding-right:100px; }}
    .hero-sub {{ font-size:14px; color:rgba(255,255,255,0.45); margin-top:8px; padding-right:100px; }}
    .hero-cta {{ display:inline-block; margin-top:24px; background:rgba(255,255,255,0.12); border:1.5px solid rgba(255,255,255,0.2); color:#fff; text-decoration:none; padding:10px 22px; border-radius:30px; font-size:14px; font-weight:600; transition:background .15s; }}
    .hero-cta:hover {{ background:rgba(255,255,255,0.2); }}
    /* Section cards */
    .card {{ background:#fff; border-radius:16px; padding:28px 32px; box-shadow:0 4px 24px rgba(0,0,0,0.06); margin-bottom:16px; }}
    .card-title {{ font-size:12px; font-weight:700; letter-spacing:.1em; color:#999; text-transform:uppercase; margin-bottom:16px; }}
    /* Brief rows */
    .brief-row {{ display:flex; align-items:center; gap:14px; padding:11px 8px; border-bottom:1px solid #f8f6f3; text-decoration:none; color:inherit; border-radius:8px; margin:0 -8px; transition:background .12s; }}
    .brief-row:last-child {{ border-bottom:none; }}
    .brief-row:hover {{ background:#f8f6f2; }}
    .brief-date-badge {{ flex-shrink:0; width:46px; height:46px; background:#1b2d4f; border-radius:10px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#fff; }}
    .badge-day {{ font-size:18px; font-weight:700; line-height:1; }}
    .badge-weekday {{ font-size:10px; color:rgba(255,255,255,0.55); margin-top:2px; }}
    .brief-info {{ flex:1; min-width:0; }}
    .brief-info-title {{ font-size:14px; font-weight:600; color:#111; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .brief-info-sub {{ font-size:12px; color:#999; margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .brief-arrow {{ color:#ccc; font-size:20px; flex-shrink:0; }}
    /* Month grid */
    .month-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
    .month-card {{ background:#4a5e72; border-radius:12px; padding:16px 14px 14px; cursor:pointer; position:relative; overflow:hidden; transition:background .15s, transform .12s, box-shadow .12s; border:2px solid transparent; }}
    .month-card:hover {{ background:#566a7f; transform:translateY(-2px); box-shadow:0 6px 20px rgba(74,94,114,.35); }}
    .month-card.active {{ border-color:#93c5fd; background:#566a7f; }}
    .month-card--current {{ background:#3e5568; }}
    .month-card-ongoing {{ display:inline-flex; align-items:center; gap:4px; background:rgba(110,211,130,.18); border:1px solid rgba(110,211,130,.4); border-radius:20px; padding:2px 8px; font-size:10px; font-weight:700; color:#7de89a; margin-bottom:8px; }}
    .month-card-ongoing::before {{ content:''; display:inline-block; width:5px; height:5px; border-radius:50%; background:#7de89a; animation:pulse 1.5s ease-in-out infinite; }}
    @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.3; }} }}
    .month-card-animal {{ font-size:22px; line-height:1; margin-bottom:6px; }}
    .month-card-year {{ font-size:11px; color:rgba(255,255,255,.5); }}
    .month-card-name {{ font-size:16px; font-weight:700; color:#fff; margin:2px 0; }}
    .month-card-count {{ font-size:11px; color:rgba(255,255,255,.5); }}
    /* Month panel */
    .month-panel {{ display:none; background:#fff; border-radius:12px; padding:16px 20px; margin-top:8px; }}
    .month-panel.open {{ display:block; }}
    .month-panel-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid #f0ede8; }}
    .month-panel-title {{ font-size:14px; font-weight:700; color:#1b2d4f; }}
    .month-panel-close {{ background:none; border:none; cursor:pointer; font-size:12px; color:#999; padding:4px 8px; border-radius:6px; }}
    .month-panel-close:hover {{ background:#f0ede8; }}
    /* Dashboard button */
    .dashboard-btn {{ position:fixed; bottom:24px; right:24px; background:#1b2d4f; color:#fff; text-decoration:none; padding:12px 20px; border-radius:30px; font-size:13px; font-weight:700; box-shadow:0 4px 16px rgba(0,0,0,0.25); transition:background .15s,transform .12s; z-index:999; display:flex; align-items:center; gap:8px; }}
    .dashboard-btn:hover {{ background:#243d6a; transform:translateY(-2px); }}
    .empty-hint {{ color:#bbb; font-size:13px; padding:16px 8px; }}
    .footer {{ text-align:center; margin-top:24px; font-size:12px; color:#bbb; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="hero">
      <div class="hero-animal">{today_animal}</div>
      <div class="hero-title">柚子 Daily Brief</div>
      <div class="hero-sub">每天五分鐘，掌握今天的世界</div>
      <a href="{cta_href}" class="hero-cta">閱讀今日簡報 →</a>
    </div>

    <div class="card">
      <div class="card-title">最近 14 天</div>
      {recent_rows}
    </div>

    <div class="card">
      <div class="card-title">歷史簡報</div>
      <div class="month-grid">
{month_cards}
      </div>
{month_panels}
    </div>

    <div class="footer">柚子 Daily Brief · 由 Gemini AI 生成 · <a href="{DASHBOARD_URL}" style="color:#bbb;">📊 投資儀表板</a></div>
  </div>
  <a href="{DASHBOARD_URL}" class="dashboard-btn" target="_blank">📊 投資儀表板</a>
  <script>
    let activeMonth = null;
    function toggleMonth(key) {{
      const card  = document.querySelector('.month-card[data-month="' + key + '"]');
      const panel = document.getElementById('panel-' + key);
      if (!card || !panel) return;
      if (activeMonth && activeMonth !== key) {{
        document.querySelector('.month-card[data-month="' + activeMonth + '"]')?.classList.remove('active');
        document.getElementById('panel-' + activeMonth)?.classList.remove('open');
      }}
      const isOpen = panel.classList.contains('open');
      card.classList.toggle('active', !isOpen);
      panel.classList.toggle('open', !isOpen);
      activeMonth = isOpen ? null : key;
      if (!isOpen) setTimeout(() => panel.scrollIntoView({{ behavior:'smooth', block:'nearest' }}), 50);
    }}
  </script>
</body>
</html>"""


# ════════════════════════════════════════════════════════════════════
# 主程式
# ════════════════════════════════════════════════════════════════════
def main():
    now      = datetime.now(TZ_TW)
    dt       = now.date()
    date_str = dt.strftime("%Y-%m-%d")
    weekday  = WEEKDAY_ZH[dt.weekday()]

    print(f"📰 {date_str}（星期{weekday}）每日簡報生成開始")

    # 1. 生成新聞內容
    print("  呼叫 Gemini + Google Search...")
    data = fetch_news(date_str, weekday)
    print(f"  ✓ 取得 {len(data['news'])} 則新聞，冷知識：{data['fact']['title'][:20]}…")

    # 2. 寫出今日 HTML
    html_file = f"{date_str}.html"
    brief_html = build_brief_html(data, now)
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(brief_html)
    print(f"  ✓ {html_file} 已生成")

    # 3. 重建 index.html
    index_html = build_index_html(".")
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(index_html)
    brief_count = len([ff for ff in os.listdir('.') if re.match(r'^\d{4}-\d{2}-\d{2}\.html$', ff)])
    print(f"  ✓ index.html 已重建（掃描 {brief_count} 份簡報）")

    print(f"✅ 完成！今日動物：{MONTH_ANIMALS[dt.month][dt.weekday()]}")


if __name__ == "__main__":
    main()
