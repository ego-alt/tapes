#!/usr/bin/env bash
#
# retag-pi.sh — clean the existing library's title/artist tags in place, then
# rescan. Wraps the `flask retag` command, run inside the running `music`
# container (where the code, mutagen, and the bind-mounted music dir all live).
#
# WHAT IT DOES
#   1. Backs up the music DB (instance/music.db) inside the container.
#   2. DRY RUN: prints exactly what would change — no files touched.
#   3. Asks for confirmation, then applies the changes in place and rescans.
#
# PREREQUISITES (on the Pi)
#   - Pull the latest code and rebuild the image so it has `flask retag`:
#       docker compose build music && docker compose up -d music
#   - Run this from the directory that holds docker-compose.yml (the dashboard
#     repo on the home stack), or set COMPOSE_DIR=/path/to/compose.
#
# ⚠️  Tag edits are IN PLACE and irreversible. The DB is backed up automatically,
#     but the audio files are NOT — back up MUSIC_DIR first if you want a net.
#
# USAGE
#   ./retag-pi.sh           # interactive: preview, then confirm
#   ./retag-pi.sh -y        # skip the confirmation prompt
#   MUSIC_SERVICE=music COMPOSE_DIR=~/dashboard ./retag-pi.sh

set -euo pipefail

SERVICE="${MUSIC_SERVICE:-music}"
ASSUME_YES=0
[ "${1:-}" = "-y" ] && ASSUME_YES=1

[ -n "${COMPOSE_DIR:-}" ] && cd "$COMPOSE_DIR"

if ! docker compose ps "$SERVICE" >/dev/null 2>&1; then
  echo "error: no docker compose project here (looked for service '$SERVICE')." >&2
  echo "       run from the compose dir, or set COMPOSE_DIR=/path/to/compose." >&2
  exit 1
fi

echo "==> Backing up the music DB inside the container…"
docker compose exec -T "$SERVICE" sh -c \
  'cp /app/instance/music.db "/app/instance/music.db.pre-retag-$(date +%Y%m%d-%H%M%S).bak"'
echo "    written to instance/ (next to music.db)"

echo
echo "==> DRY RUN — proposed changes (nothing is modified yet):"
echo
docker compose exec -T "$SERVICE" uv run flask --app app:create_app retag

if [ "$ASSUME_YES" -ne 1 ]; then
  echo
  echo "⚠️  Applying rewrites tags in place (DB backed up; audio files are not)."
  read -r -p "Apply these changes? [y/N] " ans
  case "$ans" in
    [yY] | [yY][eE][sS]) ;;
    *) echo "Aborted — nothing changed."; exit 0 ;;
  esac
fi

echo
echo "==> Applying changes and rescanning…"
docker compose exec -T "$SERVICE" uv run flask --app app:create_app retag --write
echo "==> Done."
