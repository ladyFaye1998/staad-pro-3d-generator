"""Avoid broken third-party pytest plugins in some global installs."""

import os

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
