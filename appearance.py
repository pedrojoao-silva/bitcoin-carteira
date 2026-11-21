"""Shared colors and ttk styles for the desktop wallet."""

import tkinter.font as tkfont
from tkinter import ttk

BACKGROUND = "#101820"
SURFACE = "#18242e"
SIDEBAR = "#0c141c"
HERO = "#20352f"
INK = "#f1f5f4"
MUTED = "#a3b7c2"
BORDER = "#344754"
MINT = "#74e4bc"
NAV_ACTIVE = "#233b38"
SELECTED = "#31504b"
WARNING = "#f3c381"
ERROR = "#ffaaa6"


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
    strong = (family, 10, "bold")
    heading = (family, 15, "bold")

    style.configure(".", background=BACKGROUND, foreground=INK, font=system_font)
    style.configure("TFrame", background=BACKGROUND)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Sidebar.TFrame", background=SIDEBAR)
    style.configure("Hero.TFrame", background=HERO)
    style.configure("Card.TFrame", background=SURFACE, bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("TLabel", background=BACKGROUND, foreground=INK)
    style.configure("Title.TLabel", font=(family, 23, "bold"))
    style.configure("Heading.TLabel", font=heading)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Warning.TLabel", foreground=WARNING)
    style.configure("Surface.TLabel", background=SURFACE)
    style.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("SurfaceHeading.TLabel", background=SURFACE, font=heading)
    style.configure("Sidebar.TLabel", background=SIDEBAR)
    style.configure("Brand.TLabel", background=SIDEBAR, font=(family, 12, "bold"))
    style.configure("Network.TLabel", background=NAV_ACTIVE, foreground=MINT, padding=(9, 5), font=strong)
    style.configure("Hero.TLabel", background=HERO, foreground=MUTED)
    style.configure("Balance.TLabel", background=HERO, font=(family, 36, "bold"))
    style.configure("Unit.TLabel", background=HERO, foreground=MINT, font=(family, 13, "bold"))

    style.configure(
        "TButton", background=SURFACE, foreground=INK, bordercolor=BORDER, focuscolor=MINT,
        lightcolor=SURFACE, darkcolor=SURFACE, padding=(13, 8), font=strong, anchor="center",
    )
    style.map(
        "TButton", background=[("disabled", "#202b34"), ("pressed", "#304550"), ("active", "#263844")],
        foreground=[("disabled", "#889ba7")], bordercolor=[("focus", MINT)],
    )
    style.configure(
        "Primary.TButton", background=MINT, foreground=SIDEBAR, bordercolor=MINT,
        lightcolor=MINT, darkcolor=MINT, focuscolor=SIDEBAR,
    )
    style.map(
        "Primary.TButton",
        background=[("disabled", "#273b39"), ("pressed", "#59c7a3"), ("active", "#95efd1")],
        foreground=[("disabled", MUTED)], bordercolor=[("focus", INK)],
    )
    style.configure(
        "Nav.TButton", background=SIDEBAR, lightcolor=SIDEBAR, darkcolor=SIDEBAR,
        bordercolor=SIDEBAR, foreground=MUTED, anchor="w", padding=(12, 10),
    )
    style.map("Nav.TButton", background=[("active", SURFACE)], bordercolor=[("focus", MINT)])
    style.configure(
        "Current.Nav.TButton", background=NAV_ACTIVE, lightcolor=NAV_ACTIVE, darkcolor=NAV_ACTIVE,
        bordercolor=NAV_ACTIVE, foreground=MINT,
    )
    style.map("Current.Nav.TButton", background=[("active", SELECTED)], bordercolor=[("focus", MINT)])
    style.configure(
        "TEntry", fieldbackground=SIDEBAR, foreground=INK, insertcolor=INK,
        selectbackground=SELECTED, selectforeground=INK, padding=(9, 8), bordercolor=BORDER,
        lightcolor=SIDEBAR, darkcolor=SIDEBAR,
    )
    style.map("TEntry", fieldbackground=[("readonly", SIDEBAR)], bordercolor=[("focus", MINT)])
    style.configure("TScrollbar", background=BORDER, troughcolor=SIDEBAR, bordercolor=SIDEBAR)
    style.configure(
        "Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=INK,
        rowheight=34, bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE,
    )
    style.map("Treeview", background=[("selected", SELECTED)], foreground=[("selected", INK)])
    style.configure(
        "Treeview.Heading", background="#263641", foreground=INK, font=strong,
        bordercolor=BORDER, padding=(8, 9), lightcolor="#263641", darkcolor="#263641",
    )


def style_activity_table(table):
    table.tag_configure("alternate", background="#1d2a34")
    table.tag_configure("confirmed", foreground=MINT)
    table.tag_configure("pending", foreground=WARNING)
    table.tag_configure("failed", foreground=ERROR)
