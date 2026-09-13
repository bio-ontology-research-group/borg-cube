#!/usr/bin/env bash
# Render selected Beamer PDF pages as PNGs. Dry-run is the default.

set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: frames_to_png.sh DECK.tex|DECK.pdf --frames 1,3-5 --out DIRECTORY [--dpi 150] [--apply]' \
    '' \
    'Render selected Beamer PDF pages to frame-###.png files. A .tex source is' \
    'compiled with latexmk in a temporary directory. A PDF skips compilation.' \
    'Frame numbers are PDF page numbers; Beamer overlays can create extra pages.' \
    '' \
    'The default is a dry run. Add --apply to create files. Existing output files' \
    'are never overwritten. latexmk is required for .tex input; pdftoppm is' \
    'required for all rendering.'
}

fail() {
  printf 'frames-to-png: %s\n' "$1" >&2
  exit 2
}

source_path=''
frames=''
out_dir=''
dpi=150
apply=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --frames)
      [[ $# -ge 2 ]] || fail '--frames needs a comma-separated list such as 1,3-5'
      frames=$2
      shift 2
      ;;
    --out)
      [[ $# -ge 2 ]] || fail '--out needs a destination directory'
      out_dir=$2
      shift 2
      ;;
    --dpi)
      [[ $# -ge 2 ]] || fail '--dpi needs a positive integer'
      dpi=$2
      shift 2
      ;;
    --apply)
      apply=1
      shift
      ;;
    --dry-run)
      apply=0
      shift
      ;;
    --)
      shift
      [[ $# -le 1 ]] || fail 'only one source path is allowed'
      [[ $# -eq 1 ]] && source_path=$1
      break
      ;;
    -*)
      fail "unknown option: $1"
      ;;
    *)
      [[ -z "$source_path" ]] || fail 'only one source path is allowed'
      source_path=$1
      shift
      ;;
  esac
done

[[ -n "$source_path" ]] || fail 'provide a .tex or .pdf source path'
[[ -f "$source_path" ]] || fail "source file does not exist: $source_path"
[[ -n "$frames" ]] || fail 'provide --frames, for example 1,3-5'
[[ -n "$out_dir" ]] || fail 'provide --out DIRECTORY'
[[ "$dpi" =~ ^[1-9][0-9]*$ ]] || fail '--dpi must be a positive integer'

case "${source_path##*.}" in
  tex|TEX)
    source_kind=tex
    ;;
  pdf|PDF)
    source_kind=pdf
    ;;
  *)
    fail 'source must end in .tex or .pdf'
    ;;
esac

declare -a selected=()
add_frame() {
  local candidate=$1
  local previous
  for previous in "${selected[@]}"; do
    [[ "$previous" == "$candidate" ]] && return
  done
  selected+=("$candidate")
}

IFS=',' read -r -a requested <<< "$frames"
for request in "${requested[@]}"; do
  [[ -n "$request" ]] || fail "invalid frame list: $frames"
  if [[ "$request" =~ ^([1-9][0-9]*)-([1-9][0-9]*)$ ]]; then
    start=${BASH_REMATCH[1]}
    end=${BASH_REMATCH[2]}
    (( start <= end )) || fail "invalid descending range: $request"
    current=$start
    while (( current <= end )); do
      add_frame "$current"
      ((current += 1))
    done
  elif [[ "$request" =~ ^[1-9][0-9]*$ ]]; then
    add_frame "$request"
  else
    fail "invalid frame selector: $request"
  fi
done

printf 'frames-to-png: selected PDF page(s): %s; dpi: %s; output: %s\n' \
  "${selected[*]}" "$dpi" "$out_dir"
if (( ! apply )); then
  if [[ "$source_kind" == tex ]]; then
    printf '[dry-run] latexmk -pdf -outdir TEMP %q\n' "$source_path"
  fi
  for frame in "${selected[@]}"; do
    printf '[dry-run] pdftoppm -f %s -l %s -png -singlefile INPUT %q\n' \
      "$frame" "$frame" "$out_dir/frame-$(printf '%03d' "$frame")"
  done
  exit 0
fi

if [[ "$source_kind" == tex ]] && ! command -v latexmk >/dev/null 2>&1; then
  fail 'latexmk is unavailable. Install a LaTeX distribution, or pass an already-built PDF.'
fi
if ! command -v pdftoppm >/dev/null 2>&1; then
  fail 'pdftoppm is unavailable. Install Poppler utilities, then rerun.'
fi

for frame in "${selected[@]}"; do
  destination="$out_dir/frame-$(printf '%03d' "$frame").png"
  [[ ! -e "$destination" ]] || fail "refusing to overwrite existing output: $destination"
done

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/frames-to-png.XXXXXX")
trap 'rm -rf "$work_dir"' EXIT

if [[ "$source_kind" == tex ]]; then
  source_dir=$(cd "$(dirname "$source_path")" && pwd)
  source_base=$(basename "$source_path")
  source_stem=${source_base%.*}
  printf 'frames-to-png: compiling %s\n' "$source_path"
  (
    cd "$source_dir"
    latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir="$work_dir" "$source_base"
  ) || fail 'LaTeX compilation failed. Read the latexmk output and fix the deck before rendering.'
  pdf_path="$work_dir/$source_stem.pdf"
  [[ -f "$pdf_path" ]] || fail 'latexmk finished without the expected PDF output'
else
  pdf_path=$source_path
fi

for frame in "${selected[@]}"; do
  prefix="$work_dir/frame-$(printf '%03d' "$frame")"
  printf 'frames-to-png: rendering PDF page %s\n' "$frame"
  pdftoppm -f "$frame" -l "$frame" -png -singlefile -r "$dpi" "$pdf_path" "$prefix" || \
    fail "pdftoppm could not render PDF page $frame"
  [[ -f "$prefix.png" ]] || fail "pdftoppm did not create PNG for PDF page $frame"
done

mkdir -p "$out_dir"
for frame in "${selected[@]}"; do
  filename="frame-$(printf '%03d' "$frame").png"
  mv "$work_dir/$filename" "$out_dir/$filename"
done
printf 'frames-to-png: wrote %s PNG file(s) to %s\n' "${#selected[@]}" "$out_dir"
