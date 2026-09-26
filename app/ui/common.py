"""Shared look and feel for every page: styling, footer, friendly errors, and small HTML
building blocks (cards, tags, freshness dots, sparklines, gauges).

Display only: every value shown comes from app/services. Nothing here invents data; when a
value is missing the helpers show "Unknown" or an empty state instead.
"""

import html
import math

import streamlit as st

from app.errors import FriendlyError

APP_NAME = "Pramana"
APP_TAGLINE = "Evidence-first research on Indian stocks"
FOOTER_TEXT = "Personal research tool. Not investment advice."

# Palette (same values as .streamlit/config.toml)
NAVY, BLUE, CYAN, SKY, ICE = "#03045E", "#0077B6", "#00B4D8", "#90E0EF", "#CAF0F8"
INK, INK2, INK3, LINE = "#0A1733", "#34445F", "#5F6F8A", "#E2EAF2"

_CSS = """
<style>
:root{
  --navy:#03045E; --blue:#0077B6; --cyan:#00B4D8; --sky:#90E0EF; --ice:#CAF0F8; --mist:#EEF8FC;
  --bg:#F3F7FB; --card:#FFFFFF; --sunk:#F6F9FC; --line:#E2EAF2; --line2:#D3DEEA;
  --ink:#0A1733; --ink2:#34445F; --ink3:#5F6F8A; --ink4:#AEBBCD;
  --up:#16865A; --upbg:#E4F5EC; --down:#C2412D; --downbg:#FCEBE7; --warn:#A5670B; --warnbg:#FDF3E0;
  --grad:linear-gradient(135deg,#0077B6 0%,#00B4D8 100%);
  --grad-deep:linear-gradient(140deg,#03045E 0%,#0077B6 70%,#00B4D8 130%);
  --shadow:0 1px 2px rgba(3,4,94,.04),0 12px 32px -14px rgba(3,4,94,.16);
  --mono:"JetBrains Mono",ui-monospace,monospace;
}
/* page */
.stApp{background:var(--bg);background-image:radial-gradient(1100px 480px at 75% -220px,rgba(0,180,216,.14),transparent 70%),radial-gradient(800px 400px at -10% 10%,rgba(0,119,182,.06),transparent 70%);background-attachment:fixed}
[data-testid="stHeader"]{background:transparent}
[data-testid="stMainBlockContainer"]{padding-top:2.2rem;padding-bottom:4.5rem;max-width:1320px}
h1{letter-spacing:-.03em}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{color:var(--ink2) !important;font-size:.9rem}
/* sidebar */
[data-testid="stSidebar"]{box-shadow:var(--shadow)}
[data-testid="stSidebarNav"] a{border-radius:12px;padding:.35rem .6rem;margin:1px 0}
[data-testid="stSidebarNav"] a span{color:var(--ink2);font-weight:500}
[data-testid="stSidebarNav"] a:hover{background:var(--mist)}
[data-testid="stSidebarNav"] a[aria-current="page"]{background:var(--grad);box-shadow:0 8px 18px -10px rgba(0,119,182,.8)}
[data-testid="stSidebarNav"] a[aria-current="page"] span{color:#fff !important}
[data-testid="stNavSectionHeader"],[data-testid="stNavSectionHeader"] span{font-family:var(--mono);font-size:11px !important;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--ink3) !important}
/* cards: any st.container(border=True, key="card-...") */
[class*="st-key-card"]{background:var(--card) !important;border:1px solid var(--line) !important;border-radius:22px !important;box-shadow:var(--shadow);padding:1.15rem 1.3rem !important}
[class*="st-key-cardsub"]{background:var(--sunk) !important;box-shadow:none;border-radius:18px !important;padding:1rem !important}
/* alerts become soft banners */
[data-testid="stAlertContainer"]{border-radius:16px;border:1px solid transparent}
/* buttons */
[data-testid="stBaseButton-primary"]{background:var(--grad);border:0;box-shadow:0 10px 20px -10px rgba(0,119,182,.9)}
[data-testid="stBaseButton-primary"]:hover{filter:brightness(1.06)}
[data-testid="stBaseButton-secondary"]{background:#fff;box-shadow:0 1px 2px rgba(3,4,94,.05)}
/* tabs as a segmented control */
[data-testid="stTabs"] [role="tablist"]{gap:4px;background:var(--sunk);border:1px solid var(--line);border-radius:14px;padding:4px;width:max-content;max-width:100%;border-bottom:1px solid var(--line)}
[data-testid="stTab"]{border-radius:10px;padding:6px 14px !important;height:auto;margin:0}
[data-testid="stTab"] p{color:var(--ink2);font-weight:500}
[data-testid="stTab"][data-selected="true"]{background:#fff;box-shadow:0 1px 4px rgba(3,4,94,.12)}
[data-testid="stTab"][data-selected="true"] p{color:var(--blue)}
[data-testid="stTabs"] .react-aria-SelectionIndicator{display:none}
/* page links look like quiet links */
[data-testid="stPageLink"] a{padding:.15rem 0}
[data-testid="stPageLink"] a span{color:var(--blue);font-weight:500}
[data-testid="stExpander"] details{border-radius:16px;background:#fff}
/* building blocks */
.pm-crumb{font:500 12px var(--mono);color:var(--ink3);letter-spacing:.05em;text-transform:uppercase;margin-bottom:-.6rem}
.pm-sub{color:var(--ink2);font-size:15px;margin-top:-.5rem}
.pm-meta{font:400 12.5px var(--mono);color:var(--ink3)}
.pm-num{font-feature-settings:"tnum"}
.pm-ct{font-weight:650;font-size:15.5px;letter-spacing:-.01em;display:flex;align-items:center;gap:9px;color:var(--ink)}
.pm-ico{width:28px;height:28px;border-radius:9px;background:var(--mist);color:var(--blue);display:inline-grid;place-items:center;flex:none}
.pm-ico svg{width:15px;height:15px}
.pm-cs{color:var(--ink2);font-size:13.5px;margin-top:3px}
.pm-head{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;margin-bottom:.35rem}
.pm-head>div:first-child{min-width:0;flex:1 1 200px}
.pm-tag{display:inline-flex;align-items:center;gap:5px;border-radius:8px;padding:2px 9px;font-weight:500;font-size:12px;white-space:nowrap;line-height:1.6}
.pm-blue{background:#E3F2FB;color:#0B5E91}.pm-cyan{background:var(--mist);color:#067C96}.pm-navy{background:#E6E7F6;color:var(--navy)}
.pm-green{background:var(--upbg);color:var(--up)}.pm-red{background:var(--downbg);color:var(--down)}
.pm-orange{background:var(--warnbg);color:var(--warn)}.pm-gray{background:#EEF1F5;color:var(--ink2)}
.pm-pill{display:inline-flex;align-items:center;gap:4px;border-radius:8px;padding:2px 8px;font:600 12px var(--mono);white-space:nowrap}
.pm-fresh{display:inline-flex;align-items:center;gap:7px;font:400 12.5px var(--mono);color:var(--ink2);line-height:1.4}
.pm-dot{width:7px;height:7px;border-radius:50%;background:var(--cyan);box-shadow:0 0 0 3px var(--ice);flex:none}
.pm-dot.stale{background:#E0A02A;box-shadow:0 0 0 3px var(--warnbg)}.pm-dot.none{background:var(--ink4);box-shadow:0 0 0 3px #EEF1F5}
.pm-kpi{background:var(--card);border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow);padding:18px 20px;min-height:132px;position:relative;overflow:hidden}
.pm-kpi .lab{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;color:var(--ink2);font-weight:500;font-size:13.5px}
.pm-kpi .val{font-size:32px;font-weight:700;letter-spacing:-.035em;margin:12px 0 4px;line-height:1;color:var(--ink)}
.pm-kpi .val small{font-size:14px;color:var(--ink3);font-weight:500;margin-left:5px;letter-spacing:0}
.pm-kpi.hero{background:var(--grad-deep);border:0}
.pm-kpi.hero:before{content:"";position:absolute;right:-40px;bottom:-80px;width:240px;height:240px;border-radius:50%;background:radial-gradient(circle,rgba(144,224,239,.35),transparent 65%)}
.pm-kpi.hero .lab{color:var(--sky)}.pm-kpi.hero .val{color:#fff}.pm-kpi.hero .val small{color:var(--sky)}.pm-kpi.hero .pm-meta{color:#E4F8FC}
.pm-empty{border:1.5px dashed var(--line2);border-radius:14px;padding:20px 18px;text-align:center;color:var(--ink2);background:linear-gradient(180deg,var(--sunk),#fff);font-size:13.5px;margin:.5rem 0}
.pm-empty b{display:block;color:var(--ink);margin-bottom:3px;font-size:14.5px}
.pm-wc-top{display:flex;gap:10px;align-items:center}
.pm-av{width:36px;height:36px;border-radius:11px;background:var(--mist);color:var(--blue);display:grid;place-items:center;font-weight:700;font-size:12.5px;flex:none;border:1px solid var(--ice)}
.pm-av.big{width:58px;height:58px;border-radius:18px;background:var(--grad-deep);color:#fff;font-size:19px;border:0;box-shadow:0 10px 22px -10px rgba(0,119,182,.8)}
.pm-wc-name{font-weight:650;font-size:14px;line-height:1.25;color:var(--ink)}
.pm-wc-id{font:400 11.5px var(--mono);color:var(--ink3);overflow-wrap:anywhere}
.pm-px{font-size:24px;font-weight:700;letter-spacing:-.03em;color:var(--ink);margin:10px 0 4px}
.pm-bigpx{font-size:46px;font-weight:700;letter-spacing:-.045em;line-height:1;color:var(--ink)}
.pm-bigpx small{font-size:16px;color:var(--ink3);font-weight:600;margin-left:6px;letter-spacing:0}
.pm-wc-foot{border-top:1px dashed var(--line2);padding-top:9px;margin-top:6px}
.pm-row{display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid var(--line)}
.pm-row:last-child{border-bottom:0}
.pm-row .n{font-weight:550;font-size:13.5px;color:var(--ink)}
.pm-score{margin-left:auto;text-align:right;font-weight:700;font-size:17px;letter-spacing:-.02em;color:var(--ink);white-space:nowrap}
.pm-score small{display:block;font:400 11px var(--mono);color:var(--ink3)}
.pm-dm{display:grid;grid-auto-flow:column;grid-template-rows:repeat(7,11px);gap:4px;margin:12px 0 4px;overflow-x:auto;padding-bottom:4px}
.pm-dm i{width:11px;height:11px;border-radius:50%;background:#EDF2F7;display:block}
.pm-legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px}
.pm-legend span{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--ink2)}
.pm-legend i{width:9px;height:9px;border-radius:50%;display:inline-block}
.pm-tl{display:grid;grid-template-columns:96px 18px minmax(0,1fr);gap:0 14px}
.pm-tl .when{font:400 12px var(--mono);color:var(--ink2);text-align:right;padding-top:3px;line-height:1.5}
.pm-tl .rail{position:relative}.pm-tl .rail:before{content:"";position:absolute;left:8px;top:0;bottom:-6px;width:1.5px;background:linear-gradient(180deg,var(--ice),var(--line))}
.pm-tl .rail i{position:absolute;left:3px;top:6px;width:12px;height:12px;border-radius:50%;background:#fff;border:3px solid var(--blue)}
.pm-tl b{font-weight:600;display:block;margin-bottom:6px;font-size:14px;color:var(--ink)}
.pm-tags{display:flex;gap:6px;flex-wrap:wrap}
.pm-gauge{position:relative;width:132px;height:78px;flex:none}
.pm-gauge .v{position:absolute;left:0;right:0;bottom:0;text-align:center;font-weight:700;font-size:23px;letter-spacing:-.03em;color:var(--ink)}
.pm-gauge .v small{display:block;font:400 10.5px var(--mono);color:var(--ink3);letter-spacing:0}
.pm-two{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}
.pm-two>div{background:var(--sunk);border:1px solid var(--line);border-radius:14px;padding:11px 12px}
.pm-two small{display:block;font-size:12px;color:var(--ink2);margin-bottom:5px;font-weight:500}
.pm-kv{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:.4rem 0 .8rem}
.pm-kv div{background:var(--sunk);border:1px solid var(--line);border-radius:12px;padding:10px 12px;min-width:0}
.pm-kv small{display:block;font-size:12px;color:var(--ink2);margin-bottom:3px;font-weight:500}
.pm-kv b{font-weight:500;font-size:13.5px;overflow-wrap:anywhere;color:var(--ink)}
.pm-kv .unk b{color:var(--ink3);font-weight:400}
.pm-brand{display:flex;align-items:center;gap:11px;padding:.2rem .2rem .9rem}
.pm-logo{width:38px;height:38px;border-radius:12px;background:var(--grad-deep);display:grid;grid-template-columns:1fr 1fr;gap:3px;padding:9px;box-shadow:0 6px 14px -6px rgba(0,119,182,.7);flex:none}
.pm-logo i{background:#fff;border-radius:2.5px}.pm-logo i:nth-child(2){opacity:.55}.pm-logo i:nth-child(3){opacity:.3}
.pm-brand b{font-weight:700;font-size:17px;display:block;letter-spacing:-.02em;color:var(--ink)}
.pm-brand small{color:var(--ink2);font-size:12px}
.pm-market{background:var(--grad-deep);color:#fff;border-radius:16px;padding:14px;position:relative;overflow:hidden;margin-top:.6rem}
.pm-market:after{content:"";position:absolute;right:-30px;top:-30px;width:120px;height:120px;border-radius:50%;background:radial-gradient(circle,rgba(144,224,239,.45),transparent 70%)}
.pm-market .t{font:500 11px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--sky)}
.pm-market b{display:block;font-size:15px;margin:4px 0 2px;color:#fff}
.pm-market span{font-size:12.5px;color:rgba(255,255,255,.92)}
.pm-soon{display:flex;align-items:center;justify-content:space-between;padding:6px 10px;font-size:13.5px;color:var(--ink3);border-radius:10px}
.pm-soon em{font:500 10.5px var(--mono);font-style:normal;border:1px solid var(--line2);border-radius:6px;padding:0 6px;background:#fff}
.pm-soonh{font:600 11px var(--mono);letter-spacing:.09em;text-transform:uppercase;color:var(--ink3);padding:.9rem 10px .3rem}
.mosaic-footer{position:fixed;left:0;right:0;bottom:0;text-align:center;font:400 12px var(--mono);color:var(--ink2);padding:8px;background:rgba(243,247,251,.88);backdrop-filter:blur(8px);border-top:1px solid var(--line);z-index:999}
@media (max-width:640px){.pm-kv,.pm-two{grid-template-columns:1fr}.pm-tl{grid-template-columns:64px 14px minmax(0,1fr)}.pm-bigpx{font-size:36px}}
</style>
"""


