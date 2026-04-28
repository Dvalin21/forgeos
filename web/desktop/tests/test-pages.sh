#!/bin/bash
# Test that all required pages exist

PAGES=(
  "filestation.html"
  "docker.html"
  "settings/index.html"
  "settings/storage.html"
  "settings/network.html"
  "settings/backup.html"
  "settings/system.html"
)

PASS=0
FAIL=0

for page in "${PAGES[@]}"; do
  if [ -f "web/desktop/$page" ]; then
    echo "PASS: $page exists"
    ((PASS++))
  else
    echo "FAIL: $page not found"
    ((FAIL++))
  fi
done

echo ""
echo "Results: $PASS passed, $FAIL failed"
exit $FAIL