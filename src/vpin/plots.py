"""Figures in one consistent style. Every function saves a PNG and returns its path."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# Colours of the seminar's HSE slide theme, so figures and slides match.
OURS = "#1656A6"      # our results (theme blue)
PAPER = "#EB8C3C"     # the paper's numbers (theme orange)
TRUE = "#009B64"      # true buyer/seller labels (theme green)
GREY = "#8C8C8C"
ALERT = "#7D50B9"     # CDF and alarm lines (theme purple)

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 200, "savefig.bbox": "tight",
    "font.family": "Arial", "font.size": 10, "axes.titlesize": 11, "axes.labelsize": 10,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "legend.frameon": False,
})


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def day_vpin(panels: list[dict], crash_window: tuple[str, str], path: Path, alert: float = 0.9) -> Path:
    """Figure 4: VPIN and CDF(VPIN) through one day, one panel per classification scheme.

    Each panel dict: title, buckets (end_ts, vpin, cdf), price (ts, close).
    """
    fig, axes = plt.subplots(1, len(panels), figsize=(4.6 * len(panels), 3.4), sharey=False)
    for ax, p in zip(np.atleast_1d(axes), panels):
        b = p["buckets"]
        ax.axvspan(pd.Timestamp(crash_window[0]), pd.Timestamp(crash_window[1]), color=GREY, alpha=0.15, lw=0)
        ax.plot(b["end_ts"], b["vpin"], color=OURS, lw=1.6, label="VPIN")
        ax.set_ylabel("VPIN", color=OURS)
        ax2 = ax.twinx()
        ax2.plot(b["end_ts"], b["cdf"], color=ALERT, lw=1.2, ls="--", label="CDF(VPIN)")
        ax2.axhline(alert, color=ALERT, lw=0.8, alpha=0.6)
        ax2.set_ylim(0, 1.02)
        ax2.spines["right"].set_visible(True)
        ax2.grid(False)
        ax2.set_ylabel("CDF(VPIN)", color=ALERT)
        ax3 = ax.twinx()
        ax3.plot(p["price"]["ts"], p["price"]["close"], color=GREY, lw=0.8, alpha=0.8)
        ax3.axis("off")
        ax.set_title(p["title"])
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    fig.tight_layout()
    return _save(fig, path)


def heatmap(values: pd.DataFrame, title: str, path: Path, fmt: str = "{:.2f}",
            cmap: str = "Blues", vmin=None, vmax=None, mark=None) -> Path:
    """Parameter heat map: rows = sample length, columns = buckets per day."""
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    im = ax.imshow(values.to_numpy(dtype=float), cmap=cmap, origin="lower", aspect="auto",
                   vmin=vmin, vmax=vmax)
    ax.set_xticks(range(values.shape[1]), values.columns)
    ax.set_yticks(range(values.shape[0]), values.index)
    ax.set_xlabel("Buckets per day")
    ax.set_ylabel("Sample length (buckets)")
    ax.grid(False)
    if values.size <= 170:
        for (i, j), v in np.ndenumerate(values.to_numpy(dtype=float)):
            if np.isfinite(v):
                ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=6.5,
                        color="white" if im.norm(v) > 0.6 else "black")
    if mark is not None and mark[0] in values.columns and mark[1] in values.index:
        j, i = list(values.columns).index(mark[0]), list(values.index).index(mark[1])
        ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, ec=PAPER, lw=2))
    fig.colorbar(im, ax=ax, fraction=0.046)
    ax.set_title(title)
    return _save(fig, path)


def table_heatmaps(ours: pd.DataFrame, paper: np.ndarray | None, title: str, path: Path) -> Path:
    """Table 4a / Table 5 as two heat maps side by side: the paper's and ours."""
    panels = [("Paper (E-mini)", paper), ("Ours (IVE)", ours.to_numpy(dtype=float))]
    panels = [p for p in panels if p[1] is not None]
    fig, axes = plt.subplots(1, len(panels), figsize=(5.2 * len(panels), 4.8))
    for ax, (name, m) in zip(np.atleast_1d(axes), panels):
        im = ax.imshow(m, cmap="Blues", origin="lower", aspect="auto", vmin=0, vmax=1)
        ax.set_xticks(range(m.shape[1]), ours.columns[: m.shape[1]], rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(20), ours.index, fontsize=7)
        ax.set_xlabel("|return| bin")
        ax.set_ylabel("VPIN 5%-tile")
        ax.grid(False)
        for (i, j), v in np.ndenumerate(m):
            if np.isfinite(v) and v >= 0.005:
                ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=5.5,
                        color="white" if v > 0.6 else "black")
        ax.set_title(name)
    fig.suptitle(title)
    fig.tight_layout()
    return _save(fig, path)


