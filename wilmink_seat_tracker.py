from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import re

import pandas as pd
import matplotlib.pyplot as plt
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator

# Event settings
EVENT_URL = "https://www.wilminktheater.nl/nl/agenda/het-vu-orkest-speelt-bruckners-8ste-symfonie-q2mj"
EVENT_ID = "8846"

# Manual calibration:
# You counted 323 available seats and 25 sold seats.
# So normal online sellable capacity = 323 + 25 = 348.
SELLABLE_CAPACITY = 348



# Set this to False when debugging so you can watch the browser.
HEADLESS = True

# Output files
DATA_FILE = Path("data/wilmink_seat_counts.csv")
DAILY_FILE = Path("data/wilmink_daily_sales_estimate.csv")
PLOT_FILE = Path("plots/wilmink_estimated_tickets_sold.png")
MANUAL_FILE = Path("data/manual_ticket_counts.csv")
PLOT_DATA_FILE = Path("data/wilmink_all_plot_points.csv")

def handle_cookies(page) -> None:
    """
    Clicks only real cookie consent buttons.
    Do not click generic 'Sluiten', because that can close other site dialogs.
    """
    cookie_buttons = [
        "Alles toestaan",
        "Alles accepteren",
        "Accepteren",
        "Akkoord",
    ]

    for text in cookie_buttons:
        try:
            button = page.get_by_role("button", name=text)
            if button.count() > 0 and button.first.is_visible():
                button.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                print(f"Clicked cookie button: {text}")
                return
        except Exception:
            pass


def close_cart_if_open(page) -> None:
    """
    Closes the cart popup if it is open.
    """
    try:
        close_button = page.locator(
            "#cart button:has-text('Sluiten'), #cart [aria-label='Sluiten']"
        )

        if close_button.count() > 0 and close_button.first.is_visible():
            close_button.first.click(timeout=3000)
            page.wait_for_timeout(1000)
            print("Closed cart popup.")
    except Exception:
        pass


def click_event_order_button(page, expected_text: str | None = None) -> None:
    """
    Clicks the exact order button for this event.

    The page contains hidden duplicate buttons, so we inspect all matching
    event buttons and click the visible one.
    """
    selector = f"a.btn-order[data-event-boxofficeid='{EVENT_ID}']"

    page.wait_for_selector(selector, state="attached", timeout=30000)

    buttons = page.locator(selector)
    count = buttons.count()

    print(f"Found {count} matching event order button(s).")

    for i in range(count):
        button = buttons.nth(i)

        try:
            text = button.inner_text().strip()
        except Exception:
            text = ""

        try:
            visible = button.is_visible()
        except Exception:
            visible = False

        print(f"Button {i}: visible={visible}, text={text!r}")

        if expected_text is not None and expected_text.lower() not in text.lower():
            continue

        if visible:
            button.scroll_into_view_if_needed()
            button.click(timeout=30000)
            page.wait_for_timeout(5000)
            print(f"Clicked visible event button: {text!r}")
            return

    raise RuntimeError(
        f"Could not click visible event button for event {EVENT_ID}."
    )


def click_text_if_visible(page, text_pattern: str) -> bool:
    """
    Clicks a visible link/button/text matching text_pattern.
    """
    pattern = re.compile(text_pattern, re.IGNORECASE)

    for role in ["button", "link"]:
        try:
            locator = page.get_by_role(role, name=pattern).first
            if locator.count() > 0 and locator.is_visible():
                print(f"Clicking {role}: {text_pattern}")
                locator.click(timeout=10000)
                page.wait_for_timeout(4000)
                return True
        except Exception:
            pass

    try:
        locator = page.get_by_text(pattern).first
        if locator.count() > 0 and locator.is_visible():
            print(f"Clicking text: {text_pattern}")
            locator.click(timeout=10000)
            page.wait_for_timeout(4000)
            return True
    except Exception:
        pass

    return False


