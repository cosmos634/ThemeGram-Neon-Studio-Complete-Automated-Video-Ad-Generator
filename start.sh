#!/data/data/com.termux/files/usr/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg topilmadi. O‘rnating: pkg install ffmpeg"
  exit 1
fi
if ! python -c "import flask, PIL" >/dev/null 2>&1; then
  echo "Python kutubxonalari yetishmaydi. O‘rnating: pip install -r requirements.txt"
  exit 1
fi
exec python app.py "$@"
