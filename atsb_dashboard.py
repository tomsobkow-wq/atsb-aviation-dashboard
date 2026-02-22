#!/usr/bin/env python3
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
from bs4 import BeautifulSoup
from plotly.subplots import make_subplots

BASE = "https://www.atsb.gov.au"
LIST_URL = f"{BASE}/aviation-investigation-reports"
DATA_DIR = Path("data")
OUT_DIR = Path("outputs")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def fetch_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def parse_listing(limit: int = 10):
    soup = fetch_soup(LIST_URL)
    rows = soup.select("table tbody tr")
    items = []
    for tr in rows:
        links = tr.select('a[href*="/publications/investigation_reports/"]')
        if not links:
            continue
        title_link = next((a for a in links if "AO-" not in a.get_text(" ", strip=True).upper() and "AA-" not in a.get_text(" ", strip=True).upper()), links[0])
        code_link = links[-1]
        tds = [clean(td.get_text(" ", strip=True)) for td in tr.select("td")]
        title = clean(title_link.get_text(" ", strip=True))
        href = title_link.get("href", "")
        if href.startswith("/"):
            href = BASE + href
        report_no = clean(code_link.get_text(" ", strip=True))
        date_str = tds[2] if len(tds) > 2 else ""
        status = tds[3] if len(tds) > 3 else ""
        try:
            occ_date = datetime.strptime(date_str, "%d/%m/%Y")
        except Exception:
            occ_date = None
        items.append(
            {
                "report_no": report_no,
                "title": title,
                "report_url": href,
                "occurrence_date": occ_date,
                "occurrence_date_text": date_str,
                "investigation_status": status,
            }
        )

    # De-dup and sort by date desc
    dedup = {}
    for it in items:
        dedup[it["report_no"]] = it
    items = list(dedup.values())
    items.sort(key=lambda x: x["occurrence_date"] or datetime.min, reverse=True)
    return items[:limit]


def extract_summary_text(soup: BeautifulSoup) -> str:
    main = soup.select_one("main") or soup
    paragraphs = [clean(p.get_text(" ", strip=True)) for p in main.select("p")]
    paragraphs = [p for p in paragraphs if len(p) > 40]
    return "\n\n".join(paragraphs[:4])


def classify_cause(text: str):
    t = text.lower()
    mapping = {
        "Collision with terrain": ["collision with terrain", "controlled flight into terrain", "cfit"],
        "Near collision / airprox": ["near collision", "proximity event", "airprox", "midair"],
        "Ditching / water impact": ["ditching", "water"],
        "Mechanical / system issue": ["engine", "landing gear", "rotor", "foreign object", "f.o.d", "indication", "failure"],
        "Operational event": ["fuel", "runway", "navigation", "weather", "vfr", "imc"],
    }
    for label, kws in mapping.items():
        if any(k in t for k in kws):
            return label
    return "Other / undetermined"


def classify_severity(text: str):
    t = text.lower()
    if "fatal" in t or "sustained fatal injuries" in t:
        return "Fatal"
    if "serious injury" in t:
        return "Serious injury"
    if "minor injury" in t or "injur" in t:
        return "Injury"
    if "no injuries" in t or "no injury" in t:
        return "No injury"
    return "Unknown"


def parse_aircraft(title: str):
    m = re.search(r"involving\s+([^,]+),", title, flags=re.I)
    return clean(m.group(1)) if m else "Unknown"


def parse_location(title: str):
    m = re.search(r"(?:near|at|about|off|west of|east of|south of|north of)\s+(.+?),\s+on\s+\d", title, flags=re.I)
    return clean(m.group(1)) if m else "Unknown"


def parse_operation_type(title: str):
    t = title.lower()
    if "helicopter" in t or any(x in t for x in ["r44", "aw139", "bell", "s-92"]):
        return "Helicopter"
    if any(x in t for x in ["airbus", "saab", "boeing", "a380"]):
        return "Air transport"
    if "accredited representative" in t:
        return "International assistance"
    return "General aviation"


def fetch_report_detail(item):
    soup = fetch_soup(item["report_url"])
    title = clean((soup.select_one("h1") or soup.select_one("title")).get_text(" ", strip=True)).replace(" | ATSB", "")
    summary = extract_summary_text(soup)
    combined = f"{title}\n{summary}"
    item.update(
        {
            "title": title,
            "aircraft": parse_aircraft(title),
            "location": parse_location(title),
            "operation_type": parse_operation_type(title),
            "key_text": summary,
            "cause_category": classify_cause(combined),
            "severity": classify_severity(combined),
        }
    )
    return item