def count_seats_from_page(page) -> dict:
    """
    Counts SVG seat circles by their data-status.

    This function DOES NOT click or select seats.
    It only reads the seat map already visible in the browser.
    """
    page.wait_for_selector("svg circle[data-status]", state="attached", timeout=60000)

    result = page.evaluate(
        """
        () => {
            const seats = Array.from(
                document.querySelectorAll("svg circle[data-status]")
            );

            const counts = {};

            for (const seat of seats) {
                const status = seat.getAttribute("data-status") || "unknown";
                counts[status] = (counts[status] || 0) + 1;
            }

            return {
                total: seats.length,
                counts: counts
            };
        }
        """
    )

    status_counts = Counter(result["counts"])

    total_svg_seats = int(result["total"])
    available_seats = int(status_counts.get("available", 0))

    # The SVG's blocked/unavailable count combines:
    # - actually sold seats
    # - venue-blocked seats
    # - seats not for online sale
    # - possibly accessibility/box-office-only seats
    svg_unavailable_seats = total_svg_seats - available_seats

    estimated_sold_raw = SELLABLE_CAPACITY - available_seats
    estimated_sold_seats = max(0, estimated_sold_raw)

    estimated_blocked_not_for_sale = max(
        0,
        svg_unavailable_seats - estimated_sold_seats,
    )

    calibration_warning = ""
    if available_seats > SELLABLE_CAPACITY:
        calibration_warning = (
            "Available seats is higher than SELLABLE_CAPACITY. "
            "Check the manual calibration."
        )

    now = datetime.now()

    return {
        "timestamp": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "event_id": EVENT_ID,
        "event_url": EVENT_URL,
        "sellable_capacity": SELLABLE_CAPACITY,
        "total_svg_seats": total_svg_seats,
        "available_seats": available_seats,
        "svg_unavailable_seats": svg_unavailable_seats,
        "estimated_sold_seats": estimated_sold_seats,
        "estimated_blocked_not_for_sale": estimated_blocked_not_for_sale,
        "calibration_warning": calibration_warning,
    }


def fetch_seat_counts() -> dict:
    """
    Goes to the public event page, opens the seat map, reads availability,
    then cancels/cleans up the reservation session.

    It does not click any seats and does not continue to checkout.
    """
    browser = None
    context = None
    page = None

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=HEADLESS)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720}
            )
            page = context.new_page()
            page.set_default_timeout(30000)

            print("Opening event page...")
            page.goto(EVENT_URL, wait_until="networkidle", timeout=60000)

            handle_cookies(page)
            close_cart_if_open(page)

            print("Clicking Bestellen...")
            click_event_order_button(page, expected_text="Bestellen")

            handle_cookies(page)
            close_cart_if_open(page)

            print("Clicking Verder...")
            click_event_order_button(page, expected_text="Verder")

            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(3000)

            print("Clicking Zelf stoelen kiezen...")
            clicked = click_text_if_visible(page, "Zelf stoelen kiezen")

            if not clicked:
                raise RuntimeError("Could not find 'Zelf stoelen kiezen'.")

            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(6000)

            print("Current seat map URL:")
            print(page.url)

            row = count_seats_from_page(page)

            print("Seat count result:")
            print(row)

            return row

        finally:
            # Clean up the temporary reservation/cart session.
            # This is not selecting seats; it just leaves the flow cleanly.
            if page is not None:
                try:
                    page.goto(
                        "https://www.wilminktheater.nl/nl/mijntheater/reserveer/?annuleer=1",
                        wait_until="networkidle",
                        timeout=15000,
                    )
                    page.wait_for_timeout(1000)
                    print("Cleaned up reservation session.")
                except Exception:
                    print("Could not clean up session; closing browser context.")

            if context is not None:
                context.close()

            if browser is not None:
                browser.close()


