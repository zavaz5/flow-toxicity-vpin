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


PAPER_FILL = RGBColor(0xEB, 0x8C, 0x3C)

# Order of the talk: 16 slides for 15 minutes. Every backup slide's main finding is also on a
# main slide (the scorecard, Result 2, Extension 3), so the talk loses no result.
MAIN_ORDER = [
    None,  # title slide (no title placeholder text match needed: it is always first)
    "Why toxic order flow matters",
    "Method: from PIN to VPIN, measured in volume time",
    "Method: bulk volume classification",
    "Data, and what is estimated, chosen and evaluated",
    "Result 1: the flash crash, paper vs ours",
    "Result 2: does VPIN predict the next bucket's volatility?",
    "Reproduction scorecard",
    "How could these results be overfit?",
    "Extension 1: is bulk classification right? A ground-truth test",
    "Extension 2: is VPIN more than volatility?",
    "Extension 3: a known-answer test of VPIN (pre-registered)",
    "Extension 4: the fix on real data",
    "What our work adds to the paper",
    "Critique and next steps",
    "FINAL",
]

# Backups after the final slide, in the order of the talk they support.
BACKUP_ORDER = [
    "Backup: the VPIN metric and how it is read",
    "Backup: the volume clock and the stability of VPIN",
    "Backup: high VPIN and large moves (Tables 4 and 5)",
    "Backup: the paper's predictive claims on every two-year window",
    "Backup: real-time VPIN out of sample, year by year",
    "Backup: crashes after the paper",
    "Backup: the known-answer test, every metric",
    "Backup: repository and how to run it",
]


def slide_title(slide) -> str:
    return slide.shapes.title.text if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""


