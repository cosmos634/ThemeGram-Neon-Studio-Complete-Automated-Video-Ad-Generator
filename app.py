#!/usr/bin/env python3
"""ThemeGram Neon Studio: lightweight local video-ad maker for Termux."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import Flask, jsonify, request, send_from_directory, render_template

ROOT = Path(__file__).resolve().parent
MEDIA = ROOT / "media"
EXPORTS = ROOT / "exports"
PROJECTS = ROOT / "projects"
CACHE = ROOT / "cache"
LOGS = ROOT / "logs"
FOLDERS = {name: MEDIA / name for name in ("images", "logos", "videos", "audio", "backgrounds")}
for folder in [*FOLDERS.values(), EXPORTS, PROJECTS, CACHE, LOGS]:
    folder.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False
jobs = {}
job_lock = threading.Lock()
ALLOWED = {
    "images": {".png", ".jpg", ".jpeg", ".webp"},
    "logos": {".png", ".jpg", ".jpeg", ".webp"},
    "videos": {".mp4", ".mov", ".m4v"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg"},
    "backgrounds": {".png", ".jpg", ".jpeg", ".webp"},
}
DEFAULT_PROJECT = {
    "name": "ThemeGram — Neon Promo",
    "settings": {"preset": "preview", "fps": 24, "quality": "medium", "audio": "", "volume": 0.35},
    "scenes": [
        {"title": "Telegram'ingga yangi ko'rinish ber.", "subtitle": "ThemeGram bilan uslubingni top", "duration": 2.5, "accent": "#9b5cff", "asset": "", "animation": "zoom"},
        {"title": "TEMALAR OLAMI", "subtitle": "O'zingga mos temani tanla", "duration": 2.5, "accent": "#22d3ee", "asset": "", "animation": "slide"},
        {"title": "@theme_gram_bot", "subtitle": "Botga kir va sevimli uslubingni tanla", "duration": 3, "accent": "#a855f7", "asset": "", "animation": "zoom"},
    ],
}
PRESETS = {
    "preview": (480, 854),
    "vertical_hd": (720, 1280),
    "reels": (1080, 1920),
    "square": (1080, 1080),
    "landscape": (1920, 1080),
}


def tool_path(name):
    return shutil.which(name)


def ffmpeg_info():
    ffmpeg = tool_path("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "error": "FFmpeg topilmadi. Termux'da: pkg install ffmpeg"}
    try:
        version = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=8).stdout.splitlines()[0]
        enc = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=8).stdout
        filters = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=8).stdout
        return {"ok": True, "version": version, "h264": "libx264" in enc, "aac": " aac " in enc or "aac" in enc, "xfade": "xfade" in filters, "drawtext": "drawtext" in filters}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def safe_asset_path(filename):
    if not filename:
        return None
    # References use "category/name"; old projects may contain only a filename.
    raw = Path(str(filename))
    if raw.is_absolute() or ".." in raw.parts:
        return None
    if len(raw.parts) == 2 and raw.parts[0] in FOLDERS:
        candidate = (FOLDERS[raw.parts[0]] / raw.parts[1]).resolve()
        base = FOLDERS[raw.parts[0]].resolve()
    elif len(raw.parts) == 1:
        matches = [(folder / raw.name).resolve() for folder in FOLDERS.values() if (folder / raw.name).is_file()]
        if len(matches) != 1:
            return None
        candidate = matches[0]
        base = candidate.parent
    else:
        return None
    if base not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def probe(path):
    ffprobe = tool_path("ffprobe")
    if not ffprobe:
        return {}
    try:
        raw = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration,size:stream=codec_name,width,height", "-of", "json", str(path)], capture_output=True, text=True, timeout=10, check=True).stdout
        data = json.loads(raw)
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        return {"duration": round(float(fmt.get("duration", 0)), 2), "bytes": int(fmt.get("size", path.stat().st_size)), "width": next((s.get("width") for s in streams if s.get("width")), None), "height": next((s.get("height") for s in streams if s.get("height")), None), "codec": next((s.get("codec_name") for s in streams if s.get("codec_name")), None)}
    except Exception:
        return {}


def validate_project(data):
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list) or not data["scenes"]:
        raise ValueError("Loyihada kamida bitta sahna bo'lishi kerak.")
    if len(data["scenes"]) > 12:
        raise ValueError("Bitta videoda ko'pi bilan 12 ta sahna ishlating.")
    settings = data.setdefault("settings", {})
    settings["preset"] = settings.get("preset", "preview")
    if settings["preset"] not in PRESETS:
        settings["preset"] = "preview"
    settings["fps"] = max(12, min(30, int(settings.get("fps", 24))))
    for scene in data["scenes"]:
        scene["title"] = str(scene.get("title", ""))[:180]
        scene["subtitle"] = str(scene.get("subtitle", ""))[:240]
        scene["duration"] = max(1.0, min(8.0, float(scene.get("duration", 2.5))))
        accent = str(scene.get("accent", "#9b5cff"))
        scene["accent"] = accent if re.fullmatch(r"#[0-9a-fA-F]{6}", accent) else "#9b5cff"
        scene["asset"] = str(scene.get("asset", ""))[:255]
        if scene["asset"] and not safe_asset_path(scene["asset"]):
            scene["asset"] = ""
    settings["volume"] = max(0.0, min(1.0, float(settings.get("volume", 0.35))))
    audio = str(settings.get("audio", ""))
    settings["audio"] = audio if audio and safe_asset_path(audio) else ""
    return data


def render_video(job_id, project):
    log_path = LOGS / f"{job_id}.log"
    work = CACHE / job_id
    work.mkdir(parents=True, exist_ok=True)
    out_name = secure_filename(str(project.get("name", "themegram-ad")).strip().replace(" ", "-"))[:60] or "themegram-ad"
    output = EXPORTS / f"{out_name}-{job_id[:6]}.mp4"
    ffmpeg = tool_path("ffmpeg")
    if not ffmpeg:
        with job_lock: jobs[job_id].update(status="error", error="FFmpeg topilmadi. Termux'da: pkg install ffmpeg")
        return
    width, height = PRESETS[project["settings"]["preset"]]
    fps = project["settings"]["fps"]
    scenes = project["scenes"]
    total = sum(float(s["duration"]) for s in scenes)
    started = time.time()
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
        font_candidates = ["/system/fonts/Roboto-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans.ttf"]
        bold_candidates = ["/system/fonts/Roboto-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"]
        font_path = next((p for p in font_candidates if Path(p).exists()), None)
        bold_path = next((p for p in bold_candidates if Path(p).exists()), font_path)
        def font(size, bold=False):
            path = bold_path if bold else font_path
            try: return ImageFont.truetype(path, size=size) if path else ImageFont.load_default()
            except Exception: return ImageFont.load_default()
        segments = []
        for index, scene in enumerate(scenes):
            with job_lock:
                if jobs.get(job_id, {}).get("cancel_requested"):
                    raise RuntimeError("Render foydalanuvchi tomonidan bekor qilindi.")
                jobs[job_id].update(progress=int(index / len(scenes) * 90), message=f"{index+1}/{len(scenes)}-sahna tayyorlanmoqda")
            img = Image.new("RGB", (width, height), (7, 7, 17))
            draw = ImageDraw.Draw(img)
            accent = scene["accent"]
            rgb = tuple(int(accent[i:i+2], 16) for i in (1, 3, 5))
            # Soft, low-cost radial glows; generated locally, no downloaded assets.
            glow = Image.new("RGBA", (max(1, width // 5), max(1, height // 5)), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gw, gh = glow.size
            gd.ellipse((gw*.05, gh*.1, gw*.95, gh*.9), fill=(*rgb, 100))
            glow = glow.resize((width, height), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(max(12, width//18)))
            img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
            draw = ImageDraw.Draw(img)
            for x in range(0, width, max(36, width//12)):
                draw.line((x, 0, x-width//2, height), fill=(25, 22, 45), width=max(1, width//600))
            margin = int(width * .09)
            # Smartphone mockup is clearly illustrative, not a real app screenshot.
            phone_w, phone_h = int(width*.56), int(height*.34)
            px, py = (width-phone_w)//2, int(height*.12)
            draw.rounded_rectangle((px, py, px+phone_w, py+phone_h), radius=max(12, width//30), fill=(15, 15, 29), outline=(*rgb, 255), width=max(2, width//240))
            draw.rounded_rectangle((px+int(phone_w*.07), py+int(phone_h*.09), px+int(phone_w*.93), py+int(phone_h*.9)), radius=max(8, width//45), fill=(25, 22, 43))
            draw.text((px+int(phone_w*.12), py+int(phone_h*.17)), "ThemeGram", font=font(max(12, width//22), True), fill=(235, 232, 255))
            for j, col in enumerate([(155,92,255),(34,211,238),(124,58,237)]):
                yy = py+int(phone_h*(.36+j*.16))
                draw.rounded_rectangle((px+int(phone_w*.12), yy, px+int(phone_w*.88), yy+max(10,int(phone_h*.09))), radius=8, fill=col)
            asset = safe_asset_path(scene.get("asset", ""))
            if asset:
                try:
                    with Image.open(asset) as source:
                        source = source.convert("RGBA")
                        source.thumbnail((int(width*.78), int(height*.27)))
                        ax, ay = (width-source.width)//2, int(height*.48)
                        img.paste(source, (ax, ay), source if source.mode == "RGBA" else None)
                        draw = ImageDraw.Draw(img)
                except Exception as exc:
                    with open(log_path, "a", encoding="utf-8") as log: log.write(f"asset warning: {asset.name}: {exc}\n")
            title = scene["title"]
            sub = scene["subtitle"]
            title_font = font(max(18, int(width*.075)), True)
            sub_font = font(max(12, int(width*.035)))
            def wrap(text, fnt, max_width):
                words, lines, line = text.split(), [], ""
                for word in words:
                    test = f"{line} {word}".strip()
                    if draw.textbbox((0,0), test, font=fnt)[2] <= max_width or not line:
                        line = test
                    else:
                        lines.append(line); line = word
                if line: lines.append(line)
                return lines[:4]
            y = int(height*.69)
            for line in wrap(title, title_font, width-2*margin):
                bbox = draw.textbbox((0,0), line, font=title_font)
                draw.text(((width-(bbox[2]-bbox[0]))//2, y), line, font=title_font, fill=(248,246,255), stroke_width=max(1,width//500), stroke_fill=(*rgb,255))
                y += int(width*.09)
            y += int(height*.012)
            for line in wrap(sub, sub_font, width-2*margin):
                bbox = draw.textbbox((0,0), line, font=sub_font)
                draw.text(((width-(bbox[2]-bbox[0]))//2, y), line, font=sub_font, fill=(190,190,215))
                y += int(width*.05)
            footer = "@theme_gram_bot  •  TEMALAR OLAMI"
            ff = font(max(10, width//38), True)
            bb = draw.textbbox((0,0), footer, font=ff)
            draw.text(((width-(bb[2]-bb[0]))//2, int(height*.94)), footer, font=ff, fill=(*rgb,255))
            still = work / f"scene-{index:02d}.png"
            img.save(still, optimize=True)
            segment = work / f"scene-{index:02d}.mp4"
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", str(still), "-t", str(scene["duration"]), "-r", str(fps), "-vf", f"scale={width}:{height},format=yuv420p", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28" if width >= 1080 else "25", "-movflags", "+faststart", str(segment)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=max(60, int(scene["duration"]*fps*3)))
            if result.returncode:
                # Some builds lack libx264; try their default MPEG-4 encoder.
                cmd[cmd.index("libx264")] = "mpeg4"
                cmd[cmd.index("28" if width >= 1080 else "25")] = "5"
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=max(60, int(scene["duration"]*fps*3)))
            if result.returncode:
                raise RuntimeError(result.stderr[-1200:] or "Sahna videosini yaratib bo'lmadi.")
            segments.append(segment)
            with job_lock: jobs[job_id].update(progress=int((index+1)/len(scenes)*90), message=f"{index+1}/{len(scenes)} sahna tayyor")
        list_file = work / "concat.txt"
        list_file.write_text("".join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in segments), encoding="utf-8")
        joined = work / "joined.mp4"
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(joined)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=max(90, int(total*fps*2)))
        if result.returncode: raise RuntimeError(result.stderr[-1200:] or "Sahnalarni birlashtirib bo'lmadi.")
        audio_name = project["settings"].get("audio", "")
        audio_path = safe_asset_path(audio_name)
        if audio_path:
            final_cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-stream_loop", "-1", "-i", str(audio_path), "-t", str(total), "-filter:a", f"volume={project['settings']['volume']},afade=t=in:st=0:d=0.6,afade=t=out:st={max(0,total-.7)}:d=0.7", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(output)]
        else:
            final_cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-c", "copy", "-movflags", "+faststart", str(output)]
        with job_lock: jobs[job_id].update(progress=94, message="Yakuniy MP4 tayyorlanmoqda")
        result = subprocess.run(final_cmd, capture_output=True, text=True, timeout=max(120, int(total*fps*3)))
        if result.returncode and audio_path:
            # Audio codec/filter incompatibility fallback: render video without audio rather than lose the whole export.
            result = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-c", "copy", str(output)], capture_output=True, text=True, timeout=120)
            if result.returncode: raise RuntimeError(result.stderr[-1200:] or "MP4 eksporti amalga oshmadi.")
            with job_lock: jobs[job_id]["warning"] = "Audio qo'shilmadi; video ovozsiz saqlandi."
        elif result.returncode:
            raise RuntimeError(result.stderr[-1200:] or "MP4 eksporti amalga oshmadi.")
        info = probe(output)
        if not output.is_file() or output.stat().st_size < 1000:
            raise RuntimeError("Eksport fayli yo'q yoki juda kichik. Logni tekshiring.")
        with job_lock:
            jobs[job_id].update(status="done", progress=100, message="Tayyor", output=output.name, info=info or {"bytes": output.stat().st_size}, elapsed=round(time.time()-started,1))
    except Exception as exc:
        with open(log_path, "a", encoding="utf-8") as log: log.write(f"\nERROR: {exc}\n")
        with job_lock: jobs[job_id].update(status="error", error=str(exc), log=str(log_path), message="Render xatoligi")
    finally:
        # Only successful renders have their cache removed; failures keep logs and temporary media for diagnosis.
        with job_lock: done = jobs.get(job_id, {}).get("status") == "done"
        if done: shutil.rmtree(work, ignore_errors=True)


@app.get("/")
def index():
    return render_template("index.html", default_project=DEFAULT_PROJECT)


@app.get("/api/diagnostics")
def diagnostics():
    try:
        import PIL
        pillow = PIL.__version__
    except Exception: pillow = None
    usage = shutil.disk_usage(ROOT)
    try:
        mem = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()[:3]
    except Exception: mem = []
    return jsonify({"python": __import__("sys").version.split()[0], "platform": __import__("platform").platform(), "pillow": pillow, "ffmpeg": ffmpeg_info(), "storage_free_bytes": usage.free, "storage_free_gb": round(usage.free/1024**3,2), "memory": mem, "project_root": str(ROOT)})


@app.get("/api/media")
def media_list():
    items = []
    for category, folder in FOLDERS.items():
        for p in sorted(folder.iterdir()):
            if p.is_file():
                items.append({"name": p.name, "category": category, "path": f"{category}/{p.name}", "bytes": p.stat().st_size, **probe(p)})
    return jsonify(items)


@app.post("/api/upload")
def upload():
    category = request.form.get("category", "images")
    if category not in FOLDERS: return jsonify(error="Media turi noto'g'ri."), 400
    f = request.files.get("file")
    if not f or not f.filename: return jsonify(error="Fayl tanlanmadi."), 400
    original = secure_filename(f.filename)
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED[category]: return jsonify(error="Bu turdagi fayl tanlangan bo'limda qo'llab-quvvatlanmaydi."), 400
    name = original or f"upload{suffix}"
    dest = FOLDERS[category] / name
    if dest.exists(): name = f"{Path(name).stem}-{uuid.uuid4().hex[:6]}{suffix}"; dest = FOLDERS[category] / name
    try:
        f.save(dest)
        if dest.stat().st_size == 0: dest.unlink(); return jsonify(error="Fayl bo'sh."), 400
        if category in ("images", "logos", "backgrounds"):
            from PIL import Image
            with Image.open(dest) as im: im.verify()
        elif category in ("videos", "audio") and tool_path("ffprobe"):
            meta = probe(dest)
            if not meta: raise ValueError("Faylni FFprobe o'qiy olmadi.")
        return jsonify({"ok": True, "name": name, "category": category, "path": f"{category}/{name}", "bytes": dest.stat().st_size})
    except Exception as exc:
        dest.unlink(missing_ok=True)
        return jsonify(error=f"Fayl tekshiruvdan o'tmadi: {exc}"), 400


@app.delete("/api/media/<category>/<path:name>")
def delete_media(category, name):
    if category not in FOLDERS: return jsonify(error="Bo'lim topilmadi."), 404
    path = (FOLDERS[category] / name).resolve()
    if FOLDERS[category].resolve() not in path.parents or not path.is_file(): return jsonify(error="Fayl topilmadi."), 404
    path.unlink()
    return jsonify(ok=True)


@app.get("/api/projects")
def list_projects():
    return jsonify([{"name": p.stem, "file": p.name, "bytes": p.stat().st_size} for p in sorted(PROJECTS.glob("*.json"))])


@app.post("/api/projects")
def save_project():
    try:
        data = validate_project(request.get_json(force=True))
        name = secure_filename(str(data.get("name", "project")))[:60] or "project"
        target = PROJECTS / f"{name}.json"
        if target.exists(): target = PROJECTS / f"{name}-{uuid.uuid4().hex[:5]}.json"
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify(ok=True, file=target.name)
    except Exception as exc: return jsonify(error=str(exc)), 400


@app.get("/api/projects/<path:name>")
def load_project(name):
    path = (PROJECTS / name).resolve()
    if PROJECTS.resolve() not in path.parents or path.suffix != ".json" or not path.is_file(): return jsonify(error="Loyiha topilmadi."), 404
    try: return jsonify(validate_project(json.loads(path.read_text(encoding="utf-8"))))
    except Exception as exc: return jsonify(error=f"Loyiha fayli buzilgan: {exc}"), 400


@app.post("/api/render")
def start_render():
    try:
        data = validate_project(request.get_json(force=True))
        info = ffmpeg_info()
        if not info.get("ok"): return jsonify(error=info.get("error", "FFmpeg mavjud emas.")), 400
        free = shutil.disk_usage(ROOT).free
        width, height = PRESETS[data["settings"]["preset"]]
        if free < max(150 * 1024 * 1024, width * height * 2):
            return jsonify(error="Bo'sh xotira kam. Keraksiz fayllarni o'chiring yoki Preview formatini tanlang."), 400
        with job_lock:
            if any(j.get("status") == "running" for j in jobs.values()):
                return jsonify(error="Boshqa render ishlayapti. Avval tugashini kuting."), 409
            job_id = uuid.uuid4().hex
            jobs[job_id] = {"status": "running", "progress": 0, "message": "Render navbatga qo'shildi", "started": time.time()}
        threading.Thread(target=render_video, args=(job_id, data), daemon=True).start()
        return jsonify(job_id=job_id)
    except Exception as exc: return jsonify(error=str(exc)), 400


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    with job_lock: job = jobs.get(job_id)
    if not job: return jsonify(error="Render ishi topilmadi."), 404
    return jsonify(job)


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id):
    # Cancellation is intentionally conservative: no arbitrary process killing.
    with job_lock:
        job = jobs.get(job_id)
        if not job: return jsonify(error="Render ishi topilmadi."), 404
        job["cancel_requested"] = True
    return jsonify(ok=True, message="Bekor qilish belgisi yuborildi. Ushbu versiyada faol FFmpeg jarayoni xavfsiz to'xtatilmasligi mumkin.")


@app.get("/api/exports")
def exports_list():
    return jsonify([{"name": p.name, "bytes": p.stat().st_size, **probe(p)} for p in sorted(EXPORTS.glob("*.mp4"), key=lambda p:p.stat().st_mtime, reverse=True)])


@app.get("/exports/<path:name>")
def download_export(name):
    return send_from_directory(EXPORTS, name, as_attachment=True)


@app.get("/media/<category>/<path:name>")
def serve_media(category, name):
    if category not in FOLDERS: return "Not found", 404
    return send_from_directory(FOLDERS[category], name)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ThemeGram Neon Studio")
    parser.add_argument("--diagnose", action="store_true", help="FFmpeg, Pillow, xotira va diskni tekshirish")
    parser.add_argument("--demo", action="store_true", help="Namuna loyihadan MP4 render qilish")
    args = parser.parse_args()
    if args.diagnose:
        try:
            import PIL
            pillow = PIL.__version__
        except Exception:
            pillow = "TOPILMADI"
        usage = shutil.disk_usage(ROOT)
        print("Python:", __import__("sys").version.split()[0])
        print("Platform:", __import__("platform").platform())
        print("Pillow:", pillow)
        print("FFmpeg:", json.dumps(ffmpeg_info(), ensure_ascii=False))
        print("Disk bo‘sh GiB:", round(usage.free / 1024**3, 2))
        try:
            print("RAM:", Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()[:3])
        except Exception:
            print("RAM: aniqlanmadi")
        raise SystemExit(0)
    if args.demo:
        try:
            import PIL
        except Exception:
            raise SystemExit("Pillow topilmadi: pip install -r requirements.txt")
        if not ffmpeg_info().get("ok"):
            raise SystemExit("FFmpeg topilmadi: pkg install ffmpeg")
        demo_id = "demo-" + uuid.uuid4().hex[:8]
        jobs[demo_id] = {"status": "running", "progress": 0}
        render_video(demo_id, json.loads(json.dumps(DEFAULT_PROJECT)))
        print(json.dumps(jobs[demo_id], ensure_ascii=False, indent=2))
        if jobs[demo_id].get("status") != "done":
            raise SystemExit("Demo render muvaffaqiyatsiz. Logs papkasini tekshiring.")
        raise SystemExit(0)
    host = os.environ.get("THEMEGRAM_HOST", "127.0.0.1")
    port = int(os.environ.get("THEMEGRAM_PORT", "8765"))
    print(f"ThemeGram Neon Studio: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
