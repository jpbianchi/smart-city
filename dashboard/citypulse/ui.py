"""Shared design tokens and layout primitives for every CityPulse page."""
from __future__ import annotations

import reflex as rx

PAGE_BG = "#0a1729"
PAGE_GRADIENT = ("radial-gradient(1100px 520px at 15% -8%, rgba(42,120,214,0.35) 0%, transparent 65%), "
                 "radial-gradient(900px 480px at 95% 10%, rgba(27,175,122,0.16) 0%, transparent 60%), "
                 "linear-gradient(180deg, #0f2443 0%, #0a1729 70%)")
NAVY = "#0d366b"
NAV_GRADIENT = "linear-gradient(90deg, #0d366b 0%, #1c5cab 60%, #256abf 100%)"
CARD_BG = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
HAIRLINE = "#e1e0d9"
BORDER = "1px solid rgba(11,11,11,0.10)"
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
SUCCESS_TEXT = "#006300"
BLUE = "#2a78d6"
BLUE_DARK = "#1c5cab"
RED = "#d03b3b"

# Section tones, drawn from the validated categorical palette the charts use:
# (accent, light tint for backgrounds, deep shade for text on the tint).
TONES = {
    "blue":    ("#2a78d6", "#eaf2fc", "#0d366b"),
    "aqua":    ("#1baf7a", "#e3f5ee", "#0b6e4c"),
    "violet":  ("#4a3aa7", "#eceaf8", "#2f2580"),
    "orange":  ("#eb6834", "#fdece4", "#9a3d14"),
    "magenta": ("#e87ba4", "#fcebf2", "#9c2f5a"),
}

NAV = [
    ("Doc", "/doc"),
    ("Properties", "/"),
    ("Tokens", "/tokens"),
    ("Data sources", "/sources"),
    ("Ontology", "/ontology"),
    ("Appraise", "/appraise"),
]


def kpi_tile(label: str, value, sub=None, accent=None, tone: str = "blue") -> rx.Component:
    main, tint, deep = TONES[tone]
    children = [
        rx.text(label, size="1", color=deep, weight="medium"),
        rx.heading(value, size="7", color=INK),
    ]
    if sub is not None:
        dot = (
            rx.box(width="8px", height="8px", border_radius="50%", background_color=accent)
            if accent is not None
            else rx.fragment()
        )
        children.append(rx.hstack(dot, rx.text(sub, size="1", color=INK_2), align="center", spacing="1"))
    return rx.box(
        rx.vstack(*children, spacing="1", align="start"),
        background=f"linear-gradient(135deg, {tint} 0%, {CARD_BG} 80%)",
        border=f"1px solid {main}33", border_left=f"4px solid {main}", border_radius="10px",
        padding="14px 16px", flex="1", min_width="160px",
    )


def card(*children, **kwargs) -> rx.Component:
    style = {"background_color": CARD_BG, "border": BORDER, "border_radius": "10px", "padding": "16px"}
    return rx.box(*children, **{**style, **kwargs})


def panel(*children, title: str | None = None, subtitle=None, tone: str = "blue", **kwargs) -> rx.Component:
    """A main page section: rounded box with a tinted, accent-marked heading strip."""
    main, tint, deep = TONES[tone]
    body_style = {"padding": kwargs.pop("padding", "18px")}
    outer = {"border": f"1px solid {main}40", "border_radius": "16px", "background_color": CARD_BG,
             "width": "100%",
             "box_shadow": "0 1px 2px rgba(0,0,0,0.30), 0 10px 28px rgba(0,0,0,0.35)"}
    if title is None:
        outer["border_top"] = f"4px solid {main}"
        return rx.box(rx.box(*children, **body_style), **{**outer, **kwargs})
    head = rx.hstack(
        rx.box(width="4px", height="18px", border_radius="2px", background_color=main, flex_shrink="0"),
        rx.text(title, size="3", weight="bold", color=deep),
        rx.text(subtitle, size="1", color=INK_2) if subtitle is not None else rx.fragment(),
        align="center", spacing="3", wrap="wrap",
        background=f"linear-gradient(90deg, {tint} 0%, {CARD_BG} 90%)",
        border_bottom=f"1px solid {main}33", padding="12px 18px", width="100%",
        border_radius="15px 15px 0 0",
    )
    return rx.box(head, rx.box(*children, **body_style), **{**outer, **kwargs})


def _nav_link(label: str, href: str) -> rx.Component:
    active = rx.State.router.url.path == href
    return rx.link(
        label, href=href, size="2", weight="medium", underline="none",
        color=rx.cond(active, NAVY, "rgba(255,255,255,0.88)"),
        background_color=rx.cond(active, "white", "transparent"),
        padding="5px 12px", border_radius="999px",
        _hover={"background_color": rx.cond(active, "white", "rgba(255,255,255,0.14)"), "color": rx.cond(active, NAVY, "white")},
    )


def navbar(refresh=None, subtitle: str = "Paris properties tokenization with smart contracts based on live smart city data") -> rx.Component:
    items = [
        rx.center(rx.icon("building-2", size=18, color="white"), width="32px", height="32px",
                  border_radius="9px", background="linear-gradient(135deg, #1baf7a, #2a78d6)",
                  box_shadow="0 0 0 1px rgba(255,255,255,0.25)"),
        rx.heading("CityPulse", size="5", color="white"),
        rx.text(subtitle, size="2", color="rgba(255,255,255,0.72)"),
        rx.spacer(),
        *[_nav_link(label, href) for label, href in NAV],
    ]
    if refresh is not None:
        items.append(rx.button(
            rx.icon("refresh-cw", size=14), "Refresh", on_click=refresh, size="1", variant="ghost",
            color="white", border="1px solid rgba(255,255,255,0.35)",
            _hover={"background_color": "rgba(255,255,255,0.14)"},
        ))
    return rx.box(
        rx.hstack(*items, align="center", spacing="3", wrap="wrap",
                  max_width="1280px", margin="0 auto", padding="12px 20px"),
        background=NAV_GRADIENT, box_shadow="0 2px 14px rgba(0,0,0,0.45)",
        border_bottom="1px solid rgba(255,255,255,0.10)",
        width="100vw", margin_left="calc(50% - 50vw)", margin_bottom="8px",
    )


def page(*children, max_width: str = "1280px") -> rx.Component:
    return rx.box(
        rx.vstack(
            *children,
            spacing="3", width="100%", max_width=max_width, margin="0 auto", padding="0 20px 48px",
        ),
        background=PAGE_GRADIENT, background_attachment="fixed", min_height="100vh",
    )