def apply_style() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def footer() -> None:
    st.markdown(f'<div class="mosaic-footer">{FOOTER_TEXT}</div>', unsafe_allow_html=True)


def show_error(err: FriendlyError) -> None:
    st.error(f"**{err.message}**\n\nWhat to do: {err.fix}")


# ---------------------------------------------------------------------------
# Small HTML building blocks (values are escaped; they come from services)
# ---------------------------------------------------------------------------

def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def md(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


ICONS = {
    "trend": '<path d="M3 17l6-6 4 4 8-8"/>',
    "pulse": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "health": '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
    "calendar": '<rect x="3" y="4" width="18" height="17" rx="3"/><path d="M3 9h18M8 2v4M16 2v4"/>',
    "pie": '<path d="M21 12A9 9 0 1 1 12 3v9z"/><path d="M21 8a9 9 0 0 0-5-5v5z"/>',
    "doc": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>',
    "list": '<path d="M4 6h16M4 12h16M4 18h10"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5M5 20h14"/>',
    "check": '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "chip": '<rect x="5" y="5" width="14" height="14" rx="3"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/>',
    "deal": '<path d="M7 7h10v10H7z"/><path d="M3 12h4M17 12h4M12 3v4M12 17v4"/>',
    "history": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}


def icon(name: str) -> str:
    return (f'<span class="pm-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg></span>')


def tag(text, tone: str = "gray") -> str:
    """tone: blue | cyan | navy | green | red | orange | gray (same names as Streamlit badges)."""
    return f'<span class="pm-tag pm-{tone}">{esc(text)}</span>'


def fresh(text, state: str = "current") -> str:
    """A freshness line with a dot. state: current | stale | none."""
    cls = {"current": "", "stale": "stale"}.get(state, "none")
    return f'<span class="pm-fresh"><span class="pm-dot {cls}"></span>{esc(text)}</span>'


def card_head(title: str, sub: str | None = None, icon_name: str | None = None,
              right: str = "", below: str = "") -> str:
    """Card title row. `right` and `below` are trusted HTML made by these helpers."""
    ico = icon(icon_name) if icon_name else ""
    sub_html = f'<div class="pm-cs">{esc(sub)}</div>' if sub else ""
    return (f'<div class="pm-head"><div><div class="pm-ct">{ico}{esc(title)}</div>{sub_html}'
            f'{below}</div><div>{right}</div></div>')


def empty_state(title: str, body: str) -> str:
    return f'<div class="pm-empty"><b>{esc(title)}</b>{esc(body)}</div>'


def page_header(title: str, subtitle: str | None = None, crumb: str | None = None) -> None:
    if crumb:
        md(f'<div class="pm-crumb">{esc(crumb)}</div>')
    st.title(title)
    if subtitle:
        md(f'<div class="pm-sub">{esc(subtitle)}</div>')


def kpi(label: str, value, small: str = "", meta: str = "", badge: str = "",
        hero: bool = False) -> str:
    small_html = f"<small>{esc(small)}</small>" if small else ""
    return (f'<div class="pm-kpi{" hero" if hero else ""}"><div class="lab">{esc(label)}{badge}</div>'
            f'<div class="val pm-num">{esc(value)}{small_html}</div>'
            f'<div class="pm-meta">{esc(meta)}</div></div>')


def initials(name: str) -> str:
    words = [w for w in str(name).replace(".", " ").split() if w[:1].isalnum()]
    stop = {"LTD", "LIMITED", "THE", "OF", "AND", "&"}
    words = [w for w in words if w.upper() not in stop] or words
    return esc("".join(w[0] for w in words[:2]).upper() or "?")


def sparkline(values: list[float], dim: bool = False, height: int = 50) -> str:
    """A small trend line of stored values. Needs at least two points; otherwise nothing."""
    if len(values) < 2:
        return ""
    w, h = 240, height
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pts = [(i * w / (len(values) - 1), h - 5 - (v - lo) / span * (h - 12))
           for i, v in enumerate(values)]
    path = "".join(f"{'L' if i else 'M'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    c1, c2 = ("#AEBBCD", "#8C9BB2") if dim else (CYAN, BLUE)
    gid = f"sp{abs(hash((tuple(values), dim))) % 10**8}"
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="width:100%;height:{h}px;'
            f'display:block"><defs><linearGradient id="{gid}" x1="0" x2="0" y1="0" y2="1">'
            f'<stop offset="0" stop-color="{c1}" stop-opacity=".28"/><stop offset="1" '
            f'stop-color="{c1}" stop-opacity="0"/></linearGradient><linearGradient id="{gid}l" '
            f'x1="0" x2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
            f'</linearGradient></defs><path d="{path}L{w},{h}L0,{h}Z" fill="url(#{gid})"/>'
            f'<path d="{path}" fill="none" stroke="url(#{gid}l)" stroke-width="2" '
            f'vector-effect="non-scaling-stroke" stroke-linecap="round"/></svg>')


def gauge(score: float | None, label: str = "quality / 100") -> str:
    """Half-circle gauge for a 0-100 score. None shows 'Unknown' with an empty track."""
    track = ('<path d="M12 66 A54 54 0 0 1 120 66" fill="none" stroke="#EDF2F7" '
             'stroke-width="11" stroke-linecap="round"/>')
    if score is None:
        return (f'<div class="pm-gauge"><svg viewBox="0 0 132 78" width="132" height="78">{track}'
                f'</svg><div class="v" style="font-size:13px;color:var(--ink3)">Unknown'
                f'<small>not enough data</small></div></div>')
    v = max(0.0, min(100.0, float(score)))
    warn = v < 75
    a = math.pi * (1 - v / 100)
    x, y = 66 + 54 * math.cos(a), 66 - 54 * math.sin(a)
    c1, c2 = ("#F3C66B", "#D9822B") if warn else (SKY, BLUE)
    gid = f"g{int(v * 10)}{int(warn)}"
    arc = (f'<path d="M12 66 A54 54 0 0 1 {x:.1f} {y:.1f}" fill="none" stroke="url(#{gid})" '
           f'stroke-width="11" stroke-linecap="round"/>') if v > 0 else ""
    return (f'<div class="pm-gauge"><svg viewBox="0 0 132 78" width="132" height="78"><defs>'
            f'<linearGradient id="{gid}" x1="0" x2="1"><stop offset="0" stop-color="{c1}"/>'
            f'<stop offset="1" stop-color="{c2}"/></linearGradient></defs>{track}{arc}'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="#fff" stroke="{c2}" stroke-width="3"/>'
            f'</svg><div class="v pm-num">{v:.0f}<small>{esc(label)}</small></div></div>')


# Screens from the brief that later milestones build (shown greyed out, not clickable).
COMING_NEXT = [("Thesis Builder", "M4"), ("Evidence Board", "M4"),
               ("Ask My Research", "M5"), ("Alerts", "M5"), ("Time Machine", "M6")]


def sidebar_extras() -> None:
    """Below the page list: upcoming screens, market hours status and the legal note."""
    with st.sidebar:
        soon = "".join(f'<div class="pm-soon">{esc(n)}<em>{esc(m)}</em></div>'
                       for n, m in COMING_NEXT)
        md(f'<div class="pm-soonh">Coming next</div>{soon}')
        try:
            from app.config import load_config
            from app.timeutil import market_is_open, now_utc, parse_holidays

            cfg = load_config()
            hours = cfg["market_hours"]
            is_open = market_is_open(now_utc(), hours["open"], hours["close"],
                                     parse_holidays(cfg.get("market_holidays")))
            md(f'<div class="pm-market"><div class="t">NSE hours · {esc(hours["open"])}–'
               f'{esc(hours["close"])} IST</div><b>{"Market open" if is_open else "Market closed"}'
               f'</b><span>Prices are delayed about 15 minutes. All times are IST.</span></div>')
        except Exception:  # the status card is optional; never break the sidebar
            pass


# ---------------------------------------------------------------------------
# Formatting helpers (display only; values come from services)
# ---------------------------------------------------------------------------

def fmt_inr(amount) -> str:
    """Indian digit grouping: 1234567.891 -> ₹12,34,567.89"""
    from decimal import ROUND_HALF_UP, Decimal

    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if d < 0 else ""
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}.{frac}"


