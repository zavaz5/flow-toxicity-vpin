"""Build docs/presentation.pptx on the seminar's HSE slide template.

Numbers come from results/report/key_numbers.json and the CSVs in results/ (ours) and
from src/vpin/paper_numbers.py (the paper's). Paper figures are cropped from the paper
PDF given with --paper. Each slide carries speaker notes with talking points and the
files its numbers come from.

Usage:
  python scripts/make_slides.py --paper "<paper.pdf>"
  python scripts/make_slides.py --make-template "<any deck in the HSE template>"   # once
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from vpin import paper_numbers as PN  # noqa: E402
from vpin import plots as P  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
BUILD = DOCS / "build"            # generated images for the slides (not committed)
REP = ROOT / "results" / "reproduction"
EXT = ROOT / "results" / "extensions"
TEMPLATE = DOCS / "hse_template.pptx"

NAVY = RGBColor(0x0F, 0x2C, 0x68)
BLUE = RGBColor(0x16, 0x56, 0xA6)
ORANGE = RGBColor(0xEB, 0x8C, 0x3C)
GREEN = RGBColor(0x00, 0x9B, 0x64)
RED = RGBColor(0xC0, 0x39, 0x2B)
TEXT = RGBColor(0x22, 0x22, 0x22)
MUTED = RGBColor(0x59, 0x59, 0x59)
LIGHT = RGBColor(0xEE, 0xF2, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)


# ---------- template and slide helpers ----------

def make_template(src: Path, dst: Path):
    """Keep the slide master and layouts of an HSE deck and drop every slide (and with
    them every picture and note of that deck)."""
    prs = Presentation(src)
    ids = prs.slides._sldIdLst
    for sld in list(ids):
        prs.part.drop_rel(sld.rId)
        ids.remove(sld)
    dst.parent.mkdir(parents=True, exist_ok=True)
    prs.save(dst)


def layout(prs, name):
    return next(l for l in prs.slide_masters[0].slide_layouts if l.name == name)


def drop(placeholder):
    placeholder.element.getparent().remove(placeholder.element)


def slide_with_title(prs, title: str, notes: str):
    """Text_2 layout: theme title and header; the body placeholder is replaced by our boxes."""
    s = prs.slides.add_slide(layout(prs, "Text_2"))
    s.shapes.title.text = title
    for ph in list(s.placeholders):
        idx = ph.placeholder_format.idx
        if idx == 2:
            ph.text = "Research Seminar"
        elif idx == 1:
            drop(ph)
    s.notes_slide.notes_text_frame.text = notes
    return s


def _runs(paragraph, text: str, size: float, color, bold=False):
    """Add runs to a paragraph; **double stars** mark bold segments."""
    for i, part in enumerate(text.split("**")):
        if not part:
            continue
        r = paragraph.add_run()
        r.text = part
        r.font.size = Pt(size)
        r.font.bold = bold or i % 2 == 1
        r.font.color.rgb = color


def text(slide, box, items, size=16, color=TEXT, space=6, anchor=MSO_ANCHOR.TOP):
    """Text box. items: strings, or (string, {size, color, bold, bullet, indent, align})."""
    x, y, w, h = box
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    for i, item in enumerate(items):
        s, opt = (item, {}) if isinstance(item, str) else item
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(opt.get("space", space))
        p.alignment = opt.get("align", PP_ALIGN.LEFT)
        prefix = ("    " * opt.get("indent", 0)) + ("• " if opt.get("bullet", True) and s else "")
        _runs(p, prefix + s, opt.get("size", size), opt.get("color", color), opt.get("bold", False))
    return tb


def picture(slide, path: Path, box, align="center"):
    """Fit an image inside (x, y, w, h) inches, keeping its aspect ratio."""
    x, y, w, h = box
    iw, ih = Image.open(path).size
    scale = min(w / iw, h / ih)
    pw, ph = iw * scale, ih * scale
    left = x + (w - pw) / 2 if align == "center" else x
    return slide.shapes.add_picture(str(path), Inches(left), Inches(y + (h - ph) / 2), Inches(pw), Inches(ph))


def table(slide, df: pd.DataFrame, box, widths=None, size=12, header_size=None, fills=None):
    """Table in theme colours. `fills` maps (row, col) -> RGBColor for single cells."""
    x, y, w, h = box
    rows, cols = df.shape[0] + 1, df.shape[1]
    shape = slide.shapes.add_table(rows, cols, Inches(x), Inches(y), Inches(w), Inches(h))
    t = shape.table
    widths = widths or [w / cols] * cols
    for j, cw in enumerate(widths):
        t.columns[j].width = Inches(cw)
    for i in range(rows):
        for j in range(cols):
            cell = t.cell(i, j)
            value = df.columns[j] if i == 0 else df.iat[i - 1, j]
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            _runs(p, str(value), header_size or size if i == 0 else size, WHITE if i == 0 else TEXT, bold=i == 0)
            cell.margin_left = cell.margin_right = Inches(0.06)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY if i == 0 else (LIGHT if i % 2 == 0 else WHITE)
            if fills and (i - 1, j) in fills:
                cell.fill.fore_color.rgb = fills[(i - 1, j)]
                for r in p.runs:
                    r.font.color.rgb = WHITE
                    r.font.bold = True
    return shape


def box_shape(slide, box, label, fill, size=14):
    x, y, w, h = box
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.fill.background()
    tf = shp.text_frame
    tf.word_wrap = True
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    _runs(tf.paragraphs[0], label, size, WHITE, bold=True)
    return shp


def arrow_down(slide, x, y, w=0.35, h=0.3):
    a = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    a.fill.solid()
    a.fill.fore_color.rgb = MUTED
    a.line.fill.background()


# ---------- images made for the slides ----------

def equation(tex: str, path: Path, size=26):
    """Render a formula with matplotlib's mathtext (no LaTeX install needed)."""
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, f"${tex}$", fontsize=size, color="#0F2C68")
    fig.savefig(path, dpi=300, bbox_inches="tight", pad_inches=0.05, transparent=True)
    plt.close(fig)
    return path


