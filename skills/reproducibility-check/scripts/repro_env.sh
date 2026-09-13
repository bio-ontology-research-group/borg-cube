#!/usr/bin/env bash
# Build a clean environment for a re-execution attempt and record what it took.
#
# Order of preference, highest fidelity first:
#   1. container: Dockerfile, Containerfile, *.def or *.sif (docker, podman,
#      apptainer or singularity, whichever is present)
#   2. locked virtual environment: uv.lock, poetry.lock, Pipfile.lock,
#      conda-lock.yml, environment.yml, requirements.lock, requirements.txt
#      with every line pinned
#   3. unpinned dependency list: requirements.txt or pyproject.toml without
#      pins, recorded as an improvisation
#
# It never falls back to the environment already on this machine. When no
# usable recipe is found, or the container runtime is missing, it says so,
# writes the log and exits non-zero.
#
# Everything is written under --work; the repository under test is never
# modified and is only ever read.
#
# Usage:
#   repro_env.sh --repo <clone> --work <dir> [--prefer container|venv]
#                [--python <exe>] [--build] [--json] [--help]
#
# Without --build nothing is executed: the plan and the findings are printed
# (a dry run). With --build the chosen build command runs inside --work.

set -u

PROG="repro-env"
REPO=""
WORK=""
PREFER="auto"
PYTHON="python3"
BUILD=0
JSON=0

CHECKS_VERSION="1"

usage() {
	cat <<'EOF'
repro_env.sh - build a clean environment for a re-execution attempt

Usage:
  repro_env.sh --repo <path> --work <path> [options]

Options:
  --repo <path>      repository under test; read-only, never modified (required)
  --work <path>      working directory for the attempt; everything is written
                     here (required)
  --prefer <mode>    auto (default), container, or venv
  --python <exe>     interpreter for the virtual environment path (default python3)
  --build            actually run the build command (default: plan only)
  --json             print the result as JSON instead of text
  -h, --help         show this message

Exit status:
  0  a recipe was found and, with --build, the build succeeded
  1  no usable recipe, missing runtime, or the build failed
  2  bad arguments

The script refuses to reuse the developer's environment. If the container
runtime is missing it reports that and stops rather than installing packages
into whatever interpreter happens to be on PATH.
EOF
}

log() { printf '%s: %s\n' "$PROG" "$1" >&2; }

# Findings are the improvisations and gaps that make a run less than a clean
# re-execution. Each one is a single line: <kind>\t<detail>.
FINDINGS_FILE=""
add_finding() {
	printf '%s\t%s\n' "$1" "$2" >>"$FINDINGS_FILE"
}

json_escape() {
	# escape backslash, quote and control characters for a JSON string
	printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/	/\\t/g' | tr -d '\r\n'
}

while [ $# -gt 0 ]; do
	case "$1" in
	--repo)
		REPO="${2:-}"
		shift 2 || exit 2
		;;
	--work)
		WORK="${2:-}"
		shift 2 || exit 2
		;;
	--prefer)
		PREFER="${2:-}"
		shift 2 || exit 2
		;;
	--python)
		PYTHON="${2:-}"
		shift 2 || exit 2
		;;
	--build)
		BUILD=1
		shift
		;;
	--json)
		JSON=1
		shift
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		log "unknown argument: $1"
		usage >&2
		exit 2
		;;
	esac
done

if [ -z "$REPO" ] || [ -z "$WORK" ]; then
	log "--repo and --work are required"
	exit 2
fi
if [ ! -d "$REPO" ]; then
	log "--repo is not a directory: $REPO"
	exit 2
fi
case "$PREFER" in
auto | container | venv) ;;
*)
	log "--prefer must be auto, container or venv"
	exit 2
	;;
esac

mkdir -p "$WORK" || exit 2
WORK=$(cd "$WORK" && pwd)
REPO=$(cd "$REPO" && pwd)
FINDINGS_FILE="$WORK/.repro_env_findings"
: >"$FINDINGS_FILE"

LOG="$WORK/repro-env.log"
ENV_JSON="$WORK/repro-env.json"

# ------------------------------------------------------------------ inspect

first_existing() {
	for candidate in "$@"; do
		if [ -f "$REPO/$candidate" ]; then
			printf '%s' "$candidate"
			return 0
		fi
	done
	return 1
}

find_one() {
	# first match of a glob pattern below the repository root, depth 2
	find "$REPO" -maxdepth 2 -name "$1" -type f 2>/dev/null | LC_ALL=C sort | head -n 1
}

COMMIT="unknown"
if [ -d "$REPO/.git" ] && command -v git >/dev/null 2>&1; then
	COMMIT=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || printf 'unknown')
	if [ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]; then
		add_finding "dirty-worktree" "the checkout has uncommitted changes; the commit hash does not describe it"
	fi
else
	add_finding "no-version-control" "no git checkout, so the exact revision under test cannot be recorded"
fi

CONTAINER_RECIPE=""
CONTAINER_KIND=""
if recipe=$(first_existing Dockerfile Containerfile docker/Dockerfile .devcontainer/Dockerfile); then
	CONTAINER_RECIPE="$recipe"
	CONTAINER_KIND="docker"
