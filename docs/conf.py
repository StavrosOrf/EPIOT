"""Sphinx configuration for the EPIOT documentation."""

from datetime import date

project = "EPIOT"
author = "DRIVE2X"
copyright = f"{date.today().year}, {author}"
release = "0.1.0"
version = release

extensions = [
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx.ext.autosectionlabel",
]

source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build", "_scripts", "README.md", "Thumbs.db", ".DS_Store"]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "dollarmath",
    "amsmath",
    "attrs_inline",
    "attrs_block",
    "fieldlist",
    "substitution",
    "tasklist",
]
myst_heading_anchors = 3
autosectionlabel_prefix_document = True
suppress_warnings = ["autosectionlabel.*"]

# -- HTML ---------------------------------------------------------------------
html_theme = "furo"
html_title = "EPIOT docs"
html_short_title = "EPIOT"
html_logo = "_static/logo.svg"
html_favicon = "../static/images/favicon.ico"
html_static_path = ["_static"]
templates_path = ["_templates"]
html_css_files = ["custom.css"]
html_last_updated_fmt = "%d %b %Y"
html_copy_source = False
html_baseurl = "https://epiot.readthedocs.io/en/latest/"

# Furo's default sidebar plus the DRIVE2X badge under the brand.
html_sidebars = {
    "**": [
        "sidebar/scroll-start.html",
        "sidebar/brand.html",
        "sidebar/drive2x.html",
        "sidebar/search.html",
        "sidebar/navigation.html",
        "sidebar/ethical-ads.html",
        "sidebar/scroll-end.html",
    ]
}

_brand = "#1f7a3f"
html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "top_of_page_buttons": ["view"],
    "source_view_link": "https://github.com/StavrosOrf/EPIOT/blob/main/docs/{filename}",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/StavrosOrf/EPIOT",
            "html": (
                '<svg stroke="currentColor" fill="currentColor" stroke-width="0" '
                'viewBox="0 0 16 16"><path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 '
                "3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37"
                "-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 "
                "1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-"
                ".89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2"
                ".82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 "
                "1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25."
                '54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 '
                '8c0-4.42-3.58-8-8-8z"></path></svg>'
            ),
            "class": "",
        },
    ],
    "light_css_variables": {
        "color-brand-primary": _brand,
        "color-brand-content": _brand,
        "color-admonition-title--note": _brand,
        "font-stack": "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        "font-stack--monospace": "JetBrains Mono, SFMono-Regular, Menlo, Consolas, monospace",
    },
    "dark_css_variables": {
        "color-brand-primary": "#4cc27a",
        "color-brand-content": "#4cc27a",
    },
}

copybutton_prompt_text = r"\$ |>>> "
copybutton_prompt_is_regexp = True
