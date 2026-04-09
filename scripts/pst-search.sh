#!/usr/bin/env bash
# pst-search.sh — Extract and search emails from a PST file using libpst.
#
# Usage:
#   pst-search.sh list-folders
#   pst-search.sh search <pattern> [--folder <name>] [--from <pattern>] [--to <pattern>] [--after YYYY-MM-DD] [--before YYYY-MM-DD] [--limit N]
#   pst-search.sh extract <pattern> [--folder <name>] [--limit N]
#   pst-search.sh count [--folder <name>]
#   pst-search.sh read-email <temp-dir-index>   (reads a previously extracted .eml)

set -euo pipefail

PST_FILE="/Users/tm07x/Documents/Tvistesak - Mai /Dump/Backups/lasse@reinconsult.no.pst"
EXTRACT_DIR="${TMPDIR:-/tmp}/pst-extract-$$"

cleanup() { rm -rf "$EXTRACT_DIR" 2>/dev/null || true; }
trap cleanup EXIT

cmd="${1:-help}"
shift || true

case "$cmd" in
  list-folders)
    lspst "$PST_FILE" 2>/dev/null | grep "^Folder " | sort -u | sed 's/^Folder "\(.*\)"$/\1/'
    ;;

  count)
    folder_filter=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --folder) folder_filter="$2"; shift 2;;
        *) shift;;
      esac
    done
    if [[ -n "$folder_filter" ]]; then
      lspst -l "$PST_FILE" 2>/dev/null | awk -v folder="$folder_filter" '
        /^Folder / { current=substr($0, index($0,"\"")+1); current=substr(current,1,length(current)-1) }
        /^Email/ && current==folder { count++ }
        END { print count+0 }
      '
    else
      lspst "$PST_FILE" 2>/dev/null | grep -c "^Email" || echo "0"
    fi
    ;;

  search)
    pattern="${1:-}"
    shift || true
    folder_filter=""
    from_filter=""
    to_filter=""
    after_filter=""
    before_filter=""
    limit=50

    while [[ $# -gt 0 ]]; do
      case "$1" in
        --folder) folder_filter="$2"; shift 2;;
        --from) from_filter="$2"; shift 2;;
        --to) to_filter="$2"; shift 2;;
        --after) after_filter="$2"; shift 2;;
        --before) before_filter="$2"; shift 2;;
        --limit) limit="$2"; shift 2;;
        *) shift;;
      esac
    done

    lspst -l "$PST_FILE" 2>/dev/null | awk -v pat="$pattern" -v folder="$folder_filter" \
      -v from_f="$from_filter" -v to_f="$to_filter" \
      -v after="$after_filter" -v before="$before_filter" \
      -v lim="$limit" '
    BEGIN { IGNORECASE=1; count=0 }
    /^Folder / {
      current_folder=substr($0, index($0,"\"")+1)
      current_folder=substr(current_folder,1,length(current_folder)-1)
    }
    /^Email/ {
      if (folder != "" && current_folder != folder) next

      line=$0
      # Extract date
      date_str=""
      if (match(line, /Date: [0-9]{4}-[0-9]{2}-[0-9]{2}/)) {
        date_str=substr(line, RSTART+6, 10)
      }
      if (after != "" && date_str < after) next
      if (before != "" && date_str > before) next

      # Extract from
      from_val=""
      if (match(line, /From: [^\t]*/)) {
        from_val=substr(line, RSTART+6, RLENGTH-6)
      }
      if (from_f != "" && !index(tolower(from_val), tolower(from_f))) next

      # Extract to
      to_val=""
      if (match(line, /To: [^\t]*/)) {
        to_val=substr(line, RSTART+4, RLENGTH-4)
      }
      if (to_f != "" && !index(tolower(to_val), tolower(to_f))) next

      # Extract subject
      subj=""
      if (match(line, /Subject: .*/)) {
        subj=substr(line, RSTART+9)
      }

      # Match pattern against subject, from, to, folder
      searchable=tolower(subj " " from_val " " to_val " " current_folder)
      if (pat != "" && !index(searchable, tolower(pat))) next

      count++
      if (count <= lim) {
        printf "[%s] %s | From: %s | To: %s | Subject: %s\n", current_folder, date_str, from_val, to_val, subj
      }
    }
    END { printf "\n--- %d results", count; if (count > lim) printf " (showing %d)", lim; printf " ---\n" }
    '
    ;;

  extract)
    # Extract full email bodies matching a pattern
    pattern="${1:-}"
    shift || true
    folder_filter=""
    limit=5

    while [[ $# -gt 0 ]]; do
      case "$1" in
        --folder) folder_filter="$2"; shift 2;;
        --limit) limit="$2"; shift 2;;
        *) shift;;
      esac
    done

    mkdir -p "$EXTRACT_DIR"
    # Extract all emails as separate .eml files
    readpst -e -8 -q -o "$EXTRACT_DIR" "$PST_FILE" 2>/dev/null

    count=0
    find "$EXTRACT_DIR" -type f -name "*.eml" | while IFS= read -r eml; do
      if [[ -n "$folder_filter" ]]; then
        rel="${eml#$EXTRACT_DIR/}"
        folder_part="${rel%%/*}"
        if [[ "$folder_part" != "$folder_filter" ]]; then
          continue
        fi
      fi

      if [[ -n "$pattern" ]]; then
        if ! grep -qil "$pattern" "$eml" 2>/dev/null; then
          continue
        fi
      fi

      count=$((count + 1))
      if [[ $count -le $limit ]]; then
        echo "========== MATCH $count =========="
        echo "File: $eml"
        # Print headers and first 200 lines of body
        head -200 "$eml"
        echo ""
        echo "========== END MATCH $count =========="
        echo ""
      fi
    done
    echo "--- $count total matches (showed up to $limit) ---"
    ;;

  help|*)
    cat <<'USAGE'
pst-search.sh — Search emails in the PST archive.

Commands:
  list-folders                          List all folders
  count [--folder NAME]                 Count emails (optionally in a folder)
  search PATTERN [OPTIONS]              Search email metadata (subject/from/to)
    --folder NAME                       Restrict to folder
    --from PATTERN                      Filter by sender
    --to PATTERN                        Filter by recipient
    --after YYYY-MM-DD                  Emails after date
    --before YYYY-MM-DD                 Emails before date
    --limit N                           Max results (default 50)
  extract PATTERN [OPTIONS]             Extract full email bodies matching pattern
    --folder NAME                       Restrict to folder
    --limit N                           Max emails to show (default 5)
USAGE
    ;;
esac
