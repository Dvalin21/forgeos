#!/bin/bash
# Test that CSS file exists and has required design tokens
CSS_FILE="web/desktop/css/forgeos.css"

if [ ! -f "$CSS_FILE" ]; then
  echo "FAIL: CSS file not found at $CSS_FILE"
  exit 1
fi

# Check for required color tokens (use -- to end options)
for token in "--bg-void" "--bg-base" "--accent-primary" "--accent-secondary" "--text-primary"; do
  if ! grep -q -e "$token" "$CSS_FILE"; then
    echo "FAIL: Missing required token: $token"
    exit 1
  fi
done

echo "PASS: All required design tokens found"
exit 0
