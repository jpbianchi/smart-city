import reflex as rx

config = rx.Config(
    app_name="citypulse",
    show_built_with_reflex=False,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="light", accent_color="blue"),
        ),
    ],
)