def vpin_history(buckets: pd.DataFrame, path: Path, title: str, events: dict | None = None) -> Path:
    """Figure 6: VPIN and price over the whole sample."""
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.plot(buckets["end_ts"], buckets["vpin"], color=OURS, lw=0.6, label="VPIN")
    ax.set_ylabel("VPIN", color=OURS)
    ax2 = ax.twinx()
    ax2.plot(buckets["end_ts"], buckets["end_price"], color=GREY, lw=0.7, label="price")
    ax2.set_ylabel("Price, USD", color=GREY)
    ax2.grid(False)
    for name, day in (events or {}).items():
        ax.axvline(pd.Timestamp(day), color=PAPER, lw=0.8, ls=":")
        ax.text(pd.Timestamp(day), ax.get_ylim()[1], " " + name, color=PAPER, fontsize=8, va="top")
    ax.set_title(title)
    return _save(fig, path)


def scatter_next_return(log_vpin_prev: np.ndarray, ret: np.ndarray, path: Path, title: str) -> Path:
    """Figure 11: next bucket's return against the log of the previous VPIN."""
    ok = np.isfinite(log_vpin_prev) & np.isfinite(ret)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(log_vpin_prev[ok], ret[ok], s=2, alpha=0.25, color=OURS, lw=0)
    ax.set_xlabel("ln VPIN of the previous bucket")
    ax.set_ylabel("Return over the next bucket")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title(title)
    return _save(fig, path)


def sampling_histograms(clock: np.ndarray, volume: np.ndarray, path: Path) -> Path:
    """Figure 3: standardized price changes sampled by clock vs by volume, vs N(0,1)."""
    fig, ax = plt.subplots(figsize=(6.4, 4))
    grid = np.linspace(-5, 5, 201)
    for x, name, color in [(clock, "Clock time", GREY), (volume, "Volume time", OURS)]:
        z = np.diff(x)
        z = (z - z.mean()) / z.std()
        ax.hist(z, bins=np.linspace(-5, 5, 81), density=True, histtype="step", lw=1.4,
                color=color, label=name)
    ax.plot(grid, np.exp(-grid ** 2 / 2) / np.sqrt(2 * np.pi), color="black", lw=0.8, ls="--", label="N(0,1)")
    ax.set_yscale("log")
    ax.set_ylim(1e-4, 2)
    ax.set_xlabel("Standardized price change")
    ax.set_ylabel("Density (log scale)")
    ax.legend()
    return _save(fig, path)


def stability(times: pd.Series, mean_diff: np.ndarray, std_diff: np.ndarray, path: Path) -> Path:
    """Figure 5: mean and cross-sectional std of VPIN differences across shifted starts."""
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.plot(times, std_diff, color=OURS, lw=0.6, label="cross-sectional std")
    ax.plot(times, mean_diff, color=GREY, lw=0.6, label="mean difference")
    ax.set_ylabel("VPIN difference vs first trajectory")
    ax.legend(loc="upper left")
    return _save(fig, path)


def time_gap(buckets: pd.DataFrame, path: Path, title: str) -> Path:
    """Figure 2: clock time covered by the n buckets behind each VPIN value, and VPIN."""
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.plot(buckets["end_ts"], buckets["gap_hours"], color=GREY, lw=1.4, label="time gap")
    ax.set_ylabel("Clock time covered (hours)")
    ax2 = ax.twinx()
    ax2.plot(buckets["end_ts"], buckets["vpin"], color=OURS, lw=1.4)
    ax2.set_ylabel("VPIN", color=OURS)
    ax2.grid(False)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_title(title)
    return _save(fig, path)