else
	def=$(find_one '*.def')
	sif=$(find_one '*.sif')
	if [ -n "$def" ]; then
		CONTAINER_RECIPE="${def#"$REPO"/}"
		CONTAINER_KIND="apptainer"
	elif [ -n "$sif" ]; then
		CONTAINER_RECIPE="${sif#"$REPO"/}"
		CONTAINER_KIND="apptainer-image"
	fi
fi

LOCK_FILE=""
for candidate in uv.lock poetry.lock Pipfile.lock conda-lock.yml conda-lock.yaml requirements.lock environment.yml environment.yaml; do
	if [ -f "$REPO/$candidate" ]; then
		LOCK_FILE="$candidate"
		break
	fi
done

REQ_FILE=""
if [ -f "$REPO/requirements.txt" ]; then
	REQ_FILE="requirements.txt"
fi

PINNED="unknown"
if [ -n "$REQ_FILE" ]; then
	unpinned=$(grep -v '^[[:space:]]*#' "$REPO/$REQ_FILE" | grep -v '^[[:space:]]*$' |
		grep -v -- '==' | grep -v '^-' || true)
	if [ -n "$unpinned" ]; then
		PINNED="no"
		count=$(printf '%s\n' "$unpinned" | wc -l | tr -d ' ')
		add_finding "unpinned-dependencies" "$REQ_FILE has $count requirement(s) without a == version pin"
	else
		PINNED="yes"
	fi
fi

if [ -n "$CONTAINER_RECIPE" ] && [ "$CONTAINER_KIND" = "docker" ]; then
	if grep -Eq '^[[:space:]]*FROM[[:space:]]+[^[:space:]]+(:latest)?[[:space:]]*$' "$REPO/$CONTAINER_RECIPE" &&
		! grep -Eq '^[[:space:]]*FROM[[:space:]]+[^[:space:]]+:[^[:space:]]+' "$REPO/$CONTAINER_RECIPE"; then
		add_finding "unpinned-base-image" "$CONTAINER_RECIPE has a FROM without a version tag, so the base image is a moving target"
	fi
fi

# ------------------------------------------------------------------ choose

runtime_for_container() {
	case "$CONTAINER_KIND" in
	docker)
		for rt in docker podman; do
			if command -v "$rt" >/dev/null 2>&1; then
				printf '%s' "$rt"
				return 0
			fi
		done
		;;
	apptainer | apptainer-image)
		for rt in apptainer singularity; do
			if command -v "$rt" >/dev/null 2>&1; then
				printf '%s' "$rt"
				return 0
			fi
		done
		;;
	esac
	return 1
}

STRATEGY="none"
RUNTIME=""
COMMAND=""
SOURCE=""
REASON=""

want_container=1
want_venv=1
[ "$PREFER" = "venv" ] && want_container=0
[ "$PREFER" = "container" ] && want_venv=0

if [ "$want_container" -eq 1 ] && [ -n "$CONTAINER_RECIPE" ]; then
	if RUNTIME=$(runtime_for_container); then
		SOURCE="$CONTAINER_RECIPE"
		case "$CONTAINER_KIND" in
		docker)
			STRATEGY="container"
			COMMAND="$RUNTIME build --no-cache --file $REPO/$CONTAINER_RECIPE --tag repro-check:local $REPO"
			;;
		apptainer)
			STRATEGY="container"
			COMMAND="$RUNTIME build $WORK/repro-check.sif $REPO/$CONTAINER_RECIPE"
			;;
		apptainer-image)
			STRATEGY="container-image"
			COMMAND="$RUNTIME inspect $REPO/$CONTAINER_RECIPE"
			add_finding "image-without-recipe" "$CONTAINER_RECIPE is a built image with no definition file; its contents cannot be audited or rebuilt"
			;;
		esac
	else
		RUNTIME=""
		add_finding "no-container-runtime" "$CONTAINER_RECIPE needs $CONTAINER_KIND; no runtime found on PATH"
		REASON="container recipe $CONTAINER_RECIPE found but no runtime for it is installed"
	fi
fi

