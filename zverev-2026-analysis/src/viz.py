"""Sistema de diseño editorial para los gráficos del proyecto (estilo FT / The Economist)."""

from pathlib import Path
import matplotlib.pyplot as plt

PALETTE = {
    "bg": "#FAF9F6",
    "text": "#1F2937",
    "muted": "#6B7280",
    "grid": "#E5E7EB",
    "neutral": "#9CA3AF",
    "bar_muted": "#D1D5DB",
    "zverev": "#15803D",
    "sinner": "#EA580C",
    "alcaraz": "#6D28D9",
    "negative": "#BE123C",
}


def apply_editorial_style() -> None:
    """Configura los rcParams globales de Matplotlib con estética editorial."""
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": [
            "Inter", "Plus Jakarta Sans", "Roboto",
            "Helvetica Neue", "Segoe UI", "Arial", "DejaVu Sans",
        ],
        "figure.facecolor": PALETTE["bg"],
        "axes.facecolor": PALETTE["bg"],
        "savefig.facecolor": PALETTE["bg"],
        "text.color": PALETTE["text"],
        "axes.labelcolor": PALETTE["muted"],
        "xtick.color": PALETTE["muted"],
        "ytick.color": PALETTE["muted"],
        "axes.edgecolor": PALETTE["grid"],
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": PALETTE["grid"],
        "grid.linestyle": "-",
        "grid.linewidth": 0.8,
        "grid.alpha": 0.9,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "xtick.major.pad": 7,
        "ytick.major.pad": 7,
        "axes.labelpad": 9,
        "font.size": 10,
        "axes.labelsize": 9.5,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9.5,
        "legend.frameon": False,
        "figure.dpi": 150,
        "savefig.dpi": 300,
    })


def add_editorial_chrome(
    fig: plt.Figure,
    title: str,
    subtitle: str,
    source: str = "Fuente: TennisMyLife (2018–2026) · Análisis propio en Python",
    accent_color: str = PALETTE["zverev"],
    left: float = 0.09,
    right: float = 0.95,
    top_pad_in: float = 1.05,
    bottom_pad_in: float = 0.65,
    hspace: float | None = None,
) -> None:
    """Añade barra de acento, titular, subtítulo y fuente con espaciado consistente en pulgadas."""
    fig_h = fig.get_figheight()
    top = 1.0 - (top_pad_in / fig_h)
    bottom = bottom_pad_in / fig_h

    adjust_kwargs = dict(left=left, right=right, top=top, bottom=bottom)
    if hspace is not None:
        adjust_kwargs["hspace"] = hspace
    fig.subplots_adjust(**adjust_kwargs)

    bar_y = 1.0 - (0.18 / fig_h)
    title_y = 1.0 - (0.34 / fig_h)
    subtitle_y = 1.0 - (0.68 / fig_h)
    source_y = 0.16 / fig_h

    fig.add_artist(
        plt.Line2D(
            [0.04, 0.11], [bar_y, bar_y],
            transform=fig.transFigure, color=accent_color, lw=3.5, solid_capstyle="butt",
        )
    )
    fig.text(0.04, title_y, title, fontsize=13.5, fontweight="bold", color=PALETTE["text"], va="top", ha="left")
    fig.text(0.04, subtitle_y, subtitle, fontsize=9.8, color=PALETTE["muted"], va="top", ha="left")
    fig.text(0.04, source_y, source, fontsize=8.2, color=PALETTE["muted"], va="bottom", ha="left")


def save_figure(fig: plt.Figure, filename_stem: str, out_dir: str | Path = "../figures") -> None:
    """Guarda la figura en PNG (300 DPI) y SVG vectorial."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(out_path / f"{filename_stem}.{ext}", bbox_inches="tight", pad_inches=0.22)