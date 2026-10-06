#!/bin/bash
cd /Users/stubbs/Projects/canvas/canvas_migration
PYTHONPATH=. python scripts/send_announcement.py \
    --manifest manifests/Canvas_Course_Production_Spreadsheet-20260507.csv \
    --title "Notice: Canvas Security Incident" \
    --message-file coms/announcement-20260507.html \
    --account-id 110
