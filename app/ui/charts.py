"""Altair charts in the Pramana style. Display only: every point comes from stored data."""

import altair as alt

from app.ui.common import BLUE, CYAN, INK2, INK3, LINE, NAVY, SKY

_FONT = "Inter, 'Segoe UI', sans-serif"


def _style(chart, height: int):
    return (chart.properties(height=height, background="transparent")
            .configure_view(strokeWidth=0)
            .configure_axis(labelFont=_FONT, labelColor=INK3, labelFontSize=11.5, titleFont=_FONT,
                            titleColor=INK2, domain=False, tickSize=0, labelPadding=8,
                            gridColor=LINE, gridDash=[3, 5])
            .configure_legend(labelFont=_FONT, labelColor=INK2, labelFontSize=12.5,
                              orient="bottom", title=None, symbolType="circle", symbolSize=90)
            .configure_axisX(grid=False))


def _gradient(color: str, top: float):
    return alt.Gradient(gradient="linear", x1=1, x2=1, y1=0, y2=1,
                        stops=[alt.GradientStop(color=_rgba(color, top), offset=0),
                               alt.GradientStop(color=_rgba(color, 0), offset=1)])


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def price_area(rows: list[dict], height: int = 250):
    """rows: [{"Date": "YYYY-MM-DD", "Close": float}] — stored daily closes, oldest first."""
    base = alt.Chart(alt.Data(values=rows)).encode(
        x=alt.X("Date:T", title=None, axis=alt.Axis(format="%d %b", labelAngle=0)),
        y=alt.Y("Close:Q", title=None, scale=alt.Scale(zero=False, nice=True), stack=None,
                axis=alt.Axis(format=",.0f")))
    area = base.mark_area(interpolate="monotone", clip=True, color=_gradient(CYAN, .32),
                          line={"color": BLUE, "strokeWidth": 2.4})
    hover = base.mark_circle(size=70, color=BLUE, opacity=0).encode(
        tooltip=[alt.Tooltip("Date:T", title="Date", format="%d %b %Y"),
                 alt.Tooltip("Close:Q", title="Close (₹)", format=",.2f")])
    last = alt.Chart(alt.Data(values=rows[-1:])).mark_circle(
        size=110, color=BLUE, stroke="white", strokeWidth=2.5, opacity=1).encode(
        x="Date:T", y="Close:Q")
    return _style(alt.layer(area, hover, last), height)


HOLDER_COLORS = [NAVY, BLUE, CYAN, SKY, INK3]


def holder_lines(rows: list[dict], order: list[str], height: int = 250):
    """rows: [{"As on": date, "Holder": label, "Percent": float}]. Separate lines, never stacked:
    'Public (total)' already includes institutions, so stacking would double-count."""
    color = alt.Color("Holder:N", sort=order,
                      scale=alt.Scale(domain=order, range=HOLDER_COLORS[:len(order)]))
    base = alt.Chart(alt.Data(values=rows)).encode(
        x=alt.X("As on:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0)),
        y=alt.Y("Percent:Q", title="% of shares", scale=alt.Scale(domain=[0, 100])),
        color=color,
        tooltip=[alt.Tooltip("As on:T", format="%d %b %Y"), "Holder:N",
                 alt.Tooltip("Percent:Q", format=".2f", title="% of shares")])
    lines = base.mark_line(interpolate="monotone", strokeWidth=2.6)
    points = base.mark_circle(size=70, opacity=1, stroke="white", strokeWidth=1.5)
    return _style(alt.layer(lines, points), height)


def score_area(scores: list[float], height: int = 110):
    rows = [{"Run": i + 1, "Score": s} for i, s in enumerate(scores)]
    chart = alt.Chart(alt.Data(values=rows)).mark_area(
        interpolate="monotone", color=_gradient(CYAN, .28),
        line={"color": BLUE, "strokeWidth": 2}).encode(
        x=alt.X("Run:Q", title=None, axis=None),
        y=alt.Y("Score:Q", title=None, scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(values=[0, 50, 100])),
        tooltip=["Run:Q", alt.Tooltip("Score:Q", format=".0f")])
    return _style(chart, height)