def save_reading(row: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    new_data = pd.DataFrame([row])

    if DATA_FILE.exists() and DATA_FILE.stat().st_size > 0:
        old_data = pd.read_csv(DATA_FILE)
        data = pd.concat([old_data, new_data], ignore_index=True)
    else:
        data = new_data

    data.to_csv(DATA_FILE, index=False)


def build_daily_summary() -> pd.DataFrame:
    all_rows = []

    # Automatic measurements: use exact timestamp, so every login/run becomes a point.
    if DATA_FILE.exists() and DATA_FILE.stat().st_size > 0:
        automatic = pd.read_csv(DATA_FILE)

        if "estimated_sold_seats" in automatic.columns:
            if "timestamp" in automatic.columns:
                automatic["measurement_time"] = pd.to_datetime(
                    automatic["timestamp"],
                    errors="coerce",
                )
            else:
                automatic["measurement_time"] = pd.to_datetime(
                    automatic["date"],
                    errors="coerce",
                ) + pd.Timedelta(hours=12)

            automatic["date"] = automatic["measurement_time"].dt.date
            automatic["estimated_sold_seats"] = pd.to_numeric(
                automatic["estimated_sold_seats"],
                errors="coerce",
            )
            automatic["available_seats"] = pd.to_numeric(
                automatic.get(
                    "available_seats",
                    SELLABLE_CAPACITY - automatic["estimated_sold_seats"],
                ),
                errors="coerce",
            )
            automatic["sellable_capacity"] = SELLABLE_CAPACITY
            automatic["source"] = "automatic"

            all_rows.append(
                automatic[
                    [
                        "measurement_time",
                        "date",
                        "estimated_sold_seats",
                        "available_seats",
                        "sellable_capacity",
                        "source",
                    ]
                ]
            )

    # Manual measurements: use noon as the time for manual date-only points.
    if MANUAL_FILE.exists() and MANUAL_FILE.stat().st_size > 0:
        manual = pd.read_csv(MANUAL_FILE)

        manual["measurement_time"] = pd.to_datetime(
            manual["date"],
            errors="coerce",
        ) + pd.Timedelta(hours=12)

        manual["date"] = manual["measurement_time"].dt.date
        manual["estimated_sold_seats"] = pd.to_numeric(
            manual["estimated_sold_seats"],
            errors="coerce",
        )
        manual["available_seats"] = SELLABLE_CAPACITY - manual["estimated_sold_seats"]
        manual["sellable_capacity"] = SELLABLE_CAPACITY
        manual["source"] = "manual"

        all_rows.append(
            manual[
                [
                    "measurement_time",
                    "date",
                    "estimated_sold_seats",
                    "available_seats",
                    "sellable_capacity",
                    "source",
                ]
            ]
        )

    if not all_rows:
        raise ValueError("No automatic or manual ticket data found.")

    plot_data = pd.concat(all_rows, ignore_index=True)
    plot_data = plot_data.dropna(subset=["measurement_time", "estimated_sold_seats"])
    plot_data = plot_data.sort_values("measurement_time")

    # If two identical measurement times exist, keep the highest sold estimate.
    plot_data = (
        plot_data.groupby("measurement_time", as_index=False)
        .agg(
            date=("date", "first"),
            estimated_sold_seats=("estimated_sold_seats", "max"),
            available_seats=("available_seats", "min"),
            sellable_capacity=("sellable_capacity", "max"),
            source=("source", "first"),
        )
        .sort_values("measurement_time")
    )

    PLOT_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    plot_data.to_csv(PLOT_DATA_FILE, index=False)

    # Also keep the daily summary.
    daily = (
        plot_data.groupby("date", as_index=False)
        .agg(
            estimated_sold_seats=("estimated_sold_seats", "max"),
            available_seats=("available_seats", "min"),
            sellable_capacity=("sellable_capacity", "max"),
        )
        .sort_values("date")
    )

    daily["estimated_net_sold_since_previous_day"] = (
        daily["estimated_sold_seats"]
        .diff()
        .fillna(0)
        .astype(int)
    )

    daily["estimated_new_sold_that_day"] = (
        daily["estimated_net_sold_since_previous_day"]
        .clip(lower=0)
        .astype(int)
    )

    DAILY_FILE.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_FILE, index=False)

    # Return every plotted point, not only daily points.
    return plot_data


