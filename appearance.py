"""Shared color, typography and widget styles for the desktop interface."""

import tkinter.font as tkfont
from tkinter import ttk

BACKGROUND = "#eef3f8"
SURFACE = "#ffffff"
INK = "#152136"
MUTED = "#52647b"
BORDER = "#d5dfe9"
NAVY = "#111b2e"
NAVY_MUTED = "#b9cadb"
MINT = "#6ae6cf"
TEAL = "#075c50"
SELECTED = "#d7f5ee"
WARNING = "#854809"


def apply_theme(window):
    style = ttk.Style(window)
    style.theme_create("carteira", parent="clam")
    style.theme_use("carteira")
    window.configure(background=BACKGROUND)

    available = set(tkfont.families(window))
    system_font = tkfont.nametofont("TkDefaultFont", root=window)
    family = next(
        (name for name in ("Inter", "Noto Sans", "DejaVu Sans") if name in available),
        system_font.actual("family"),
    )
    system_font.configure(family=family, size=10)
    heading = (family, 14, "bold")
    strong = (family, 10, "bold")

    style.configure(".", background=BACKGROUND, foreground=INK, font=system_font)
    style.configure("TFrame", background=BACKGROUND)
    style.configure("Card.TFrame", background=SURFACE, bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Dark.TFrame", background=NAVY)
    style.configure("TLabelframe", background=BACKGROUND)
    style.configure("TLabel", background=BACKGROUND, foreground=INK)
    style.configure("Heading.TLabel", font=heading)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Warning.TLabel", foreground=WARNING)
    style.configure("Surface.TLabel", background=SURFACE)
    style.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("SurfaceHeading.TLabel", background=SURFACE, font=heading)
    style.configure("Dark.TLabel", background=NAVY, foreground=NAVY_MUTED)
    style.configure("Brand.TLabel", background=NAVY, foreground=SURFACE, font=(family, 17, "bold"))
    style.configure("Network.TLabel", background="#1f334b", foreground="#d5e7f6", padding=(10, 6), font=strong)
    style.configure("Balance.TLabel", background=NAVY, foreground=SURFACE, font=(family, 29, "bold"))

    style.configure(
        "TButton", background=SURFACE, foreground=INK, bordercolor=BORDER, focuscolor=TEAL,
        lightcolor=SURFACE, darkcolor=SURFACE, padding=(13, 8), font=strong, anchor="center",
    )
    style.map(
        "TButton", background=[("disabled", "#edf1f5"), ("pressed", "#dce8f3"), ("active", "#e8eff7")],
        foreground=[("disabled", "#627488")], bordercolor=[("focus", TEAL)],
    )
    style.configure(
        "Primary.TButton", background=MINT, foreground=NAVY, bordercolor=MINT,
        lightcolor=MINT, darkcolor=MINT,
    )
    style.map(
        "Primary.TButton",
        background=[("disabled", "#d9ebe8"), ("pressed", "#36c5ac"), ("active", "#8aefdb")],
        foreground=[("disabled", "#536c66")], bordercolor=[("focus", TEAL)],
    )
    style.configure(
        "Dark.TButton", background="#23354c", foreground=SURFACE, bordercolor="#38516d",
        lightcolor="#23354c", darkcolor="#23354c", focuscolor=MINT,
    )
    style.map("Dark.TButton", background=[("pressed", "#334962"), ("active", "#2c425c")],
              bordercolor=[("focus", MINT)])
    style.configure(
        "TEntry", fieldbackground=SURFACE, foreground=INK, insertcolor=INK,
        selectbackground=SELECTED, selectforeground=INK, padding=(9, 7), bordercolor=BORDER,
    )
    style.map("TEntry", fieldbackground=[("readonly", "#f2f6fa")], bordercolor=[("focus", TEAL)])

    style.configure("TNotebook", background=BACKGROUND, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background="#e2eaf2", foreground=MUTED, padding=(16, 9), font=strong)
    style.map(
        "TNotebook.Tab", background=[("selected", SURFACE), ("active", "#d7e4ef")],
        foreground=[("selected", TEAL)],
    )
    style.configure(
        "Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=INK,
        rowheight=31, bordercolor=BORDER,
    )
    style.map("Treeview", background=[("selected", SELECTED)], foreground=[("selected", INK)])
    style.configure(
        "Treeview.Heading", background="#e7eff6", foreground=INK, font=strong,
        bordercolor=BORDER, padding=(8, 8),
    )
    return style


def stripe_table(table):
    table.tag_configure("alternate", background="#f3f7fb")
