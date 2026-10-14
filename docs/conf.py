"""Sphinx configuration for the EPIOT documentation."""

from datetime import date

project = "EPIOT"
author = "DRIVE2X WP5 — DLR & TU Delft"
copyright = f"{date.today().year}, {author}"
release = "0.1.0"
version = release

extensions = [
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
    "sphinx.ext.autosectionlabel",
]

source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build", "_scripts", "Thumbs.db", ".DS_Store"]

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
html_css_files = ["custom.css"]
html_js_files = ["mermaid-size.js"]
html_last_updated_fmt = "%d %b %Y"
html_copy_source = False

_brand = "#1f7a3f"
html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "top_of_page_buttons": ["view"],
    "source_view_link": "https://gitlab.dlr.de/drive2x/epiot/-/blob/main/docs/{filename}",
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

# -- Mermaid ------------------------------------------------------------------
mermaid_version = "11.4.1"
mermaid_light_theme = "neutral"
mermaid_dark_theme = "dark"
mermaid_init_config = {
    "startOnLoad": False,
    "fontFamily": "Inter, system-ui, sans-serif",
    "flowchart": {"curve": "basis", "htmlLabels": True},
    "sequence": {"mirrorActors": False, "showSequenceNumbers": True},
}

copybutton_prompt_text = r"\$ |>>> "
copybutton_prompt_is_regexp = True
