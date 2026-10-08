"""Sphinx configuration."""

from xpilatus import __version__

project = "xpilatus"
author = "Brookhaven National Lab"
copyright = "2026, Brookhaven National Lab"
version = release = __version__
extensions = ["sphinx.ext.autodoc", "sphinx.ext.viewcode", "sphinx.ext.githubpages"]
html_theme = "sphinx_rtd_theme"
master_doc = "index"
