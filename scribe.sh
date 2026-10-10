#!/usr/bin/env bash
cd "$(dirname "$(readlink -f "$0")")" && exec .venv/bin/python -m scribe "$@"
