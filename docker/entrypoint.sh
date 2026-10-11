#!/bin/sh
set -e
# Install any club plugins listed in /data/plugins.txt (one pip requirement per line).
if [ -f /data/plugins.txt ]; then
  echo "Installing plugins from /data/plugins.txt"
  pip install --user --quiet -r /data/plugins.txt || echo "WARNING: plugin install failed; continuing without them"
fi
exec "$@"