def fmt_signed(amount, pct=False) -> str:
    from decimal import ROUND_HALF_UP, Decimal

    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "+" if d > 0 else ""
    return f"{sign}{d}%" if pct else f"{sign}{fmt_inr(d)}"


def unknown_text(v) -> str:
    label = "Unknown" if v.state == "unknown" else "Not applicable"
    return f"{label} — {v.reason}"


CONTENT_BADGE = {
    "current": ("Content current", "green"), "partial": ("Content partly current", "orange"),
    "stale": ("Content stale", "orange"), "no_data": ("No data yet", "gray"),
    "timestamp_unknown": ("Content age unknown", "gray"),
}

STATUS_BADGE = {
    # fetch status
    "ok": ("Fetch OK", "green"), "stale": ("Fetch stale", "orange"),
    "missing": ("Fetch returned nothing", "orange"), "blocked": ("Blocked by source", "red"),
    "timeout": ("Timed out", "red"), "error": ("Fetch error", "red"),
    "never_run": ("Never fetched", "gray"),
    # content status
    "current": ("Content current", "green"), "partial": ("Content partly current", "orange"),
    "no_data": ("No data yet", "gray"), "timestamp_unknown": ("Content age unknown", "gray"),
}


# ---------------------------------------------------------------------------
# Signals (M3)
# ---------------------------------------------------------------------------

