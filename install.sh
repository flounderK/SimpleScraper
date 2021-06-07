#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

if [ -e "$SCRIPT_DIR/requirements.txt" ];then
	pip install -r "$SCRIPT_DIR/requirements.txt"
fi

install "$SCRIPT_DIR/simplescraper.py" "$HOME/.local/bin"
