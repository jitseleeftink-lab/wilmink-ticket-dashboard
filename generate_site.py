from pathlib import Path
import shutil
import pandas as pd


PLOT_DATA_FILE = Path("data/wilmink_all_plot_points.csv")
GRAPH_FILE = Path("plots/wilmink_estimated_tickets_sold.png")

DOCS_FOLDER = Path("docs")
DOCS_ASSETS = DOCS_FOLDER / "assets"
DOCS_DATA = DOCS_FOLDER / "data"

PUBLIC_GRAPH = DOCS_ASSETS / "wilmink_estimated_tickets_sold.png"
PUBLIC_CSV = DOCS_DATA / "wilmink_all_plot_points.csv"
INDEX_FILE = DOCS_FOLDER / "index.html"

PAGE_TITLE = "Kaartverkoop Wilminktheater Enschede"


def main() -> None:
    DOCS_ASSETS.mkdir(parents=True, exist_ok=True)
    DOCS_DATA.mkdir(parents=True, exist_ok=True)

    if not PLOT_DATA_FILE.exists():
        raise FileNotFoundError(f"Missing {PLOT_DATA_FILE}. Run wilmink_seat_tracker.py first.")

    if not GRAPH_FILE.exists():
        raise FileNotFoundError(f"Missing {GRAPH_FILE}. Run wilmink_seat_tracker.py first.")

    plot_data = pd.read_csv(PLOT_DATA_FILE)
    plot_data["measurement_time"] = pd.to_datetime(plot_data["measurement_time"])
    plot_data = plot_data.sort_values("measurement_time")

    latest = plot_data.iloc[-1]

    latest_time = latest["measurement_time"].strftime("%d-%m-%Y %H:%M")
    latest_sold = int(latest["estimated_sold_seats"])
    data_points = len(plot_data)

    # Growth since 23:59 the previous day
    yesterday_2359 = latest["measurement_time"].normalize() - pd.Timedelta(minutes=1)

    previous_rows = plot_data[plot_data["measurement_time"] <= yesterday_2359]

    if len(previous_rows) > 0:
        sold_at_yesterday_2359 = int(previous_rows.iloc[-1]["estimated_sold_seats"])
    else:
        sold_at_yesterday_2359 = latest_sold

    growth_since_yesterday_2359 = latest_sold - sold_at_yesterday_2359

    shutil.copy2(GRAPH_FILE, PUBLIC_GRAPH)
    shutil.copy2(PLOT_DATA_FILE, PUBLIC_CSV)

    html = f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{PAGE_TITLE}</title>
  <meta http-equiv="refresh" content="300">

  <style>
    :root {{
      --bg: #f6f1e8;
      --card: #fffaf2;
      --text: #2b2523;
      --muted: #756b63;
      --accent: #8b1e2d;
      --line: #d8c8b8;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(139, 30, 45, 0.11), transparent 32rem),
        linear-gradient(135deg, #f6f1e8 0%, #efe4d4 100%);
      color: var(--text);
      min-height: 100vh;
    }}

    .wrap {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 42px 18px;
    }}

    .hero {{
      background: rgba(255, 250, 242, 0.92);
      border: 1px solid rgba(216, 200, 184, 0.9);
      border-radius: 26px;
      padding: 34px;
      box-shadow: 0 18px 50px rgba(43, 37, 35, 0.12);
      margin-bottom: 24px;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(2rem, 5vw, 4rem);
      line-height: 1;
      letter-spacing: -0.05em;
    }}

    .subtitle {{
      color: var(--muted);
      margin-top: 14px;
      margin-bottom: 0;
      font-size: 1.05rem;
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 16px;
      margin-top: 28px;
    }}

    .stat {{
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 8px 22px rgba(43, 37, 35, 0.06);
    }}

    .label {{
      color: var(--muted);
      font-size: 0.9rem;
      margin-bottom: 8px;
    }}

    .value {{
      font-size: 2.3rem;
      font-weight: 800;
      letter-spacing: -0.04em;
      color: var(--accent);
    }}

    .value.small {{
      font-size: 1.45rem;
      letter-spacing: -0.02em;
      color: var(--text);
    }}

    .card {{
      background: rgba(255, 250, 242, 0.95);
      border: 1px solid rgba(216, 200, 184, 0.9);
      border-radius: 26px;
      padding: 24px;
      box-shadow: 0 18px 50px rgba(43, 37, 35, 0.10);
    }}

    .card h2 {{
      margin-top: 0;
      margin-bottom: 18px;
      font-size: 1.4rem;
    }}

    img {{
      width: 100%;
      height: auto;
      display: block;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: white;
    }}

    .footer {{
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 18px;
      color: var(--muted);
      font-size: 0.92rem;
    }}

    a {{
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }}

    a:hover {{
      text-decoration: underline;
    }}
  </style>
</head>

<body>
  <main class="wrap">
    <section class="hero">
      <h1>{PAGE_TITLE}</h1>
      <p class="subtitle">Het VU-Orkest speelt Bruckners 8ste Symfonie · Muziekcentrum Enschede</p>

      <div class="stats">
        <div class="stat">
          <div class="label">Laatste geschatte verkoop</div>
          <div class="value">{latest_sold}</div>
        </div>

        <div class="stat">
          <div class="label">Laatste meting</div>
          <div class="value small">{latest_time}</div>
        </div>

        <div class="stat">
          <div class="label">Datapunten</div>
          <div class="value">{data_points}</div>
        </div>

        <div class="stat">
            <div class="label">Verkoop sinds gisteren 23:59</div>
            <div class="value">+{growth_since_yesterday_2359}</div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Verkoopontwikkeling</h2>
      <img src="assets/wilmink_estimated_tickets_sold.png?cache={data_points}" alt="Grafiek geschatte kaartverkoop">

      <div class="footer">
        <span>Deze pagina wordt bijgewerkt wanneer de tracker draait.</span>
        <a href="data/wilmink_all_plot_points.csv">Download CSV</a>
      </div>
    </section>
  </main>
</body>
</html>
"""

    INDEX_FILE.write_text(html, encoding="utf-8")

    print(f"Generated {INDEX_FILE}")
    print(f"Copied graph to {PUBLIC_GRAPH}")
    print(f"Copied data to {PUBLIC_CSV}")


if __name__ == "__main__":
    main()