def reorder(prs, order, backup_order):
    """Put slides in the order of the talk: title first, the listed titles, the final slide,
    then the backups in `backup_order`. A slide in neither list raises, so none is lost."""
    ids = prs.slides._sldIdLst
    entries = list(zip(list(ids), list(prs.slides)))
    title_first, final = entries[0], next(e for e in entries if e[1].slide_layout.name == "Final_1")
    by_title = {slide_title(sl): (el, sl) for el, sl in entries}
    main = [title_first] + [by_title[t] if t != "FINAL" else final for t in order[1:]]
    used = {id(e[0]) for e in main}
    backup = sorted((e for e in entries if id(e[0]) not in used), key=lambda e: backup_order.index(slide_title(e[1])))
    for el, _ in entries:
        ids.remove(el)
    for el, _ in main + backup:
        ids.append(el)


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
    get = lambda c, per, sig, col="corr": df[(df["choice"] == c) & (df["period"] == per) & (df["signal"] == sig)][col].iloc[0]
    x = np.arange(len(choices))
    fig, ax = plt.subplots(figsize=(6.2, 3.8))
    w = 0.27
    for dx, per, sig, kw in [(-w, "in-sample", "VPIN", {"color": P.OURS, "alpha": 0.45, "label": "VPIN, in sample (2009–11)"}),
                             (0, "out-of-sample", "VPIN", {"color": P.OURS, "label": "VPIN, out of sample (2011–26)"}),
                             (w, "out-of-sample", "RV (trailing volatility)", {"color": P.GREY, "label": "trailing volatility, out of sample"})]:
        ax.bar(x + dx, [get(c, per, sig) for c in choices], w, yerr=[get(c, per, sig, "corr_se") for c in choices],
               capsize=2, error_kw={"lw": 0.8}, **kw)
    labels = [c.replace("paper Table 5", "paper's\nTable 5").replace("best in-sample ", "best in-sample\n") for c in choices]
    ax.set_xticks(x, labels, fontsize=8)
    ax.set_ylabel("Corr(ln signal, next |return|) ± s.e.")
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
            ph.text = "Group 8"
        elif idx == 4:
            ph.text = "DAVID EASLEY, MARCOS LÓPEZ DE PRADO AND MAUREEN O'HARA"
        else:
            drop(ph)
    text(s, (1.12, 6.0, 7, 1.0), [("Review of Financial Studies 25(5), 2012", {"bullet": False, "size": 14, "color": NAVY}),
                                  ("Nazarov · Doroshenko · Burlakov · Daunov · Sergeev", {"bullet": False, "size": 14, "color": MUTED})])
    s.notes_slide.notes_text_frame.text = (
        "Timing (15 min): problem 2 · method 3 · results and reproduction 5 · "
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
    s = slide_with_title(prs, "Backup: the VPIN metric and how it is read", (
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

    u250, u350 = pred["uncertainty"]["50_250"], pred["uncertainty"]["10_350"]
    o = k["ive_oos"]
    pm = lambda st, as_pct=False: (f"{st['value']:.0%} ± {st['se']:.0%}" if as_pct else f"{st['value']:.2f} ± {st['se']:.2f}")
    ci = lambda st, as_pct=False: (f"[{st['lo']:.0%}, {st['hi']:.0%}]" if as_pct else f"[{st['lo']:.2f}, {st['hi']:.2f}]")
    se = lambda r, key, as_pct=False: (f"{r[key]:.0%} ± {r[key + '_se']:.0%}" if as_pct else f"{r[key]:.2f} ± {r[key + '_se']:.2f}")

    # 6. Data and objectives: two set-up tables (no results), so sources are not mixed
    s = slide_with_title(prs, "Data, and what is estimated, chosen and evaluated", (
        "Method, ~1 min. Top table, data: CME data are paid, so we use the only free tick history with quotes "
        "we found: IVE from Kibot, which covers the flash crash. Binance BTC data give the true aggressor side, "
        "which the paper never had. The table compares set-ups, not results. All deviations with reasons: "
        "DEVIATIONS.md. Bottom table anticipates 'what was the objective?'. VPIN is not trained: it is a moment "
        "estimator (average absolute imbalance over volume) of the PIN ratio, so it has no loss function. The "
        "only optimisation in the paper is the choice of bucket size and window: they scan grids and report the "
        "best cell, i.e. the selection objective IS the evaluation statistic, on the same data. We separate "
        "the two: select on 2009-11, evaluate on 2011-26."))
    df = pd.DataFrame([
        ("Market and hours", "E-mini S&P 500 and WTI crude futures; almost 24 hours", "IVE (S&P 500 Value ETF) ticks with quotes, 09:30–16:00 New York; BTCUSDT for extensions"),
        ("Period", "Jan 2008 – Aug 2011 (incl. 2008 crisis)", f"{data['period'][0]} – {data['period'][1]}; out of sample to Sep 2026"),
        ("Classification, settings", "bulk, one-minute bars; V = ADV/50, n = 50, whole-sample σ and CDF", "identical, plus 10-second bars and Lee-Ready"),
    ], columns=["Data", "Paper", "Ours"])
    table(s, df, (0.64, 2.25, 12.05, 1.1), widths=[2.2, 4.65, 5.2], size=11)
    df = pd.DataFrame([
        ("Estimate PIN (original model)", "Maximise the likelihood of a Poisson mixture: α, μ, ε, δ", "daily buy and sell counts"),
        ("Estimate VPIN", "Nothing is fitted: average |sell − buy volume| / V, a moment estimate of αμ / (αμ + 2ε)", "the last n buckets"),
        ("Inputs σ and V", "Standard deviation of one-minute price changes; average daily volume / 50", "paper: whole sample · ours, real-time: previous 250 days"),
        ("Choose buckets/day and n", "Paper: grid cell with the highest corr(ln VPIN, next |return|) (Fig. 10) or true-positive rate (Table 5)", "paper: the evaluation sample itself · ours: 2009–11, then frozen"),
        ("Evaluate", "Corr with next |return|; P(VPIN high | big move); true positives. We add lift and ΔR² over volatility", "paper: in sample · ours: 2011–26, out of sample"),
    ], columns=["Step", "Objective", "Data used"])
    table(s, df, (0.64, 3.8, 12.05, 1.8), widths=[2.2, 6.05, 3.8], size=11)
    text(s, (0.64, 6.25, 12.0, 1.1), [
        (f"Also removed: 42 IVE trades at prices like $0.08 that the exchanges **cancelled** on 6 May 2010. "
         f"{data['share_bars_no_price_change']:.0%} of IVE one-minute bars have no price change; bulk classification splits them 50/50. "
         "**±** on our numbers: block bootstrap over calendar months (1,000 replications), because VPIN windows overlap and volatility clusters.",
         {"size": 11, "color": MUTED}),
        ("**VPIN has no training objective.** The paper's only optimisation is the parameter search, and it maximises the statistic it then reports, on the same data. We select on 2009–11 and evaluate on 2011–26.",
         {"size": 12, "color": NAVY}),
    ], space=4)

    # 8. Flash crash
    s = slide_with_title(prs, "Result 1: the flash crash, paper vs ours", (
        "Results, ~1 min. Paper Fig. 4(a): CDF(VPIN) crossed 0.9 at least two hours before the crash. Ours, "
        f"one-minute bars: CDF above 0.9 from {fc['BVC, 1-minute bars']['first'][11:16]}, {fc['BVC, 1-minute bars']['lead_hours']:.1f} h before 14:32. "
        "With 10-second bars it crosses only during the crash, and with Lee-Ready never. One event, so no ± is "
        "possible; the point is that the warning depends on the classification choice. "
        "Source: results/reproduction/flash_crash.csv."))
    picture(s, figs["paper_fig4"], (0.4, 2.4, 4.1, 3.4))
    text(s, (0.4, 5.75, 4.1, 0.4), [("Paper, Fig. 4(a): E-mini, one-minute bars", {"bullet": False, "size": 11, "color": MUTED, "align": PP_ALIGN.CENTER})])
    picture(s, REP / "figures" / "fig4_flash_crash.png", (4.6, 2.45, 8.5, 2.9))
    text(s, (4.6, 5.3, 8.5, 0.35), [("Ours: IVE, 6 May 2010, three classification schemes", {"bullet": False, "size": 11, "color": MUTED, "align": PP_ALIGN.CENTER})])
    lr = fc["Lee-Ready, trade by trade"]
    text(s, (4.7, 5.7, 8.3, 1.4), [
        f"**One-minute bars:** CDF > 0.9 from {fc['BVC, 1-minute bars']['first'][11:16]}, **{fc['BVC, 1-minute bars']['lead_hours']:.1f} h** before the fall, as the paper says.",
        f"**10-second bars:** first above 0.9 at {fc['BVC, 10-second bars']['first'][11:16]}, during the fall. **Lee-Ready:** never (max CDF {lr['max_cdf']:.2f}).",
        "One event: no ± possible. The warning depends on the classification choice.",
    ], size=13, space=3)

    # 9. Volume clock + stability: the paper's table and ours, separately
    s = slide_with_title(prs, "Backup: the volume clock and the stability of VPIN", (
        "Backup; rows 1-2 of the scorecard summarise it in the talk. Two separate tables: the paper's Table 1 and ours. Ours drops 6 May 2010 (IVE fell to "
        "about half its price for minutes; one change of ~100 sigma sets the kurtosis) and overnight changes "
        "(a 24-hour futures market has none). Last column: in how many paired bootstrap replications volume "
        "time has the lower value; green = at least 95%. Sources: results/reproduction/table1_*_bootstrap.csv, "
        "summary.json (stability)."))
    stats = ["Kurt", "J-B*", "L-B*", "White*", "Max"]
    text(s, (0.64, 2.3, 4.6, 0.4), [("Paper: E-mini, 2008–11", {"bullet": False, "bold": True, "color": NAVY, "size": 14})])
    paper_t1 = pd.DataFrame([(st, f"{PN.TABLE1_50['Chrono time'][st]:.2f}", f"{PN.TABLE1_50['Volume time'][st]:.2f}") for st in stats],
                            columns=["50 draws a day", "Clock", "Volume"])
    table(s, paper_t1, (0.64, 2.75, 4.4, 2.55), widths=[1.7, 1.35, 1.35], size=12,
          fills={(i, 2): GREEN for i, st in enumerate(stats) if PN.TABLE1_50["Volume time"][st] < PN.TABLE1_50["Chrono time"][st]})
    b1 = k["table1_boot"]["50"]
    text(s, (5.5, 2.3, 7.5, 0.4), [("Ours: IVE, 2009–11 (± s.e.)", {"bullet": False, "bold": True, "color": NAVY, "size": 14})])
    ours_t1 = pd.DataFrame([(st, f"{b1[st]['Chrono time']:.2f} ± {b1[st]['Chrono ±']:.2f}", f"{b1[st]['Volume time']:.2f} ± {b1[st]['Volume ±']:.2f}",
                             f"{b1[st]['P(volume < clock)']:.3f}") for st in stats],
                           columns=["50 draws a day", "Clock", "Volume", "P(volume lower)"])
    table(s, ours_t1, (5.5, 2.75, 7.4, 2.55), widths=[1.6, 2.05, 1.95, 1.8], size=12,
          fills={(i, 3): GREEN for i, st in enumerate(stats) if b1[st]["P(volume < clock)"] >= 0.95})
    sig = k["table1_significant"]
    text(s, (0.64, 5.5, 12.4, 1.6), [
        f"Ours: volume time is **significantly** lower on {sig['50']} of the 4 test statistics at 50 draws a day and {sig['100']} of 4 at 100; tails and White* clearly improve, autocorrelation (L-B*) does not at 50.",
        f"**Stability (Fig. 5):** restarting the buckets 0, 1, …, 999 bars later changes VPIN by {k['stability']['ours']:.1%} of its mean on IVE; the paper reports {k['stability']['paper']:.1%} for the E-mini.",
    ], size=13, space=6)

    # 10. Correlation surface
    w = k["windows"]
    n_windows = w["IVE"]["windows"] + w["BTC"]["windows"]
    # The slide says no window reaches the paper's numbers; fail loudly if the results ever disagree.
    assert max(w[m]["corr_50_250"][1] for m in w) < PN.CORR_50_250
    assert max(w[m]["insurance_50_250"][1] for m in w) < PN.INSURANCE_50_250
    s = slide_with_title(prs, "Result 2: does VPIN predict the next bucket's volatility?", (
        "Results, ~1 min. Paper Fig. 10 vs the same computation on IVE. Each caption gives its own source's "
        "number. The paper's interval (footnote 29) treats buckets as independent; neighbouring VPIN values "
        "share almost all of their window, so it is far too narrow. With the same iid formula ours would be "
        f"[{pred['corr_50_250_fisher_ci_iid'][0]:.2f}, {pred['corr_50_250_fisher_ci_iid'][1]:.2f}]; month blocks give {ci(u250['corr'])}. "
        f"Every window: the paper's exact in-sample method on all {n_windows} two-year windows of IVE and BTC; none "
        "reaches the paper's correlation or insurance value (backup slide). "
        "Source: results/reproduction/parameter_grid.csv, summary.json, results/extensions/windows/."))
    picture(s, figs["paper_fig10"], (0.4, 2.35, 5.6, 3.9))
    text(s, (0.4, 6.25, 5.6, 0.7), [(f"Paper (E-mini): {PN.CORR_50_250:.2f} at (50, 250), 95% CI [{PN.CORR_50_250_CI[0]:.3f}, {PN.CORR_50_250_CI[1]:.3f}] (iid)",
                                     {"bullet": False, "size": 12, "color": MUTED, "align": PP_ALIGN.CENTER})])
    picture(s, REP / "figures" / "fig10_correlation.png", (6.2, 2.35, 4.6, 3.9))
    text(s, (6.2, 6.25, 4.6, 0.7), [(f"Ours (IVE): {pm(u250['corr'])} at (50, 250), 95% CI {ci(u250['corr'])}",
                                     {"bullet": False, "size": 12, "color": MUTED, "align": PP_ALIGN.CENTER})])
    text(s, (10.9, 2.35, 2.3, 4.7), [
        ("On IVE", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        ("Same sign; 0.40 is outside our interval.", {"bullet": False, "size": 12, "space": 10}),
        ("About the ±", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        (f"An iid interval would give ours as [{pred['corr_50_250_fisher_ci_iid'][0]:.2f}, {pred['corr_50_250_fisher_ci_iid'][1]:.2f}]: overlapping windows make it far too narrow.",
         {"bullet": False, "size": 12, "space": 10}),
        ("On every window", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        (f"None of {n_windows} two-year windows (IVE, BTC) reaches the paper's {PN.CORR_50_250:.2f}, nor its > {PN.INSURANCE_50_250:.0%} "
         f"for big moves; we could detect ≥ {k['inference']['power']['mde_80pct_power']:.2f}.", {"bullet": False, "size": 12}),
    ], size=12)

    # 11. Tables 4 and 5
    s = slide_with_title(prs, "Backup: high VPIN and large moves (Tables 4 and 5)", (
        "Results, ~1 min. The heat maps are two separate panels: the paper's Table 4a and ours. Low VPIN does "
        "mean calm in both. The warning claims are weaker on IVE; the Table 5 number is consistent with ours "
        "only because our interval is wide (few stays in the top quartile at 10 buckets a day). Sources: "
        "results/reproduction/table4a.csv, table5.csv, summary.json (uncertainty)."))
    picture(s, REP / "figures" / "table4a_conditional.png", (0.3, 2.3, 8.6, 4.9))
    text(s, (9.0, 2.35, 4.1, 2.0), [
        ("Paper reports (E-mini)", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        (f"Bottom-quartile VPIN → next |return| < 0.25%: > {PN.BOTTOM_QUARTILE_SMALL_MOVE:.0%}", {"size": 12}),
        (f"P(VPIN top quartile | move > 0.75%): > {PN.INSURANCE_50_250:.0%}", {"size": 12}),
        (f"Big move while VPIN stays high, (10, 350): {PN.TRUE_POSITIVE_10_350:.1%}", {"size": 12}),
    ], size=12, space=4)
    text(s, (9.0, 4.45, 4.1, 2.6), [
        ("On IVE (± s.e.)", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        (f"Bottom quartile → < 0.25%: **{u250['bottom_small']['value']:.1%} ± {u250['bottom_small']['se']:.1%}**", {"size": 12}),
        (f"P(top quartile | move > 0.75%): **{pm(u250['insurance'], True)}**", {"size": 12}),
        (f"Big move while VPIN stays high, (10, 350): **{pm(u350['tp_top'], True)}**, 95% CI {ci(u350['tp_top'], True)}", {"size": 12}),
        ("Low VPIN = calm reproduces; the warning value is weaker or uncertain.", {"bold": True, "color": NAVY, "size": 12}),
    ], size=12, space=4)

    # 12. Scorecard: two tables, same row numbers
    s = slide_with_title(prs, "Reproduction scorecard", (
        "Summary. Left: what the paper reports. Right: what we find on IVE, with ± and a verdict that uses only "
        "our own data: reproduced if the paper's value is inside our 95% interval and the effect's direction is "
        "significant; inconclusive if inside but not significant; weaker if outside but the direction holds; "
        "not reproduced otherwise. Rule in scripts/make_report.py. Sources: results/report/scorecard_*.csv."))
    sp = pd.read_csv(ROOT / "results" / "report" / "scorecard_paper.csv")
    so = pd.read_csv(ROOT / "results" / "report" / "scorecard_ours.csv")
    short_ours = so.iloc[:, 1].tolist()
    short_ours[1] = f"{sig['50']} of 4 / {sig['100']} of 4 significant"
    short_ci = ["–" if "event" in c or "dispersion" in c else ("P ≥ 0.95" if "paired" in c else c) for c in so.iloc[:, 2]]
    text(s, (0.4, 2.2, 7.7, 0.35), [("Paper reports: E-mini, 2008–11", {"bullet": False, "bold": True, "color": NAVY, "size": 13})])
    table(s, sp.iloc[:, :3].rename(columns={sp.columns[2]: "Reported"}), (0.4, 2.6, 7.7, 4.5), widths=[0.35, 5.75, 1.6], size=10)
    text(s, (8.25, 2.2, 4.75, 0.35), [("Ours: IVE, 2009–11", {"bullet": False, "bold": True, "color": NAVY, "size": 13})])
    ours_tab = pd.DataFrame({"#": so["#"], "Ours (± s.e.)": short_ours, "95% interval": short_ci, "Verdict": so["Verdict"]})
    colours = {"reproduced": GREEN, "weaker": ORANGE, "partly": ORANGE, "inconclusive": MUTED, "not reproduced": RED}
    table(s, ours_tab, (8.25, 2.6, 4.75, 4.5), widths=[0.35, 1.6, 1.3, 1.5], size=10,
          fills={(i, 3): colours.get(v, MUTED) for i, v in enumerate(so["Verdict"])})

    # 13. Overfitting
    best = o["best in-sample true positive"]
    s = slide_with_title(prs, "How could these results be overfit?", (
        "Critique, ~1.5 min (required slide). Four ways the paper's numbers can be too good, and our check: a "
        "real-time pipeline (sigma, bucket size and CDF from the past only) with parameters frozen on the paper's "
        "period and tested on 2011-2026. Error bars are ± one bootstrap standard error. "
        "Source: results/extensions/ive_oos_comparison.csv."))
    text(s, (0.64, 2.4, 6.3, 4.6), [
        ("In the paper", {"bullet": False, "bold": True, "color": NAVY, "size": 16}),
        "The CDF of VPIN is built from the **whole sample**, future included.",
        "Bucket size and window are picked by **scanning grids** on the same data (Figs. 10, 12, 14); Table 5 reports the best cell.",
        "**No out-of-sample** period; its ± assumes independent buckets. One flash crash = one observation.",
        ("Our check", {"bullet": False, "bold": True, "color": NAVY, "size": 16}),
        "Real-time VPIN: σ, V and CDF from **past data only**; parameters frozen in 2009–11, tested on 2011–26.",
        f"Best in-sample true-positive pair {tuple(k['ive_chosen']['best in-sample true positive'])}: "
        f"**{se(best['in-sample']['VPIN'], 'true_positive_top', True)} → {se(best['out-of-sample']['VPIN'], 'true_positive_top', True)}** "
        f"out of sample (bottom quartile: {se(best['out-of-sample']['VPIN'], 'true_positive_bottom', True)}).",
    ], size=14, space=6)
    picture(s, figs["is_oos"], (7.1, 2.4, 5.9, 4.4))

    # 14. E1
    bb = k["btc_buckets"]["50_50"]
    bse = bb["se"]
    tr = k["btc_trades"]
    bars_k = k["btc_bars"]
    s = slide_with_title(prs, "Extension 1: is bulk classification right? A ground-truth test", (
        "Upgrade, ~1 min. Binance BTCUSDT data mark the aggressor of every trade, so we know the true buy volume "
        "that BVC estimates — the paper never could. Same buckets, two classifications. ± by month blocks; the "
        "trade-day ranges are across 5 days. Sources: results/extensions/summary.json, "
        "btc_bars_bvc_vs_truth.csv, btc_trade_days.csv."))
    picture(s, EXT / "figures" / "e1_btc_vpin_true_vs_bvc.png", (0.4, 2.35, 8.0, 2.75))
    text(s, (0.64, 5.2, 7.8, 1.9), [
        f"Bars: BVC gets the sign right for **{bars_k['direction_agreement']:.1%} ± {bars_k['direction_agreement_se']:.1%}** of volume.",
        f"Buckets: BVC inflates |imbalance| **{bse['imbalance_inflation']:.1f}×**; the two VPINs correlate only **{bb['corr_vpin_bvc_true']:.2f} ± {bse['corr_vpin_bvc_true']:.2f}**.",
    ], size=14, space=6)
    text(s, (8.7, 2.45, 4.4, 4.6), [
        ("On 5 days with every trade", {"bullet": False, "bold": True, "color": NAVY, "size": 15}),
        f"Tick rule: **{tr['tick_accuracy_min']:.0%}–{tr['tick_accuracy_max']:.0%}** of volume classified right.",
        f"Bucket imbalance vs truth: tick rule **≥ {tr['corr_tick_min']:.2f}**, BVC **{tr['corr_bvc_1min_min']:.2f}–{tr['corr_bvc_1min_max']:.2f}** (1-min bars).",
        ("Ranges are across the 5 days. Caveat: Binance aggregates the fills of one order, which helps the tick rule.", {"size": 12, "color": MUTED}),
        ("The paper's claim that bulk beats trade-by-trade classification does not hold here.", {"bold": True, "color": NAVY}),
    ], size=14, space=8)

    # 15. E3
    s = slide_with_title(prs, "Extension 2: is VPIN more than volatility?", (
        "Upgrade, ~1 min. One data source (BTC), three signals. Lift = hit rate divided by how often the alarm "
        "is on; a signal that is always on has lift 1. With true labels VPIN has no positive link to future "
        "volatility; with BVC it does, because BVC turns price moves into imbalance. Trailing volatility beats "
        "both. Andersen and Bondarenko (2014) made this argument; we confirm it with ground truth. "
        "Sources: btc_signal_comparison.csv, regressions.csv."))
    b50 = k["btc_signals"]["50"]
    df = pd.DataFrame([(sig_name, se(r, "corr"), se(r, "insurance", True), f"{r['alarm_rate']:.0%}", se(r, "lift"))
                       for sig_name, r in b50.items()],
                      columns=["BTCUSDT 2020–26, 50 buckets/day, n = 50", "Corr with next |return|",
                               "P(top quartile | move > 0.75%)", "Time in top quartile", "Lift"])
    table(s, df, (0.64, 2.45, 12.05, 1.8), widths=[4.3, 2.1, 2.45, 1.75, 1.45], size=13)
    reg = [r for r in k["regressions"] if r["market"] == "BTC" and r["choice"] == "(50, 50)" and r["signal"] == "vpin"][0]
    reg_ive = [r for r in k["regressions"] if r["market"] == "IVE" and r["choice"] == "paper (50, 250)" and r["period"] == "out-of-sample"][0]
    text(s, (0.64, 4.55, 12.0, 2.5), [
        "VPIN from **true labels** is negatively related to the next move; bulk-classified VPIN is positive; **trailing volatility wins**.",
        f"BVC imbalance moves with the bucket's own |return| ({bb['corr_abs_imbalance_with_same_bucket_abs_return_bvc']:.2f} ± {bse['corr_abs_imbalance_with_same_bucket_abs_return_bvc']:.2f} vs {bb['corr_abs_imbalance_with_same_bucket_abs_return_true']:.2f} ± {bse['corr_abs_imbalance_with_same_bucket_abs_return_true']:.2f} for the truth): BVC builds volatility into VPIN.",
        f"Regression with volatility and trade-intensity controls: VPIN adds ΔR² = **{reg['delta_r2']:.4f} ± {reg['delta_r2_se']:.4f}** on BTC, **{reg_ive['delta_r2']:.4f} ± {reg_ive['delta_r2_se']:.4f}** on IVE out of sample.",
    ], size=14, space=8)

    # 16. E2
    s = slide_with_title(prs, "Backup: real-time VPIN out of sample, year by year", (
        "Upgrade, ~1 min. Fifteen years after the paper, one data source. Year by year, VPIN's correlation with "
        "the next move is small and unstable, trailing volatility is higher almost every year, and the share of "
        "time the VPIN alarm is on drifts a lot — a CDF from the past does not fit the future. Source: "
        "results/extensions/ive_by_year.csv, ive_oos_comparison.csv."))
    picture(s, EXT / "figures" / "e2_ive_by_year.png", (0.4, 2.35, 12.5, 3.9))
    p250 = o["paper (50, 250)"]["out-of-sample"]
    text(s, (0.64, 6.25, 12.0, 0.9), [
        f"Paper's (50, 250), 2011–26: corr VPIN **{se(p250['VPIN'], 'corr')}** vs trailing volatility **{se(p250['RV (trailing volatility)'], 'corr')}**; "
        f"lift **{se(p250['VPIN'], 'lift')}** vs **{se(p250['RV (trailing volatility)'], 'lift')}**.",
    ], size=14)

    # 17. E4
    ev = pd.DataFrame(k["events"])
    al = pd.DataFrame(k["alarms"])
    s = slide_with_title(prs, "Backup: crashes after the paper", (
        "Upgrade, ~45 s. Was the real-time alarm (CDF >= 0.9) on when each day's largest one-hour fall began? "
        "Compare hits with how often the alarm is on overall. The binomial p-value assumes falls are "
        "independent draws, which they are not (several fall inside weeks of turmoil, e.g. Aug 2011, Mar 2020), "
        "so it is a rough guide. On IVE VPIN's alarm was on at every fall — the extension result most "
        "favourable to VPIN. Source: results/extensions/crash_events.csv, crash_alarm_summary.csv."))
    onoff = lambda v: "–" if v is None or (isinstance(v, float) and np.isnan(v)) else ("on" if v else "off")
    df = pd.DataFrame([(r["market"], r["day"], f"{r['drop_1h']:.1%}", onoff(r["vpin_alarm_on"]),
                        onoff(r.get("vpin_true_alarm_on")), onoff(r["rv_alarm_on"])) for r in ev.to_dict(orient="records")],
                      columns=["Market", "Day", "Largest 1-hour fall", "VPIN alarm", "VPIN alarm, true labels", "Volatility alarm"])
    fills = {(i, j): (GREEN if df.iat[i, j] == "on" else MUTED) for i in range(len(df)) for j in (3, 4, 5) if df.iat[i, j] != "–"}
    table(s, df, (0.64, 2.4, 7.6, 3.9), widths=[1.0, 1.5, 1.5, 1.15, 1.35, 1.1], size=13, fills=fills)
    names = {"vpin": "VPIN", "vpin_true": "VPIN, true labels", "rv": "Volatility"}
    al_df = pd.DataFrame([(a["market"], names[a["signal"]], f"{a['hits']} of {a['falls']}", f"{a['alarm_share']:.0%}",
                           f"{a['p_value_binomial']:.3f}" if a["p_value_binomial"] >= 0.001 else "< 0.001")
                          for a in al.to_dict(orient="records")],
                         columns=["", "Alarm", "Hits", "On overall", "p"])
    table(s, al_df, (8.5, 2.4, 4.45, 2.6), widths=[0.6, 1.5, 0.8, 0.8, 0.75], size=11)
    text(s, (8.5, 5.2, 4.6, 1.8), [
        ("p: chance of that many hits if the alarm were on at random with its overall rate (falls treated as independent).", {"size": 11, "color": MUTED}),
        ("IVE: VPIN on at every fall. BTC: nothing reliable. Few events.", {"bold": True, "color": NAVY, "size": 13}),
    ], size=12, space=6)

    # 18. Critique and next steps
    s = slide_with_title(prs, "Critique and next steps", (
        "Critique ~1 min, next steps ~2 min. Keep it to what we tested. The authors disclose a patent on VPIN "
        "and a financial interest in it (title page)."))
    text(s, (0.64, 2.4, 6.0, 4.6), [
        ("Critique", {"bullet": False, "bold": True, "color": NAVY, "size": 17}),
        "Bulk classification **builds volatility into VPIN**; with true labels the predictive link disappears.",
        "Whole-sample CDF and grid-searched parameters: **look-ahead and selection** with no out-of-sample test.",
        "Main evidence is **one event** (6 May 2010); on IVE the warning depends on bar size and classifier.",
        "No baseline: the paper never compares VPIN with **plain volatility**, which wins in our tests.",
        "Its **±** treats overlapping buckets as independent: far too narrow.",
        "The authors hold a **patent** on VPIN and disclose a financial interest.",
    ], size=14, space=7)
    text(s, (6.9, 2.4, 6.2, 4.6), [
        ("With three more months", {"bullet": False, "bold": True, "color": NAVY, "size": 17}),
        "E-mini futures with **exchange aggressor flags** (e.g. CME MDP 3.0): the paper's market, with ground truth.",
        "VPIN as a **filter for a market-making strategy**: does it reduce adverse-selection losses after costs?",
        "Correct the grid search for **multiple testing** (White's reality check, deflated statistics).",
        "Combine with **HAR volatility forecasts** and test VPIN's incremental value out of sample.",
    ], size=14, space=7)

    # 19. Repository
    s = slide_with_title(prs, "Backup: repository and how to run it", (
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

    # ---------- new slides: all windows, simulation, the fix, inference, contribution ----------
    EXTD = ROOT / "results" / "extensions"
    s = slide_with_title(prs, "Backup: the paper's predictive claims on every two-year window", (
        "Backup; the Result 2 slide summarises it in the talk. The paper's exact in-sample method on every two-year window, starting each January and "
        "July: 31 windows of IVE, 10 of BTC. Every window is shown; none was selected. This analysis was run once "
        "as an exploration before we wrote the pre-registration, and we say so. Not a power problem: the "
        "reproduction can detect any correlation of 0.13 or more with 80% power. Source: "
        "results/extensions/windows/."))
    picture(s, EXTD / "windows" / "windows.png", (0.4, 2.35, 8.4, 2.95))
    text(s, (0.64, 5.45, 8.2, 1.6), [
        (f"IVE: corr {w['IVE']['corr_50_250'][0]:.2f} to {w['IVE']['corr_50_250'][1]:.2f}; P(top quartile | big move) {w['IVE']['insurance_50_250'][0]:.0%} to {w['IVE']['insurance_50_250'][1]:.0%}.", {}),
        (f"BTC: corr {w['BTC']['corr_50_250'][0]:.2f} to {w['BTC']['corr_50_250'][1]:.2f}; P(top quartile | big move) {w['BTC']['insurance_50_250'][0]:.0%} to {w['BTC']['insurance_50_250'][1]:.0%}. Big moves are routine on BTC, so low VPIN scores as many true positives.", {}),
    ], size=13, space=5)
    text(s, (9.1, 2.45, 4.0, 1.6), [
        ("Paper reports (E-mini, 2008–11)", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        (f"corr {PN.CORR_50_250:.2f}; P(top quartile | big move) > {PN.INSURANCE_50_250:.0%}", {"size": 13}),
    ], size=13)
    text(s, (9.1, 4.2, 4.0, 2.8), [
        ("Our reading", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        ("No window on either market reaches the paper's numbers.", {"size": 13}),
        (f"Our reproduction could detect any correlation ≥ {k['inference']['power']['mde_80pct_power']:.2f} (80% power): the gap is not a matter of power.", {"size": 13}),
    ], size=13, space=6)

    sim_get = lambda wd, ver, m: next(r for r in k["simulation"]["summary"] if r["world"] == wd and r["version"] == ver and r["metric"] == m)
    d = k["simulation"]["decisions"]
    s = slide_with_title(prs, "Extension 3: a known-answer test of VPIN (pre-registered)", (
        "Upgrade, ~1.5 min. The gap: the paper validates VPIN (Appendix A.2) with buys and sells drawn straight from "
        "the PIN model: correct labels, no prices. Its empirical VPIN uses bulk classification, which needs prices, "
        "so that validation does not cover the method it uses. We simulate the paper's own model with a price "
        "and run the exact pipeline where the truth is known. Hypotheses, metrics and decision rules were written "
        "in docs/preregistration.md before the first run; its hash is in the run manifest. "
        "D2: in world V the paper's VPIN raises more alarms in volatile blocks, although informed "
        "trading never changes; true-label VPIN goes the other way (extra uninformed volume dilutes informed "
        "trading), the same sign as on real BTC. In world V the paper's VPIN tracks the true informed share at "
        "corr ~0.03. D3 did not hold: the paper's predictive statistic is not fooled in this calibration, because "
        "two effects cancel. D4: one-day sigma fixes the bias and keeps detection. ± = Monte Carlo s.e. "
        "Every metric with its error bar: backup slide. Source: results/extensions/simulation/."))
    text(s, (0.64, 2.3, 6.4, 2.1), [
        "**Gap in the paper:** its Monte Carlo (Appendix A.2) uses correctly labelled trades and no prices; its VPIN uses bulk classification, which needs prices.",
        "**Our model:** the paper's PIN model, plus a price: Δp = λ (buys − sells) + public noise. Informed flow moves the price; public noise does not involve any trader.",
        "**Worlds:** T = more informed trading in some blocks; V = more volatility and uninformed volume, informed trading unchanged; TV = both; 0 = neither.",
        f"**Same pipeline**, truth known, {k['simulation']['manifest']['reps']} replications per world, rules fixed before running.",
    ], size=12, space=4)
    verdict = lambda ok: "holds" if ok else "does not hold"
    dec = pd.DataFrame([
        ("D1", "true labels track informed trading", f"{d['D1_true_vpin_tracks_informed_trading']['M1_T_true']:.2f}", verdict(d["D1_true_vpin_tracks_informed_trading"]["holds"])),
        ("D2", "paper's VPIN: false alarms from volatility", f"{d['D2_false_alarms_from_volatility']['paper']['M2_V']:+.3f} ± {d['D2_false_alarms_from_volatility']['paper']['mc_se']:.3f}", verdict(d["D2_false_alarms_from_volatility"]["paper"]["confounds_volatility"])),
        ("D3", "paper's predictive test fooled by volatility", f"{d['D3_predictive_test_uninformative']['M4_V_paper']:+.3f} ± {d['D3_predictive_test_uninformative']['mc_se']:.3f}", verdict(d["D3_predictive_test_uninformative"]["holds"])),
        ("D4", "one-day σ: fewer false alarms, same detection", f"{d['D4_local_sigma_is_an_improvement']['M2_V_local']:+.3f}; AUC {d['D4_local_sigma_is_an_improvement']['AUC_T_local']:.3f}", verdict(d["D4_local_sigma_is_an_improvement"]["holds"])),
    ], columns=["Rule", "Pre-registered statement", "Result", "Verdict"])
    table(s, dec, (0.64, 4.25, 6.4, 1.9), widths=[0.55, 2.95, 1.6, 1.3], size=11,
          fills={(i, 3): (GREEN if v == "holds" else MUTED) for i, v in enumerate(dec["Verdict"])})
    text(s, (7.35, 2.3, 5.75, 1.3), [
        ("Tracking of the true informed share, world V", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        (f"paper's VPIN **{sim_get('V', 'paper', 'M1_tracking')['mean']:.2f}** · true labels **{sim_get('V', 'true', 'M1_tracking')['mean']:.2f}** · "
         f"one-day σ (fix) **{sim_get('V', 'local', 'M1_tracking')['mean']:.2f}**", {"size": 13}),
        ("When volatility changes, the paper's VPIN stops measuring informed trading.", {"bold": True, "color": NAVY, "size": 13}),
    ], size=13, space=4)
    picture(s, EXTD / "simulation" / "example_V.png", (7.35, 3.7, 5.75, 2.85))
    text(s, (7.35, 6.55, 5.75, 0.6), [("World V: the paper's VPIN (blue) stays high in volatile blocks while the true informed share (dashed) falls.",
                                       {"bullet": False, "size": 11, "color": MUTED})])

    s = slide_with_title(prs, "Backup: the known-answer test, every metric", (
        "Backup for Extension 3. Bars are means over the replications, error bars ± 1.96 Monte Carlo standard errors. "
        "Left: D2, false alarms from volatility in world V (alarm rate in high minus low volatility blocks). "
        "Middle: detection of toxic episodes in world T (AUC, 0.5 = chance). Right: D3, the paper's predictive "
        "statistic where informed trading never changes (world V). Source: results/extensions/simulation/."))
    picture(s, EXTD / "simulation" / "metrics.png", (0.4, 2.3, 12.5, 4.1))
    text(s, (0.64, 6.45, 12.0, 0.7), [
        ("Blue: the paper's method (BVC, whole-sample σ); green: true labels; orange: BVC with one-day σ (our fix). Error bars: ± 1.96 Monte Carlo standard errors. "
         "Left: false alarms from volatility (world V). Middle: detection of toxic episodes (world T, AUC). Right: the paper's predictive test where informed trading never changes (world V).",
         {"bullet": False, "size": 12, "color": MUTED}),
    ])

    ls = pd.DataFrame(k["local_sigma"]["predictive"])
    ls = ls[((ls["market"] == "BTC") & (ls["sample_length"] == 50)) | (ls["market"] != "BTC")]
    tr = k["local_sigma"]["tracking"]
    lregs = {(r["market"], r["choice"], r["signal"]): r for r in k["local_sigma"]["regressions"]}
    s = slide_with_title(prs, "Extension 4: the fix on real data", (
        "Upgrade, ~1 min. Pre-registered rule D5, run because D4 held. Bulk classification with sigma from the "
        "previous day only, in the same real-time buckets. On BTC, where the truth is known, it tracks "
        "true-label VPIN better. And once the volatility bias is gone, most of VPIN's correlation with future "
        "volatility disappears: the paper's predictive power came from the bias. A small signal beyond "
        "volatility remains on IVE, none on BTC. Source: results/extensions/local_sigma/."))
    df = pd.DataFrame([(r["market"], r["signal"], f"{r['corr']:.3f} ± {r['corr_se']:.3f}", f"{r['lift']:.2f} ± {r['lift_se']:.2f}")
                       for r in ls.to_dict(orient="records")],
                      columns=["Market (real-time, 50 buckets/day)", "Signal", "Corr with next |return|", "Lift"])
    table(s, df, (0.64, 2.4, 7.9, 3.6), widths=[2.3, 2.9, 1.6, 1.1], size=11,
          fills={(i, 1): PAPER_FILL for i, v in enumerate(df["Signal"]) if "fix" in v})
    text(s, (8.8, 2.4, 4.3, 4.7), [
        ("Closer to the truth (BTC)", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        (f"corr with true-label VPIN: fix **{tr['BTC_50_50']['corr_local_true']['value']:.2f}** vs standard {tr['BTC_50_50']['corr_standard_true']['value']:.2f} (+{tr['BTC_50_50']['difference']['value']:.2f} ± {tr['BTC_50_50']['difference']['se']:.2f})", {"size": 13}),
        ("Less volatility in disguise", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        ("its correlation with the next move collapses: the paper's predictive power came from the bias", {"size": 13}),
        ("What remains beyond volatility", {"bullet": False, "bold": True, "color": NAVY, "size": 14}),
        (f"IVE: t = {lregs[('IVE 2011-26', '(50, 250)', 'vpin_local')]['t_vpin_hac']:.1f}, ΔR² = {lregs[('IVE 2011-26', '(50, 250)', 'vpin_local')]['delta_r2']:.4f}; BTC: negative (t = {lregs[('BTC', '(50, 50)', 'vpin_local')]['t_vpin_hac']:.1f})", {"size": 13}),
    ], size=13, space=4)

    inf = k["inference"]
    s = slide_with_title(prs, "What our work adds to the paper", (
        "~1 min. Be explicit about what is new and what confirms others. The ground-truth and volatility "
        "critiques confirm Andersen and Bondarenko (2014, 2015; the latter uses perfect trade classification on E-mini) and "
        "Chakrabarty, Pascual and Shkilko (2015, bulk vs trade-by-trade classification), on new data. The "
        "known-answer simulation that closes the paper's own validation gap, and the one-day-sigma fix tested "
        "against ground truth, are our additions, as far as we know. "
        "Right column, the inference behind points 2 and 4. The placebo keeps each one-minute imbalance's size and draws its direction at random. "
        "If VPIN's predictive power came from informed traders on one side, the placebo would lose it; it keeps "
        "~100%. On IVE 2011-26 the real VPIN is detectably better by 0.002 — still 97% kept. Ledger: a claim "
        "counts as supported only if significant and on the claimed side. Sources: "
        "results/extensions/inference/, results/report/ledger.csv, docs/preregistration.md."))
    text(s, (0.64, 2.35, 7.3, 4.75), [
        "**1. Closes the paper's validation gap.** Its Monte Carlo never runs bulk classification. Our known-answer simulation of its own model shows that VPIN, as the paper computes it, stops measuring informed trading when volatility changes.",
        "**2. Locates where VPIN's predictive power comes from.** With true labels VPIN does not predict volatility (BTC); with shuffled directions it predicts as well as the real VPIN (IVE, BTC). It is the size of price moves, not toxicity.",
        "**3. A fix that works where it can be checked.** Measuring price changes against the previous day's volatility makes VPIN track true toxicity better on BTC, and removes the volatility artefact.",
        f"**4. An honest evaluation.** Real-time, out of sample 2011–2026, all {n_windows} two-year windows, pre-registration, ± on every metric, and a ledger with multiple-testing control. The paper's predictive numbers do not appear anywhere.",
        ("Confirms on new data: Andersen & Bondarenko (2014, 2015); Chakrabarty, Pascual & Shkilko (2015).", {"bullet": False, "size": 11, "color": MUTED}),
    ], size=13, space=7)
    plc = pd.DataFrame([(sname.replace(", real-time", ""), f"{v['real_corr']:.3f}", f"{v['placebo_corr_mean']:.3f} ± {v['placebo_corr_sd']:.3f}",
                         f"{v['placebo_share_of_real_corr']:.0%}") for sname, v in inf["placebo"].items()],
                       columns=["Sample", "Corr, real VPIN", "Corr, direction shuffled", "Kept"])
    text(s, (8.2, 2.3, 4.9, 0.4), [("Placebo: direction of every imbalance shuffled", {"bullet": False, "bold": True, "color": NAVY, "size": 13})])
    table(s, plc, (8.2, 2.7, 4.9, 1.3), widths=[1.75, 0.85, 1.6, 0.7], size=10)
    led = inf["ledger"]
    flips = sum(v["sign_flips"] for v in inf["loyo"].values())
    text(s, (8.2, 4.3, 4.9, 2.8), [
        "**The direction of trading carries almost none of VPIN's predictive power:** the size of price moves does.",
        f"**Leave one year out:** {flips} sign flips across {len(inf['loyo'])} signal–sample pairs.",
        f"**Power:** the reproduction detects any correlation ≥ {inf['power']['mde_80pct_power']:.2f}; the paper's 0.40 would not be missed.",
        f"**Ledger:** {led['tests']} tests behind our claims; supported after Benjamini–Hochberg **{led['supported_bh']}**, after Bonferroni "
        f"**{led['supported_bonferroni']}**; significant but on the wrong side **{led['significant_wrong_side']}** (reported as not supported).",
        ("New tests pre-registered before running; every later change logged.", {"size": 11, "color": MUTED}),
    ], size=12, space=4)

    # Final slide, then the backup slides after it
    prs.slides.add_slide(layout(prs, "Final_1"))
    reorder(prs, MAIN_ORDER, BACKUP_ORDER)
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