def build_dashboard(df: pd.DataFrame, out_html: Path):
    cause_counts = df["cause_category"].value_counts().reset_index()
    cause_counts.columns = ["cause_category", "count"]

    sev_counts = df["severity"].value_counts().reset_index()
    sev_counts.columns = ["severity", "count"]

    op_counts = df["operation_type"].value_counts().reset_index()
    op_counts.columns = ["operation_type", "count"]

    timeline = df.sort_values("occurrence_date")

    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=("Cause categories", "Operation type", "Severity", "Timeline"),
        specs=[[{"type": "bar"}, {"type": "bar"}], [{"type": "pie"}, {"type": "scatter"}]],
    )

    fig.add_trace(go.Bar(x=cause_counts["cause_category"], y=cause_counts["count"], name="Causes"), row=1, col=1)
    fig.add_trace(go.Bar(x=op_counts["operation_type"], y=op_counts["count"], name="Operation type"), row=1, col=2)
    fig.add_trace(go.Pie(labels=sev_counts["severity"], values=sev_counts["count"], name="Severity"), row=2, col=1)
    fig.add_trace(
        go.Scatter(
            x=timeline["occurrence_date"],
            y=timeline["report_no"],
            mode="markers+lines",
            text=timeline["title"],
            name="Timeline",
        ),
        row=2,
        col=2,
    )

    fig.update_layout(height=900, width=1300, title_text="ATSB Aviation Latest 10 Investigation Reports - Insights Dashboard")

    table_cols = [
        "report_no",
        "occurrence_date_text",
        "operation_type",
        "aircraft",
        "cause_category",
        "severity",
        "investigation_status",
        "report_url",
    ]
    table_df = df[table_cols].copy()
    table_html = table_df.to_html(index=False, escape=False)

    html = f"""
    <html>
    <head><meta charset='utf-8'><title>ATSB Dashboard</title></head>
    <body>
      <h1>ATSB Aviation - Latest 10 Investigation Reports</h1>
      {fig.to_html(include_plotlyjs='cdn', full_html=False)}
      <h2>Report table</h2>
      {table_html}
      <p>Source: Australian Transport Safety Bureau (ATSB). Links in table point to original report pages.</p>
    </body>
    </html>
    """
    out_html.write_text(html, encoding="utf-8")


def write_insights(df: pd.DataFrame, out_md: Path):
    causes = df["cause_category"].value_counts()
    ops = df["operation_type"].value_counts()
    sev = df["severity"].value_counts()

    top_locations = Counter(df["location"]).most_common(5)
    lines = [
        "# ATSB aviation reports - key insights (latest 10)",
        "",
        f"- Reports analysed: **{len(df)}**",
        f"- Date window: **{df['occurrence_date'].min().date()} to {df['occurrence_date'].max().date()}**",
        "",
        "## Key patterns",
        f"- Most frequent event/cause bucket: **{causes.index[0]}** ({causes.iloc[0]} reports).",
        f"- Operational context is mainly **{ops.index[0]}** ({ops.iloc[0]} reports).",
        f"- Severity profile is dominated by **{sev.index[0]}** ({sev.iloc[0]} reports).",
        "",
        "## Cause/category distribution",
    ]
    for k, v in causes.items():
        lines.append(f"- {k}: {v}")

    lines += ["", "## Severity", *[f"- {k}: {v}" for k, v in sev.items()], "", "## Frequent locations"]
    for loc, c in top_locations:
        lines.append(f"- {loc}: {c}")

    lines += [
        "",
        "## Notes",
        "- Many latest ATSB aviation entries are ongoing investigations, so final causal findings may not yet be published.",
        "- Cause categories in this dashboard are derived from report titles + available narrative text (keyword-based classification).",
    ]
    out_md.write_text("\n".join(lines), encoding="utf-8")


def main():
    DATA_DIR.mkdir(exist_ok=True)
    OUT_DIR.mkdir(exist_ok=True)

    listing = parse_listing(limit=10)
    detailed = [fetch_report_detail(item) for item in listing]
    df = pd.DataFrame(detailed)
    df["occurrence_date"] = pd.to_datetime(df["occurrence_date"])

    json_ready = df.copy()
    json_ready["occurrence_date"] = json_ready["occurrence_date"].dt.strftime("%Y-%m-%d")

    df.to_csv(DATA_DIR / "reports.csv", index=False)
    (DATA_DIR / "reports.json").write_text(json.dumps(json_ready.to_dict(orient="records"), indent=2), encoding="utf-8")

    write_insights(df, OUT_DIR / "insights.md")
    build_dashboard(df, OUT_DIR / "dashboard.html")

    print("Created:")
    print("- data/reports.csv")
    print("- data/reports.json")
    print("- outputs/insights.md")
    print("- outputs/dashboard.html")
    print("Top cause category:", df["cause_category"].value_counts().idxmax())


if __name__ == "__main__":
    main()
