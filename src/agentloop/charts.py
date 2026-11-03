"""报告用图表（matplotlib → PNG）。HTML 报告内嵌为 base64，Word 报告插入为图片。"""

from __future__ import annotations

import io
import logging
import warnings

import matplotlib
import matplotlib.ticker
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Arial Unicode MS（Mac）与微软雅黑（Windows）同时包含中文和 Sjögren 中的 ö
plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB",
                                   "SimHei", "Noto Sans CJK SC", "Source Han Sans SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="Glyph .* missing from font")


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def progress_chart(rounds: list[dict]) -> bytes | None:
    if not rounds:
        return None
    x = [r["round"] for r in rounds]
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    series = [("n_findings", "表型发现"), ("n_hypotheses", "提出假设"), ("n_passed_review", "通过审稿"),
              ("cumulative_meaningful", "累计有意义结论")]
    for key, label in series:
        ax.plot(x, [r[key] for r in rounds], marker="o", label=label)
    ax.plot(x, [len(r["new_meaningful"]) for r in rounds], marker="s", linestyle="--", label="本轮新增有意义结论")
    ax.set_xlabel("研究轮次")
    ax.set_ylabel("数量")
    ax.set_ylim(bottom=0, top=max(3, max(max(r[k] for k, _ in series) for r in rounds)) * 1.25)
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax.set_xticks(x, [f"第{i}轮" for i in x])
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=3, loc="upper left")
    ax.set_title("各轮进展")
    return _png(fig)


def effects_chart(items: list[dict], title: str) -> bytes | None:
    """items: [{label, estimate, ci_low, ci_high, highlight(bool), measure}]，横轴为对数刻度的 OR/HR。"""
    items = [i for i in items if i.get("estimate")]
    if not items:
        return None
    fig, ax = plt.subplots(figsize=(7.5, 0.45 * len(items) + 1.2))
    for y, it in enumerate(reversed(items)):
        color = "#c0392b" if it.get("highlight") else "#7f8c8d"
        ax.plot([it["ci_low"], it["ci_high"]], [y, y], color=color, linewidth=2)
        ax.plot(it["estimate"], y, "o", color=color)
    ax.axvline(1, color="black", linewidth=0.8, linestyle=":")
    ax.set_xscale("log")
    lo = min(i["ci_low"] for i in items)
    hi = max(i["ci_high"] for i in items)
    ticks = [t for t in (0.1, 0.2, 0.5, 1, 2, 3, 5, 10, 20, 50) if lo / 1.5 <= t <= hi * 1.5]
    ax.set_xticks(ticks, [f"{t:g}" for t in ticks])
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_yticks(range(len(items)), [i["label"] for i in reversed(items)], fontsize=8)
    ax.set_xlabel("效应量（OR 或 HR，对数刻度；1 表示无关联）")
    ax.set_title(title)
    ax.grid(alpha=0.3, axis="x")
    return _png(fig)