def yearly_bars(df: pd.DataFrame, path: Path) -> Path:
    """E2: year-by-year correlation and insurance value, VPIN against trailing volatility."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    x = np.arange(len(df))
    w = 0.38
    axes[0].bar(x - w / 2, df["vpin_corr"], w, color=OURS, label="VPIN")
    axes[0].bar(x + w / 2, df["rv_corr"], w, color=GREY, label="trailing volatility (RV)")
    axes[0].set_title("Corr(ln signal, next |return|)")
    axes[1].bar(x - w / 2, df["vpin_insurance"], w, color=OURS, label="VPIN")
    axes[1].bar(x + w / 2, df["rv_insurance"], w, color=GREY, label="RV")
    axes[1].plot(x, df["vpin_alarm_rate"], color=ALERT, marker="o", ms=3, lw=1,
                 label="share of time VPIN alarm is on")
    axes[1].set_title("P(signal in top quartile | next |return| > 0.75%)")
    axes[1].yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    for ax in axes:
        ax.set_xticks(x, df["year"], rotation=60, fontsize=8)
        ax.axhline(0, color="black", lw=0.6)
        ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


SERIES_STYLE = {"vpin": ("CDF(VPIN), bulk classified", OURS, "-"),
                "vpin_true": ("CDF(VPIN), true labels", TRUE, "-"),
                "rv": ("CDF(trailing volatility)", GREY, "--")}


def crash_panels(panels: list[dict], path: Path, alert: float = 0.9) -> Path:
    """E4: real-time CDFs before and after each day's largest one-hour fall."""
    if not panels:
        return path
    cols = 2
    rows = int(np.ceil(len(panels) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(11, 3.0 * rows), squeeze=False)
    for ax, p in zip(axes.ravel(), panels):
        for key, (ts, values) in p["series"].items():
            name, color, ls = SERIES_STYLE[key]
            ax.plot(ts, values, color=color, ls=ls, lw=1.3, label=name)
        ax.axhline(alert, color=ALERT, lw=0.8)
        ax.axvline(p["t0"], color="black", lw=0.8, ls=":")
        ax.set_ylim(0, 1.02)
        ax2 = ax.twinx()
        ax2.plot(p["price"]["ts"], p["price"]["close"], color=GREY, lw=0.7, alpha=0.6)
        ax2.axis("off")
        ax.set_title(p["title"], fontsize=10)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
        ax.tick_params(labelsize=7)
    for ax in axes.ravel()[len(panels):]:
        ax.axis("off")
    axes[0, 0].legend(fontsize=7, loc="lower left")
    fig.tight_layout()
    return _save(fig, path)


def bvc_vs_truth(b: pd.DataFrame, path: Path) -> Path:
    """E1: VPIN from bulk classification against VPIN from the true aggressor side."""
    ok = b["vpin"].notna() & b["vpin_true"].notna()
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [1, 1.6]})
    axes[0].hexbin(b.loc[ok, "vpin_true"], b.loc[ok, "vpin"], gridsize=60, bins="log", cmap="Blues")
    lim = float(max(b.loc[ok, "vpin"].max(), b.loc[ok, "vpin_true"].max()))
    axes[0].plot([0, lim], [0, lim], color="black", lw=0.6, ls="--")
    axes[0].set_xlabel("VPIN, true labels")
    axes[0].set_ylabel("VPIN, bulk classified")
    axes[0].set_title(f"Corr = {b.loc[ok, 'vpin'].corr(b.loc[ok, 'vpin_true']):.2f}")
    end = b["end_ts"].max()
    window = b["end_ts"] >= end - pd.Timedelta(days=60)
    axes[1].plot(b.loc[window, "end_ts"], b.loc[window, "vpin"], color=OURS, lw=0.9, label="bulk classified")
    axes[1].plot(b.loc[window, "end_ts"], b.loc[window, "vpin_true"], color=TRUE, lw=0.9, label="true labels")
    axes[1].set_title("Last 60 days of the sample")
    axes[1].legend(fontsize=8)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.tight_layout()
    return _save(fig, path)


def volume_profile(bars: pd.DataFrame, path: Path) -> Path:
    """Figure 1: average volume in each 5-minute slot of the session."""
    minute = (bars["ts"] - bars["day"]).dt.total_seconds() // 300 * 5
    per_day = bars.groupby([bars["day"], minute])["volume"].sum()
    profile = per_day.groupby(level=1).mean()
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    labels = [f"{int(m // 60):02d}:{int(m % 60):02d}" for m in profile.index]
    ax.bar(range(len(profile)), profile.to_numpy(), color=OURS, width=0.9)
    step = max(1, len(profile) // 7)
    ax.set_xticks(range(0, len(profile), step), labels[::step])
    ax.set_ylabel("Average shares per 5 minutes")
    ax.set_title("IVE: intraday volume profile")
    return _save(fig, path)