if [ "$STRATEGY" = "none" ] && [ "$want_venv" -eq 1 ]; then
	if ! command -v "$PYTHON" >/dev/null 2>&1; then
		add_finding "no-interpreter" "$PYTHON is not on PATH"
	elif [ -n "$LOCK_FILE" ]; then
		STRATEGY="venv-locked"
		SOURCE="$LOCK_FILE"
		case "$LOCK_FILE" in
		uv.lock) COMMAND="uv sync --frozen --project $REPO" ;;
		poetry.lock) COMMAND="poetry install --no-root --sync --directory $REPO" ;;
		Pipfile.lock) COMMAND="pipenv sync" ;;
		conda-lock.yml | conda-lock.yaml) COMMAND="conda-lock install --prefix $WORK/env $REPO/$LOCK_FILE" ;;
		environment.yml | environment.yaml) COMMAND="conda env create --prefix $WORK/env --file $REPO/$LOCK_FILE" ;;
		requirements.lock)
			COMMAND="$PYTHON -m venv $WORK/venv && $WORK/venv/bin/pip install --no-deps --require-hashes -r $REPO/$LOCK_FILE"
			;;
		esac
		case "$LOCK_FILE" in
		environment.yml | environment.yaml)
			add_finding "resolver-in-the-loop" "$LOCK_FILE is resolved at install time, so the versions installed today may differ from the authors'"
			;;
		esac
		tool=${COMMAND%% *}
		if ! command -v "$tool" >/dev/null 2>&1; then
			add_finding "missing-tool" "$SOURCE needs $tool, which is not on PATH"
			STRATEGY="none"
			REASON="lock file $LOCK_FILE found but $tool is not installed"
		fi
	elif [ -n "$REQ_FILE" ]; then
		STRATEGY="venv-requirements"
		SOURCE="$REQ_FILE"
		COMMAND="$PYTHON -m venv $WORK/venv && $WORK/venv/bin/pip install -r $REPO/$REQ_FILE"
		if [ "$PINNED" != "yes" ]; then
			add_finding "resolver-in-the-loop" "$REQ_FILE is not fully pinned, so pip chooses versions today and the environment is not the authors'"
		fi
	elif [ -f "$REPO/pyproject.toml" ]; then
		STRATEGY="venv-pyproject"
		SOURCE="pyproject.toml"
		COMMAND="$PYTHON -m venv $WORK/venv && $WORK/venv/bin/pip install $REPO"
		add_finding "no-lock-file" "pyproject.toml without a lock file; dependency versions are resolved at install time"
	fi
fi

if [ "$STRATEGY" = "none" ] && [ -z "$REASON" ]; then
	REASON="no container recipe, lock file, requirements file or pyproject.toml in $REPO"
	add_finding "no-environment-recipe" "$REASON"
fi

# ------------------------------------------------------------------ act

BUILD_STATUS="not-run"
if [ "$STRATEGY" != "none" ] && [ "$BUILD" -eq 1 ]; then
	log "building with: $COMMAND"
	if (cd "$WORK" && eval "$COMMAND") >>"$LOG" 2>&1; then
		BUILD_STATUS="ok"
	else
		BUILD_STATUS="failed"
		add_finding "build-failed" "the build command exited non-zero; see $LOG"
	fi
fi

FINDING_COUNT=$(wc -l <"$FINDINGS_FILE" | tr -d ' ')

{
	printf 'repro-env %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	printf 'repo: %s\n' "$REPO"
	printf 'commit: %s\n' "$COMMIT"
	printf 'work: %s\n' "$WORK"
	printf 'strategy: %s\n' "$STRATEGY"
	printf 'source: %s\n' "${SOURCE:-none}"
	printf 'runtime: %s\n' "${RUNTIME:-none}"
	printf 'command: %s\n' "${COMMAND:-none}"
	printf 'build: %s\n' "$BUILD_STATUS"
	printf 'findings: %s\n' "$FINDING_COUNT"
	while IFS='	' read -r kind detail; do
		[ -n "$kind" ] && printf '  - %s: %s\n' "$kind" "$detail"
	done <"$FINDINGS_FILE"
} >"$WORK/repro-env.txt"

{
	printf '{\n'
	printf '  "checks_version": "%s",\n' "$CHECKS_VERSION"
	printf '  "repo": "%s",\n' "$(json_escape "$REPO")"
	printf '  "commit": "%s",\n' "$(json_escape "$COMMIT")"
	printf '  "work": "%s",\n' "$(json_escape "$WORK")"
	printf '  "strategy": "%s",\n' "$STRATEGY"
	printf '  "source": "%s",\n' "$(json_escape "${SOURCE:-}")"
	printf '  "runtime": "%s",\n' "$(json_escape "${RUNTIME:-}")"
	printf '  "command": "%s",\n' "$(json_escape "${COMMAND:-}")"
	printf '  "build": "%s",\n' "$BUILD_STATUS"
	printf '  "reason": "%s",\n' "$(json_escape "${REASON:-}")"
	printf '  "findings": ['
	sep=""
	while IFS='	' read -r kind detail; do
		[ -z "$kind" ] && continue
		printf '%s\n    {"kind": "%s", "detail": "%s"}' "$sep" "$(json_escape "$kind")" "$(json_escape "$detail")"
		sep=","
	done <"$FINDINGS_FILE"
	if [ -n "$sep" ]; then printf '\n  ]\n'; else printf ']\n'; fi
	printf '}\n'
} >"$ENV_JSON"

rm -f "$FINDINGS_FILE"

if [ "$JSON" -eq 1 ]; then
	cat "$ENV_JSON"
else
	cat "$WORK/repro-env.txt"
	if [ "$STRATEGY" != "none" ] && [ "$BUILD" -eq 0 ]; then
		printf '\n[dry-run] rerun with --build to execute the command above\n'
	fi
fi

if [ "$STRATEGY" = "none" ]; then
	log "no clean environment could be built: ${REASON}"
	log "refusing to fall back to the environment on this machine"
	exit 1
fi
if [ "$BUILD_STATUS" = "failed" ]; then
	exit 1
fi
exit 0