def make_plot(plot_data: pd.DataFrame) -> None:
    PLOT_FILE.parent.mkdir(parents=True, exist_ok=True)

    plot_data = plot_data.copy()
    plot_data["measurement_time"] = pd.to_datetime(plot_data["measurement_time"])
    plot_data["estimated_sold_seats"] = pd.to_numeric(
        plot_data["estimated_sold_seats"],
        errors="coerce",
    )
    plot_data = plot_data.dropna(subset=["measurement_time", "estimated_sold_seats"])
    plot_data = plot_data.sort_values("measurement_time")

    point_count = len(plot_data)
    latest_sold = int(plot_data["estimated_sold_seats"].iloc[-1])
    latest_time = plot_data["measurement_time"].iloc[-1]

    # Growth since 23:59 the previous day
    yesterday_2359 = latest_time.normalize() - pd.Timedelta(minutes=1)
    previous_rows = plot_data[plot_data["measurement_time"] <= yesterday_2359]

    if len(previous_rows) > 0:
        sold_at_yesterday_2359 = int(previous_rows.iloc[-1]["estimated_sold_seats"])
    else:
        sold_at_yesterday_2359 = latest_sold

    change_since_yesterday_2359 = latest_sold - sold_at_yesterday_2359

    fig, ax = plt.subplots(figsize=(12, 6.5))

    fig.patch.set_facecolor("#f6f1e8")
    ax.set_facecolor("#fffaf2")

    x = plot_data["measurement_time"]
    y = plot_data["estimated_sold_seats"]

    ax.plot(
        x,
        y,
        linewidth=3,
        color="#8b1e2d",
    )

    ax.fill_between(
        x,
        y,
        0,
        alpha=0.12,
        color="#8b1e2d",
    )

    ax.scatter(
        [x.iloc[-1]],
        [y.iloc[-1]],
        s=140,
        color="#8b1e2d",
        zorder=5,
    )

    ax.annotate(
        f"{latest_sold} kaarten",
        xy=(x.iloc[-1], y.iloc[-1]),
        xytext=(12, 12),
        textcoords="offset points",
        fontsize=11,
        fontweight="bold",
        color="#8b1e2d",
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "#fffaf2",
            "edgecolor": "#8b1e2d",
            "alpha": 0.95,
        },
    )

    ax.set_title(
        "Kaartverkoop Wilminktheater Enschede",
        fontsize=20,
        fontweight="bold",
        pad=18,
        color="#2b2523",
    )

    ax.set_xlabel("Meetmoment", fontsize=12, color="#2b2523")
    ax.set_ylabel("Geschat aantal verkochte kaarten", fontsize=12, color="#2b2523")

    ax.grid(True, which="major", linestyle="-", linewidth=0.8, alpha=0.22)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#b8a99a")
    ax.spines["bottom"].set_color("#b8a99a")

    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m"))

    fig.autofmt_xdate(rotation=30, ha="right")

    counter_text = (
        f"Datapunten: {point_count}\n"
        f"Laatste stand: {latest_sold} kaarten\n"
        f"Sinds gisteren 23:59: +{change_since_yesterday_2359}\n"
        f"Laatste meting: {latest_time:%d-%m-%Y %H:%M}"
    )

    ax.text(
        0.02,
        0.96,
        counter_text,
        transform=ax.transAxes,
        verticalalignment="top",
        fontsize=10.5,
        color="#2b2523",
        bbox={
            "boxstyle": "round,pad=0.55",
            "facecolor": "#ffffff",
            "edgecolor": "#d8c8b8",
            "alpha": 0.95,
        },
    )

    ax.margins(x=0.04, y=0.18)

    plt.tight_layout()
    plt.savefig(PLOT_FILE, dpi=180, facecolor=fig.get_facecolor())
    plt.close()


def main() -> None:
    row = fetch_seat_counts()

    save_reading(row)
    daily = build_daily_summary()
    make_plot(daily)

    print()
    print("Done.")
    print(f"Available seats: {row['available_seats']}")
    print(f"Estimated sold seats: {row['estimated_sold_seats']}")
    print(f"Estimated blocked/not-for-sale seats: {row['estimated_blocked_not_for_sale']}")
    print(f"CSV: {DATA_FILE}")
    print(f"Daily summary: {DAILY_FILE}")
    print(f"Plot: {PLOT_FILE}")


if __name__ == "__main__":
    main()