SIGNAL_STATUS_TONE = {"verified": ("Verified", "green"), "unverified": ("Unverified", "orange"),
                      "needs_review": ("Needs review", "red"), "rejected": ("Rejected", "gray")}
DIRECTION_TAG = {"positive": ("▲ positive", "green"), "negative": ("▼ negative", "red"),
                 "neutral": ("● neutral", "gray")}


def signal_card(s: dict, show_company: bool = True, link: bool = True) -> None:
    """One signal: status and claim-type tags, the claim, where it came from, and a link that
    opens the exact highlighted passage in the Document Viewer. The claim type (14.15) is
    always shown next to the status: Verified proves the quote exists, not that it is true."""
    from app.llm.schemas import CLAIM_TYPES, SIGNAL_TYPES
    from app.timeutil import fmt_ist, from_iso

    label, tone = SIGNAL_STATUS_TONE.get(s["current_status"], (s["current_status"], "gray"))
    by_code = s.get("provider") == "code"
    d_label, d_tone = DIRECTION_TAG.get(s["direction"], (s["direction"], "gray"))
    tags = [tag(label + (" · structured data" if by_code else ""), tone),
            tag(CLAIM_TYPES.get(s["claim_type"], s["claim_type"] or "Unknown claim type"), "navy"),
            tag(SIGNAL_TYPES.get(s["type"], s["type"]), "blue"), tag(d_label, d_tone),
            tag(f"strength {s['strength']}/5", "gray")]
    where = [s.get("company_name") if show_company else None,
             s["signal_date"] or f"found {fmt_ist(from_iso(s['created_at']))}",
             f"tier {s['source_tier']}" if s.get("source_tier") else None,
             f"page {s['page']}" if s.get("page") else None,
             "no AI" if by_code else f"{s['model']} · {s['prompt_version']}"]
    with st.container(border=True, key=f"card-sig-{s['id']}-{'c' if show_company else 'd'}"):
        md(" ".join(tags))
        md(f'<div style="font-weight:600;margin:.35rem 0 .15rem">{esc(s["claim_text"])}</div>')
        st.caption(" · ".join(x for x in where if x))
        if link:
            st.page_link("app/ui/DocumentViewer.py", label="Open the highlighted source passage",
                         query_params={"doc": s["document_id"], "signal": s["id"]},
                         icon=":material/format_quote:")
