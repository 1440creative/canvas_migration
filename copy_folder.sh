for f in utils/*.py; do
  echo -e "\n### FILE: $f ###"; cat "$f"; done | pbcopy