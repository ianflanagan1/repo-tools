#!/bin/sh
# Checks repo-tools is set up and says how to put its commands on your PATH.
# Run with `devbox run setup`, which first runs `uv sync` to build .venv.
#
# Each tool's commands are console scripts that uv writes into .venv/bin, pointing at the
# Python devbox pins. They run without starting devbox, which is slower and prints its own
# error line whenever a command fails; cli-kit puts devbox's packages, such as gh, on the PATH.

set -eu

here=$(cd "$(dirname "$0")" && pwd -P)
bin=$here/.venv/bin
commands="github packagist repo-list repo-fix"
for command in $commands; do
    if [ ! -x "$bin/$command" ]; then
        echo "✘ $bin/$command was not created. Run this with: devbox run setup" >&2
        exit 1
    fi
done

if [ ! -f "$here/config.toml" ]; then
    cp "$here/config.example.toml" "$here/config.toml"
    echo "✔ Created config.toml from config.example.toml. Edit it for your settings; git ignores it."
fi

echo "✔ repo-tools is set up. To run its commands from anywhere, link them onto your PATH:"
echo
for command in $commands; do
    echo "ln -sf $bin/$command ~/.local/bin/$command"
done