def bvc_curve(path: Path):
    """Illustration of bulk classification: the buy share of a bar as a function of dP / sigma."""
    z = np.linspace(-3, 3, 200)
    from scipy.stats import norm
    fig, ax = plt.subplots(figsize=(5, 3.2))
    ax.plot(z, norm.cdf(z), color=P.OURS, lw=2.2)
    ax.axhline(0.5, color=P.GREY, lw=0.8, ls="--")
    ax.axvline(0, color=P.GREY, lw=0.8, ls="--")
    for zz, label in [(0, "no change:\n50% buys"), (1.5, "+1.5σ:\n93% buys")]:
        ax.plot(zz, norm.cdf(zz), "o", color=P.PAPER)
        ax.annotate(label, (zz, norm.cdf(zz)), xytext=(-2.6, 0.68) if zz == 0 else (1.75, 0.55),
                    fontsize=9, arrowprops={"arrowstyle": "-", "color": P.GREY})
    ax.set_xlabel("Price change of the bar / σ")
    ax.set_ylabel("Share of the bar's volume\ncounted as buys")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    fig.savefig(path, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return path


def is_vs_oos_bars(path: Path):
    """In-sample vs out-of-sample correlation of VPIN for each parameter choice, and RV."""
    df = pd.read_csv(EXT / "ive_oos_comparison.csv")
    choices = list(dict.fromkeys(df["choice"]))
    get = lambda c, per, sig: df[(df["choice"] == c) & (df["period"] == per) & (df["signal"] == sig)]["corr"].iloc[0]
    x = np.arange(len(choices))
    fig, ax = plt.subplots(figsize=(6.2, 3.8))
    w = 0.27
    ax.bar(x - w, [get(c, "in-sample", "VPIN") for c in choices], w, color=P.OURS, alpha=0.45, label="VPIN, in sample (2009–11)")
    ax.bar(x, [get(c, "out-of-sample", "VPIN") for c in choices], w, color=P.OURS, label="VPIN, out of sample (2011–26)")
    ax.bar(x + w, [get(c, "out-of-sample", "RV (trailing volatility)") for c in choices], w, color=P.GREY,
           label="trailing volatility, out of sample")
    labels = [c.replace("paper Table 5", "paper's\nTable 5").replace("best in-sample ", "best in-sample\n") for c in choices]
    ax.set_xticks(x, labels, fontsize=8)
    ax.set_ylabel("Corr(ln signal, next |return|)")
    ax.legend(fontsize=8, loc="upper right")
    fig.savefig(path, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return path


def crop_paper(pdf: Path, page: int, clip, path: Path, dpi=220):
    """Render part of a page of the paper (1-based page, clip in PDF points)."""
    doc = pymupdf.open(pdf)
    doc[page - 1].get_pixmap(dpi=dpi, clip=pymupdf.Rect(*clip)).save(path)
    return path


# ---------- slides ----------

def build(paper_pdf: Path, out: Path):
    BUILD.mkdir(parents=True, exist_ok=True)
    k = json.loads((ROOT / "results" / "report" / "key_numbers.json").read_text())
    pred, data = k["prediction"], k["data"]
    fc = k["flash_crash"]
    figs = {
        "paper_fig4": crop_paper(paper_pdf, 54, (95, 82, 517, 372), BUILD / "paper_fig4a.png"),
        "paper_fig10": crop_paper(paper_pdf, 62, (68, 82, 492, 372), BUILD / "paper_fig10.png"),
        "eq_pin": equation(r"\mathrm{PIN}=\frac{\alpha\mu}{\alpha\mu+2\varepsilon}", BUILD / "eq_pin.png"),
        "eq_bvc": equation(r"V^{B}_{\tau}=\sum_{i\in\tau}V_i\,Z\!\left(\frac{P_i-P_{i-1}}{\sigma_{\Delta P}}\right),\quad V^{S}_{\tau}=V-V^{B}_{\tau}", BUILD / "eq_bvc.png"),
        "eq_vpin": equation(r"\mathrm{VPIN}_{\tau}=\frac{\sum_{j=\tau-n+1}^{\tau}\left|V^{S}_{j}-V^{B}_{j}\right|}{nV}", BUILD / "eq_vpin.png"),
        "bvc_curve": bvc_curve(BUILD / "bvc_curve.png"),
        "is_oos": is_vs_oos_bars(BUILD / "is_vs_oos.png"),
    }
    prs = Presentation(TEMPLATE)

    # 1. Title
    s = prs.slides.add_slide(layout(prs, "Title_1"))
    for ph in list(s.placeholders):
        idx = ph.placeholder_format.idx
        if idx == 0:
            ph.text = "11. FLOW TOXICITY AND LIQUIDITY IN A HIGH-FREQUENCY WORLD"
        elif idx == 1:
            ph.text = "Research Seminar"
        elif idx == 2:
            ph.text = "Group N"
        elif idx == 4:
            ph.text = "DAVID EASLEY, MARCOS LÓPEZ DE PRADO AND MAUREEN O'HARA"
        else:
            drop(ph)
    text(s, (1.12, 6.0, 7, 1.0), [("Review of Financial Studies 25(5), 2012", {"bullet": False, "size": 14, "color": NAVY}),
                                  ("Name Surname · Name Surname · Name Surname", {"bullet": False, "size": 14, "color": MUTED})])
    s.notes_slide.notes_text_frame.text = (
        "Fill in the group number and names. Timing (15 min): problem 2 · method 3 · results and reproduction 5 · "
        "critique 3 · next steps 2. Then 10 minutes of questions.")

    # 2. Problem
    s = slide_with_title(prs, "Why toxic order flow matters", (
        "Problem, ~1 min. Market makers earn the spread; adverse selection = trading with someone who knows more. "
        "Toxic flow drains them; they withdraw; liquidity vanishes; prices gap. The paper's question: can we see "
        "this coming from the trade record alone?"))
    text(s, (0.64, 2.45, 7.0, 4.4), [
        "**Market makers** (today mostly high-frequency firms) earn a tiny spread on many trades and avoid directional bets.",
        "They lose when the other side **knows more**. Order flow is **toxic** when it adversely selects them, often before they notice.",
        "When toxicity rises they widen quotes or **leave**. With no one absorbing orders, prices gap. The paper links the **6 May 2010 flash crash** to this.",
        "**Question:** can toxicity be measured in real time, from trades alone, early enough to act?",
    ], size=17, space=12)
    y = 2.5
    for label, fill in [("One-sided, informed order flow", BLUE), ("Market makers lose on their inventory", BLUE),
                        ("They widen quotes or withdraw", NAVY), ("Liquidity gap → extreme volatility", ORANGE)]:
        box_shape(s, (8.3, y, 4.3, 0.75), label, fill, size=14)
        if y < 5.5:
            arrow_down(s, 10.27, y + 0.8)
        y += 1.13

    # 3. PIN -> VPIN
    s = slide_with_title(prs, "Method: from PIN to VPIN, measured in volume time", (
        "Method, ~1 min. PIN is the share of orders from informed traders in the sequential-trade model "
        "(Easley et al. 1996). Estimating it needs maximum likelihood on daily counts — slow and fragile. VPIN "
        "replaces the parameters by observable volume: |buys − sells| estimates alpha*mu, total volume estimates "
        "alpha*mu + 2 epsilon. Updated after every equal-volume bucket. The figure is our data: on 6 May 2010 the "
        "same 50 buckets covered less and less clock time as trading sped up. Source: results/reproduction/figures/fig2_time_gap.png."))
    text(s, (0.64, 2.45, 6.3, 1.0), ["**PIN** (Easley et al. 1996): the share of orders that come from informed traders"], size=16)
    picture(s, figs["eq_pin"], (0.9, 3.05, 5.5, 1.0))
    text(s, (0.64, 4.2, 6.3, 2.7), [
        "α: chance of news, μ: informed arrivals, ε: uninformed arrivals per side. Needs maximum likelihood: slow and unstable at high frequency.",
        "**VPIN:** |buys − sells| estimates αμ, total volume estimates αμ + 2ε. No parameters to fit.",
        "**Volume clock:** cut trading into buckets of equal volume (1/50 of a day). Busy, news-heavy periods get more updates.",
    ], size=14, space=8)
    picture(s, REP / "figures" / "fig2_time_gap.png", (7.1, 2.45, 5.8, 4.3))

    # 4. BVC
    s = slide_with_title(prs, "Method: bulk volume classification", (
        "Method, ~1 min. Trade-by-trade signing (Lee-Ready, tick rule) struggles with order splitting, "
        "cancellations and millions of quote updates. The paper classifies whole one-minute bars: the share of a "
        "bar's volume counted as buys is the normal CDF of the bar's standardized price change. This is the "
        "step our extension E1 tests against the truth."))
    picture(s, figs["eq_bvc"], (0.64, 2.5, 6.6, 1.0), align="left")
    text(s, (0.64, 3.85, 6.6, 3.0), [
        "Group trades into **one-minute bars**; split each bar's volume by its standardized price change.",
        "No price change → 50/50. A rise of 1.5σ → 93% buys. Z is the standard normal CDF; σ is the standard deviation of bar price changes.",
        "Robust to order splitting and cancellations, cheap to compute.",
        "**But:** the imbalance it produces grows with |price change|, by construction.",
    ], size=15, space=9)
    picture(s, figs["bvc_curve"], (7.9, 2.6, 5.0, 4.2))

    # 5. VPIN and how to read it
    s = slide_with_title(prs, "Method: the VPIN metric and how it is read", (
        "Method, ~1 min. Baseline: V = average daily volume / 50 and n = 50, so VPIN is about one day of "
        "trading, updated 50 times a day. The paper reads VPIN through its CDF over the whole sample; an "
        "alarm is CDF above 0.9. Note for Q&A: a whole-sample CDF uses future data (see the overfitting slide)."))
    picture(s, figs["eq_vpin"], (0.64, 2.45, 5.5, 1.3), align="left")
    text(s, (0.64, 3.95, 5.9, 3.0), [
        "Bucket size **V = average daily volume / 50**; window **n = 50** buckets ≈ one day.",
        "Updated after **every bucket**: on busy days many times per hour.",
        "Levels depend on classification and settings, so the paper reads **CDF(VPIN)** over the whole sample. Alarm: CDF > 0.9.",
        "Claim: high VPIN warns of **toxicity-induced volatility**.",
    ], size=15, space=9)
    picture(s, REP / "figures" / "fig6_vpin_history.png", (6.7, 2.5, 6.3, 3.9))

    # 6. Data
    s = slide_with_title(prs, "Data and our replication setup", (
        "Data, ~1 min. CME data are paid, so we use the only free tick history with quotes we found: IVE from "
        "Kibot, which covers the flash crash. Binance BTC data give the true aggressor side, which the paper "
        "never had. All deviations with reasons: DEVIATIONS.md. Numbers: results/reproduction/summary.json."))
    t2 = k["table2"]
    df = pd.DataFrame([
        ("Market", "E-mini S&P 500 and WTI crude futures", "IVE (S&P 500 Value ETF) ticks with quotes; BTCUSDT for extensions"),
        ("Period", "Jan 2008 – Aug 2011 (incl. 2008 crisis)", f"{data['period'][0]} – {data['period'][1]}; out of sample to Sep 2026"),
        ("Trading hours", "almost 24 hours", "09:30–16:00 New York"),
        ("VPIN observations (50, 50)", f"{t2['paper']['#Observ.']:,}", f"{int(t2['ours']['#Observ.']):,}"),
        ("Classification", "bulk, one-minute bars", "same, plus 10-second bars and Lee-Ready"),
        ("Settings", "V = ADV/50, n = 50, whole-sample σ and CDF", "identical"),
    ], columns=["", "Paper", "Ours"])
    table(s, df, (0.64, 2.45, 12.05, 3.0), widths=[2.6, 4.2, 5.25], size=13)
    text(s, (0.64, 5.7, 12.0, 1.4), [
        f"Main deviations: ETF instead of futures; regular hours only; our sample starts in Sep 2009 (no 2008 crisis); "
        f"42 IVE trades at prices like $0.08 that the exchanges **cancelled** on 6 May 2010 are removed. "
        f"{data['share_bars_no_price_change']:.0%} of IVE one-minute bars have no price change, and bulk classification splits them 50/50.",
    ], size=13, color=MUTED)

    # 7. Flash crash
    s = slide_with_title(prs, "Result 1: the flash crash, paper vs ours", (
        "Results, ~1 min. Paper Fig. 4(a): CDF(VPIN) crossed 0.9 at least two hours before the crash. Ours, "
        f"one-minute bars: CDF above 0.9 from {fc['BVC, 1-minute bars']['first'][11:16]}, {fc['BVC, 1-minute bars']['lead_hours']:.1f} h before 14:32. "
        "But with 10-second bars it crosses only during the crash, and with Lee-Ready never. "
        "So the early warning depends on how volume is classified. Source: results/reproduction/flash_crash.csv."))
    picture(s, figs["paper_fig4"], (0.4, 2.4, 4.1, 3.4))
    text(s, (0.4, 5.75, 4.1, 0.4), [("Paper, Fig. 4(a): E-mini, one-minute bars", {"bullet": False, "size": 11, "color": MUTED, "align": PP_ALIGN.CENTER})])
    picture(s, REP / "figures" / "fig4_flash_crash.png", (4.6, 2.45, 8.5, 2.9))
    lr = fc["Lee-Ready, trade by trade"]
    text(s, (4.7, 5.4, 8.3, 1.7), [
        f"**One-minute bars:** CDF > 0.9 from {fc['BVC, 1-minute bars']['first'][11:16]}, **{fc['BVC, 1-minute bars']['lead_hours']:.1f} h** before the fall — as in the paper.",
        f"**10-second bars:** first above 0.9 at {fc['BVC, 10-second bars']['first'][11:16]}, during the fall. **Lee-Ready:** never (max CDF {lr['max_cdf']:.2f}).",
        "The warning depends on the classification choice.",
    ], size=13, space=4)

    # 8. Volume clock + stability
    s = slide_with_title(prs, "Result 2: the volume clock and the stability of VPIN", (
        "Results, ~1 min. Table 1: sampling by volume should give price changes closer to normal. On IVE the raw "
        "table is dominated by one observation: on 6 May 2010 IVE fell to about half its price for minutes. "
        "Without that day and without overnight changes (which a 24-hour futures market does not have), volume "
        "time wins on most statistics. Stability: restarting buckets 1,000 times barely moves VPIN. "
        "Sources: results/reproduction/table1_*.csv, summary.json (stability)."))
    ours = pd.read_csv(REP / "table1_50_no_crash_day_intraday.csv", index_col=0)
    rows = []
    for stat in ["Kurt", "J-B*", "L-B*", "White*", "Max"]:
        rows.append((stat, f"{PN.TABLE1_50['Chrono time'][stat]:.2f}", f"{PN.TABLE1_50['Volume time'][stat]:.2f}",
                     f"{ours.loc[stat, 'Chrono time']:.2f}", f"{ours.loc[stat, 'Volume time']:.2f}"))
    df = pd.DataFrame(rows, columns=["50 draws a day", "Paper: clock", "Paper: volume", "Ours: clock", "Ours: volume"])
    better = {(i, 4): GREEN for i, r in enumerate(rows) if float(r[4]) < float(r[3])}
    better.update({(i, 2): GREEN for i, r in enumerate(rows) if float(r[2]) < float(r[1])})
    table(s, df, (0.64, 2.45, 7.0, 2.6), size=13, fills=better)
    w = k["table1"]["wins_clean"]
    text(s, (0.64, 5.2, 7.0, 1.9), [
        f"Volume time improves {w['50'][0]} of 4 test statistics at 50 draws a day and {w['100'][0]} of 4 at 100 (green = lower than clock time).",
        "Computed without 6 May 2010 and without overnight changes; the raw table is dominated by the flash crash (DEVIATIONS.md, row 8).",
    ], size=13, color=MUTED)
    text(s, (8.0, 2.45, 4.8, 0.5), [("Stability (Fig. 5)", {"bullet": False, "bold": True, "size": 16, "color": NAVY})])
    text(s, (8.0, 3.0, 4.8, 3.8), [
        "Start the bucket sequence 0, 1, …, 999 bars later and compare the VPIN paths.",
        f"Cross-sectional std / mean VPIN: paper **{k['stability']['paper']:.1%}**, ours **{k['stability']['ours']:.1%}**.",
        "VPIN does not depend on where the volume clock starts. **Reproduced.**",
    ], size=14, space=8)

    # 9. Correlation surface
    s = slide_with_title(prs, "Result 3: does VPIN predict the next bucket's volatility?", (
        "Results, ~1 min. Paper Fig. 10: correlation of ln VPIN with the next bucket's absolute return, over "
        "buckets per day and window length; 0.40 at (50, 250). Ours is the same computation on IVE: "
        f"{pred['corr_50_250']:.2f} at (50, 250) and at most {pred['corr_max']:.2f} anywhere on the grid. "
        f"Not the overnight gaps: without buckets spanning the close it is {pred['corr_50_250_intraday']:.2f}. "
        "Source: results/reproduction/parameter_grid.csv."))
    picture(s, figs["paper_fig10"], (0.4, 2.35, 5.6, 4.0))
    text(s, (0.4, 6.35, 5.6, 0.4), [("Paper, Fig. 10: E-mini", {"bullet": False, "size": 11, "color": MUTED, "align": PP_ALIGN.CENTER})])
    picture(s, REP / "figures" / "fig10_correlation.png", (6.2, 2.35, 4.6, 4.1))
    text(s, (10.85, 2.5, 2.3, 4.2), [
        ("At (50, 250)", {"bullet": False, "bold": True, "color": NAVY, "size": 15}),
        (f"paper **{PN.CORR_50_250:.2f}**", {"bullet": False, "size": 15}),
        (f"ours **{pred['corr_50_250']:.2f}**", {"bullet": False, "size": 15, "space": 14}),
        (f"Best cell on our grid: {pred['corr_max']:.2f}", {"bullet": False, "size": 13, "color": MUTED}),
        ("Same sign, a fifth of the size.", {"bullet": False, "size": 13, "color": MUTED}),
    ], size=14)

    # 10. Tables 4 and 5
    s = slide_with_title(prs, "Result 4: high VPIN and large moves (Tables 4 and 5)", (
        "Results, ~1 min. Left/right: paper's Table 4a and ours as heat maps. Low VPIN does mean calm: in the "
        "bottom quartile the next move is below 0.25% almost always, in both. But high VPIN does not spread "
        "the next return out as much on IVE. Insurance value and true positives are lower. Sources: "
        "results/reproduction/table4a.csv, table5.csv, summary.json."))
    picture(s, REP / "figures" / "table4a_conditional.png", (0.3, 2.3, 8.6, 4.9))
    text(s, (9.0, 2.45, 4.1, 4.5), [
        (f"Bottom-quartile VPIN → next |return| < 0.25%: paper > {PN.BOTTOM_QUARTILE_SMALL_MOVE:.0%}, ours **{pred['bottom_quartile_small_move']:.0%}**", {}),
        (f"P(VPIN in top quartile | next |return| > 0.75%): paper > {PN.INSURANCE_50_250:.0%}, ours **{pred['insurance_50_250']:.0%}**", {}),
        (f"Large move while VPIN stays in its top quartile (Table 5): paper **{PN.TRUE_POSITIVE_10_350:.0%}**, ours **{pred['true_positive_10_350']:.0%}** at (10, 350)", {}),
        ("Low VPIN = calm reproduces; the warning value is weaker.", {"bold": True, "color": NAVY}),
    ], size=14, space=10)

    # 11. Scorecard
    s = slide_with_title(prs, "Reproduction scorecard", (
        "Summary of the reproduction. The verdict rule is fixed in code (scripts/make_report.py): ours/paper "
        ">= 0.8 reproduced, 0.4-0.8 weaker, below 0.4 much weaker. Mechanics reproduce; predictive claims are "
        "weaker. Source: results/report/scorecard.csv."))
    sc = pd.read_csv(ROOT / "results" / "report" / "scorecard.csv")
    colours = {"reproduced": GREEN, "weaker": ORANGE, "much weaker": RED, "not reproduced": RED, "partly": ORANGE}
    fills = {(i, 3): colours.get(v, MUTED) for i, v in enumerate(sc["Verdict"])}
    table(s, sc, (0.64, 2.35, 12.05, 4.6), widths=[6.6, 1.6, 2.35, 1.5], size=11, fills=fills)

    # 12. Overfitting
    s = slide_with_title(prs, "How could these results be overfit?", (
        "Critique, ~1.5 min (required slide). Four ways the paper's numbers can be too good, and our check: a "
        "real-time pipeline (sigma, bucket size and CDF from the past only) with parameters frozen on the paper's "
        "period and tested on 2011-2026. The parameter pair with the best in-sample correlation keeps little of "
        "it out of sample. Source: results/extensions/ive_oos_comparison.csv."))
    o = k["ive_oos"]
    best = o["best in-sample true positive"]
    text(s, (0.64, 2.4, 6.3, 4.6), [
        ("In the paper", {"bullet": False, "bold": True, "color": NAVY, "size": 16}),
        "The CDF of VPIN is built from the **whole sample**, future included.",
        "Bucket size and window are picked by **scanning grids** on the same data (Figs. 10, 12, 14); Table 5 reports the best cell.",
        "**No out-of-sample** period. One flash crash = one observation.",
        ("Our check", {"bullet": False, "bold": True, "color": NAVY, "size": 16}),
        "Real-time VPIN: σ, V and CDF from **past data only**; parameters frozen in 2009–11, tested on 2011–26.",
        f"Best in-sample true-positive pair {tuple(k['ive_chosen']['best in-sample true positive'])}: "
        f"**{best['in-sample']['VPIN']['true_positive_top']:.0%} → {best['out-of-sample']['VPIN']['true_positive_top']:.0%}** "
        f"out of sample (bottom quartile: {best['out-of-sample']['VPIN']['true_positive_bottom']:.0%}).",
    ], size=14, space=6)
    picture(s, figs["is_oos"], (7.1, 2.4, 5.9, 4.4))

    # 13. E1
    bb = k["btc_buckets"]["50_50"]
    tr = k["btc_trades"]
    s = slide_with_title(prs, "Extension 1: is bulk classification right? A ground-truth test", (
        "Upgrade, ~1 min. Binance BTCUSDT data mark the aggressor of every trade, so we know the true buy volume "
        "that BVC estimates — the paper never could. Same buckets, two classifications. Sources: "
        "results/extensions/summary.json, btc_bars_bvc_vs_truth.csv, btc_trade_days.csv."))
    picture(s, EXT / "figures" / "e1_btc_vpin_true_vs_bvc.png", (0.4, 2.35, 8.0, 2.75))
    text(s, (0.64, 5.2, 7.8, 1.9), [
        f"Bars: BVC gets the sign right for **{k['btc_bars']['direction_agreement_min']:.0%}–{k['btc_bars']['direction_agreement_max']:.0%}** of volume.",
        f"Buckets: BVC inflates |imbalance| **{bb['mean_abs_imbalance_bvc'] / bb['mean_abs_imbalance_true']:.1f}×**; the two VPINs correlate only **{bb['corr_vpin_bvc_true']:.2f}**.",
    ], size=14, space=6)
    text(s, (8.7, 2.45, 4.4, 4.6), [
        ("On 5 days with every trade", {"bullet": False, "bold": True, "color": NAVY, "size": 15}),
        f"Tick rule: **{tr['tick_accuracy_min']:.0%}–{tr['tick_accuracy_max']:.0%}** of volume classified right.",
        f"Bucket imbalance vs truth: tick rule **≥ {tr['corr_tick_min']:.2f}**, BVC **{tr['corr_bvc_1min_min']:.2f}–{tr['corr_bvc_1min_max']:.2f}** (1-min bars).",
        ("Caveat: Binance aggregates the fills of one order, which helps the tick rule.", {"size": 12, "color": MUTED}),
        ("The paper's claim that bulk beats trade-by-trade classification does not hold here.", {"bold": True, "color": NAVY}),
    ], size=14, space=8)

    # 14. E3
    s = slide_with_title(prs, "Extension 2: is VPIN more than volatility?", (
        "Upgrade, ~1 min. Lift = hit rate divided by how often the alarm is on; a signal that is always on has "
        "lift 1. With true labels VPIN has no positive link to future volatility; with BVC it does, because "
        "BVC turns price moves into imbalance. Trailing volatility beats both. Andersen and Bondarenko (2014) "
        "argued this from equity data; we confirm it with ground truth. Sources: btc_signal_comparison.csv, "
        "regressions.csv."))
    b50 = k["btc_signals"]["50"]
    df = pd.DataFrame([(sig.replace(" (trailing volatility)", " (trailing volatility)"), f"{r['corr']:.2f}", f"{r['insurance']:.0%}",
                        f"{r['alarm_rate']:.0%}", f"{r['lift']:.1f}×") for sig, r in b50.items()],
                      columns=["BTCUSDT, 2020–26 (50 buckets/day, n = 50)", "Corr with next |return|",
                               "P(top quartile | move > 0.75%)", "Time in top quartile", "Lift"])
    table(s, df, (0.64, 2.45, 12.05, 1.8), widths=[4.6, 2.0, 2.45, 1.85, 1.15], size=13)
    reg = [r for r in k["regressions"] if r["market"] == "BTC" and r["choice"] == "(50, 50)" and r["signal"] == "vpin"][0]
    reg_ive = [r for r in k["regressions"] if r["market"] == "IVE" and r["choice"] == "paper (50, 250)"][1]
    text(s, (0.64, 4.55, 12.0, 2.5), [
        f"VPIN from **true labels** is negatively related to the next move ({b50['VPIN (true labels)']['corr']:.2f}); bulk-classified VPIN is positive ({b50['VPIN (bulk classified)']['corr']:.2f}); **trailing volatility wins** ({b50['RV (trailing volatility)']['corr']:.2f}).",
        f"BVC imbalance moves with the bucket's own |return| ({bb['corr_abs_imbalance_with_same_bucket_abs_return_bvc']:.2f} vs {bb['corr_abs_imbalance_with_same_bucket_abs_return_true']:.2f} for the truth): BVC builds volatility into VPIN.",
        f"Regression with volatility and trade-intensity controls (Newey–West): VPIN adds ΔR² = **{reg['delta_r2']:.4f}** on BTC, **{reg_ive['delta_r2']:.4f}** on IVE out of sample.",
    ], size=14, space=8)

    # 15. E2
    s = slide_with_title(prs, "Extension 3: real-time VPIN out of sample, IVE 2011–2026", (
        "Upgrade, ~1 min. Fifteen years after the paper. Year by year, the correlation of VPIN with the next "
        "move is small and unstable, trailing volatility is higher almost every year, and the share of time the "
        "VPIN alarm is on drifts a lot — its CDF from the past does not fit the future. Source: "
        "results/extensions/ive_by_year.csv, ive_oos_comparison.csv."))
    picture(s, EXT / "figures" / "e2_ive_by_year.png", (0.4, 2.35, 12.5, 3.9))
    p250 = o["paper (50, 250)"]["out-of-sample"]
    text(s, (0.64, 6.25, 12.0, 0.9), [
        f"Paper's (50, 250), out of sample: corr VPIN **{p250['VPIN']['corr']:.2f}** vs trailing volatility **{p250['RV (trailing volatility)']['corr']:.2f}**; "
        f"lift **{p250['VPIN']['lift']:.1f}×** vs **{p250['RV (trailing volatility)']['lift']:.1f}×**.",
    ], size=14)

    # 16. E4
    ev = pd.DataFrame(k["events"])
    share = {m: ev[ev["market"] == m].iloc[0] for m in ("IVE", "BTC")}
    hits = lambda m, col: int(sum(v is True or v == 1.0 for v in ev.loc[ev["market"] == m, col]))
    n_ive, n_btc = int((ev["market"] == "IVE").sum()), int((ev["market"] == "BTC").sum())
    s = slide_with_title(prs, "Extension 4: crashes after the paper", (
        "Upgrade, ~45 s. Was the real-time alarm (CDF >= 0.9) on when each day's largest one-hour fall began? "
        "Compare each hit count with how often that alarm is on overall. On IVE, VPIN's alarm was on at every "
        "fall — the extension result most favourable to VPIN — but these are few events, several inside weeks of turmoil "
        "(Aug 2011, Mar 2020), when trailing volatility was also high. On BTC no signal was reliable. "
        "Source: results/extensions/crash_events.csv."))
    onoff = lambda v: "–" if v is None or (isinstance(v, float) and np.isnan(v)) else ("on" if v else "off")
    df = pd.DataFrame([(r["market"], r["day"], f"{r['drop_1h']:.1%}", onoff(r["vpin_alarm_on"]),
                        onoff(r.get("vpin_true_alarm_on")), onoff(r["rv_alarm_on"])) for r in ev.to_dict(orient="records")],
                      columns=["Market", "Day", "Largest 1-hour fall", "VPIN alarm", "VPIN alarm, true labels", "Volatility alarm"])
    fills = {(i, j): (GREEN if df.iat[i, j] == "on" else MUTED) for i in range(len(df)) for j in (3, 4, 5) if df.iat[i, j] != "–"}
    table(s, df, (0.64, 2.4, 7.6, 3.9), widths=[1.0, 1.5, 1.5, 1.15, 1.35, 1.1], size=13, fills=fills)
    text(s, (8.6, 2.4, 4.5, 4.6), [
        ("Hits vs how often the alarm is on", {"bullet": False, "bold": True, "color": NAVY, "size": 15}),
        f"IVE, VPIN: on at **{hits('IVE', 'vpin_alarm_on')} of {n_ive}** falls; on **{share['IVE']['vpin_alarm_share']:.0%}** of all the time.",
        f"IVE, volatility: **{hits('IVE', 'rv_alarm_on')} of {n_ive}**; on {share['IVE']['rv_alarm_share']:.0%} of the time.",
        f"BTC: VPIN **{hits('BTC', 'vpin_alarm_on')} of {n_btc}**, true-label VPIN **{hits('BTC', 'vpin_true_alarm_on')} of {n_btc}**, volatility **{hits('BTC', 'rv_alarm_on')} of {n_btc}**.",
        ("Few events: suggestive on IVE, nothing on BTC.", {"bold": True, "color": NAVY}),
    ], size=14, space=9)

    # 17. Critique and next steps
    s = slide_with_title(prs, "Critique and next steps", (
        "Critique ~1 min, next steps ~2 min. Keep it to what we tested. The authors disclose a patent on VPIN "
        "and a financial interest in it (title page)."))
    text(s, (0.64, 2.4, 6.0, 4.6), [
        ("Critique", {"bullet": False, "bold": True, "color": NAVY, "size": 17}),
        "Bulk classification **builds volatility into VPIN**; with true labels the predictive link disappears.",
        "Whole-sample CDF and grid-searched parameters: **look-ahead and selection** with no out-of-sample test.",
        "Main evidence is **one event** (6 May 2010); on IVE the warning depends on bar size and classifier.",
        "No baseline: the paper never compares VPIN with **plain volatility**, which wins in our tests.",
        "The authors hold a **patent** on VPIN and disclose a financial interest.",
    ], size=14, space=7)
    text(s, (6.9, 2.4, 6.2, 4.6), [
        ("With three more months", {"bullet": False, "bold": True, "color": NAVY, "size": 17}),
        "E-mini futures with **exchange aggressor flags** (e.g. CME MDP 3.0): the paper's market, with ground truth.",
        "VPIN as a **filter for a market-making strategy**: does it reduce adverse-selection losses after costs?",
        "Correct the grid search for **multiple testing** (White's reality check, deflated statistics).",
        "Combine with **HAR volatility forecasts** and test VPIN's incremental value out of sample.",
    ], size=14, space=7)

    # 18. Repository
    s = slide_with_title(prs, "Repository: how to run it", (
        "Code is ours, written from scratch. One command per stage; every number in the README and these slides "
        "is read from results/. Raw data are downloaded by scripts, not committed."))
    tree = ("src/vpin/\n  data.py        IVE ticks, BTC klines and trades; cancelled trades\n"
            "  bars.py        time bars, within-day price changes\n  classify.py    BVC, tick rule, Lee-Ready\n"
            "  buckets.py     equal-volume buckets\n  metric.py      VPIN, full-sample and real-time CDF\n"
            "  analysis.py    Tables 1–5, Figures 10–14\n  realtime.py    no-look-ahead pipeline\n"
            "  paper_numbers.py  the paper's numbers with pages\nscripts/  download, reproduce, extensions, report, slides\n"
            "tests/    unit tests (incl. Table 1 formula check)\nDEVIATIONS.md  every deviation and silent decision")
    tb = text(s, (0.64, 2.4, 7.2, 4.6), [(line, {"bullet": False, "size": 12, "space": 1}) for line in tree.split("\n")])
    for p in tb.text_frame.paragraphs:
        for r in p.runs:
            r.font.name = "Courier New"
    text(s, (8.1, 2.4, 5.0, 4.6), [
        ("Run", {"bullet": False, "bold": True, "color": NAVY, "size": 16}),
        ("pip install -r requirements.txt", {"bullet": False, "size": 12}),
        ("pytest -q", {"bullet": False, "size": 12}),
        ("python scripts/download_kibot.py", {"bullet": False, "size": 12}),
        ("python scripts/download_binance.py", {"bullet": False, "size": 12}),
        ("python scripts/reproduce.py", {"bullet": False, "size": 12}),
        ("python scripts/extensions.py", {"bullet": False, "size": 12}),
        ("python scripts/make_report.py", {"bullet": False, "size": 12, "space": 12}),
        (f"Free data: {data['ticks']:,} IVE trades in the paper's period; BTCUSDT 2020–2026.", {"bullet": False, "size": 12, "color": MUTED}),
    ], size=12)

    # 19. Final
    prs.slides.add_slide(layout(prs, "Final_1"))
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out)
    print(f"saved {out} ({len(prs.slides)} slides)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper", type=Path, help="the paper's PDF, for figure crops")
    parser.add_argument("--make-template", type=Path, help="deck in the HSE template to strip into docs/")
    parser.add_argument("--out", type=Path, default=DOCS / "presentation.pptx")
    args = parser.parse_args()
    if args.make_template:
        make_template(args.make_template, TEMPLATE)
        print(f"template saved to {TEMPLATE}")
        return
    build(args.paper, args.out)


if __name__ == "__main__":
    main()
