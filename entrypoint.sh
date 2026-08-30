#!/bin/bash
set -e

case "$1" in
  analyze|process)
    script="$1"
    shift
    exec python /app/${script}.py "$@"
    ;;
  *)
    echo "Usage: docker run -v /path/to/videos:/videos wgi-sync <analyze|process> [args]"
    echo ""
    echo "Examples:"
    echo "  docker run -v /data/wgi:/videos wgi-sync analyze /videos"
    echo "  docker run -v /data/wgi:/videos wgi-sync analyze /videos --threshold 0.3"
    echo "  docker run -v /data/wgi:/videos wgi-sync process /videos/config.json"
    echo "  docker run -v /data/wgi:/videos wgi-sync process /videos/config.json --only buckhorn"
    echo "  docker run -v /data/wgi:/videos wgi-sync process /videos/config.json --dry-run"
    ;;
esac
