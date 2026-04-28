#!/bin/bash
# Syntax check for all widget files

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPONENTS_DIR="$SCRIPT_DIR/../components"

echo "Checking JavaScript syntax for all widgets..."

for file in widget-storage.js widget-network.js widget-alerts.js forge-widget.js widget-system.js; do
  if [ -f "$COMPONENTS_DIR/$file" ]; then
    # Use node if available, otherwise just check file exists and has content
    if command -v node &> /dev/null; then
      node --check "$COMPONENTS_DIR/$file" 2>&1 && echo "PASS: $file has valid syntax" || echo "FAIL: $file has syntax errors"
    else
      # Basic check - file exists and is not empty
      if [ -s "$COMPONENTS_DIR/$file" ]; then
        echo "PASS: $file exists and is not empty"
      else
        echo "FAIL: $file is empty or missing"
      fi
    fi
  else
    echo "FAIL: $file not found"
  fi
done
