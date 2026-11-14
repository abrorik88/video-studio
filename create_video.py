#!/usr/bin/env python3
"""Create a narrated slideshow video from freely licensed Wikimedia Commons images."""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import wave
import asyncio
import edge_tts
from piper import PiperVoice
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "GitHubVideoStudio/1.0 (educational personal project)"}
OUT = Path("output")
WORK = Path("work")
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def clean_html(value):
    value = re.sub(r"<[^>]+>", "", value or "")
    return html.unescape(value).strip()


def commons_images(topic, limit=7):
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {topic}",
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": 1600,
    }
    response = requests.get(API, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    results = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info or not info.get("thumburl"):
            continue
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        meta = info.get("extmetadata", {})
        results.append({
            "title": page.get("title", "Untitled"),
            "url": info["thumburl"],
            "page": info.get("descriptionurl", ""),
            "artist": clean_html(meta.get("Artist", {}).get("value", "")),
            "license": clean_html(meta.get("LicenseShortName", {}).get("value", "")),
            "license_url": meta.get("LicenseUrl", {}).get("value", ""),
        })
    return results


def download_images(items):
    WORK.mkdir(exist_ok=True)
    downloaded = []
    for i, item in enumerate(items):
        try:
            r = requests.get(item["url"], headers=HEADERS, timeout=45)
            r.raise_for_status()
            path = WORK / f"source_{i}.jpg"
            path.write_bytes(r.content)
            with Image.open(path) as im:
                im.verify()
            downloaded.append((path, item))
            time.sleep(0.15)
        except Exception as exc:
            print(f"Skipping image {item.get('title')}: {exc}")
    return downloaded


def split_text(text, count):
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        sentences = [text.strip()]
    groups = [[] for _ in range(count)]
    for i, sentence in enumerate(sentences):
        groups[min(i * count // len(sentences), count - 1)].append(sentence)
    return [" ".join(g) for g in groups]


def load_font(path, size):
    return ImageFont.truetype(path, size)


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def make_slide(src, dest, topic, caption, index, total, size):
    w, h = size
    with Image.open(src) as im:
        im = ImageOps.fit(im.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS)
    # Darken the lower portion for readable captions.
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = overlay.load()
    start = int(h * 0.48)
    for y in range(start, h):
        alpha = int(20 + 175 * ((y - start) / max(1, h - start)))
        for x in range(w):
            pix[x, y] = (0, 0, 0, alpha)
    im = Image.alpha_composite(im.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(im)
    margin = int(w * 0.07)
    title_font = load_font(FONT_BOLD, max(30, int(w * 0.055)))
    body_font = load_font(FONT_REG, max(24, int(w * 0.033)))
    small_font = load_font(FONT_REG, max(18, int(w * 0.021)))

    title_lines = wrap_text(draw, topic, title_font, w - 2 * margin)[:2]
    y = int(h * 0.58)
    for line in title_lines:
        draw.text((margin, y), line, font=title_font, fill="white",
                  stroke_width=2, stroke_fill=(0, 0, 0, 120))
        y += int(title_font.size * 1.2)
    y += int(h * 0.025)
    for line in wrap_text(draw, caption, body_font, w - 2 * margin)[:5]:
        draw.text((margin, y), line, font=body_font, fill=(245, 245, 245))
        y += int(body_font.size * 1.35)
    draw.text((margin, h - int(h * 0.055)),
              f"{index}/{total}  •  Изображения: Wikimedia Commons",
              font=small_font, fill=(230, 230, 230))
    im.convert("RGB").save(dest, quality=92)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--narration", required=True)
    parser.add_argument("--orientation", choices=["portrait", "landscape"], default="portrait")
    parser.add_argument("--voice", choices=["ru", "en"], default="ru")
    args = parser.parse_args()

    topic = args.topic.strip()[:120]
    narration = args.narration.strip()
    if len(narration) < 40:
        sys.exit("Текст озвучки слишком короткий. Добавьте хотя бы 2–3 предложения.")

    voice_name = {"ru": "ru-RU-DmitryNeural", "en": "en-US-GuyNeural"}[args.voice]
    piper_voice_name = {"ru": "ru_RU-denis-medium", "en": "en_US-joe-medium"}[args.voice]

    OUT.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    size = (720, 1280) if args.orientation == "portrait" else (1280, 720)

    print(f"Searching Wikimedia Commons for: {topic}")
    items = commons_images(topic)
    if not items:
        sys.exit("Не удалось найти изображения. Попробуйте другую тему (лучше на английском).")
    downloaded = download_images(items)
    if not downloaded:
        sys.exit("Не удалось скачать изображения из Wikimedia Commons.")

    captions = split_text(narration, len(downloaded))
    slides = []
    credits = [
        "Материалы изображений: Wikimedia Commons.",
        "Проверьте лицензии и условия повторного использования перед публикацией.",
        "Нейросетевая озвучка: Edge TTS с локальным резервным голосом Piper.",
        ""
    ]
    for i, ((src, item), caption) in enumerate(zip(downloaded, captions), start=1):
        dest = WORK / f"slide_{i:02d}.jpg"
        make_slide(src, dest, topic, caption, i, len(downloaded), size)
        slides.append(dest)
        credits.append(f"{i}. {item['title']}")
        credits.append(f"   Автор: {item['artist'] or 'не указан в метаданных'}")
        credits.append(f"   Лицензия: {item['license'] or 'см. страницу файла'}")
        credits.append(f"   Лицензия URL: {item['license_url']}")
        credits.append(f"   Страница файла: {item['page']}")
        credits.append("")

    credits.append("Wikimedia Commons: https://commons.wikimedia.org/")
    (OUT / "credits.txt").write_text("\n".join(credits), encoding="utf-8")

    voice_path = WORK / "voice.mp3"
    try:
        async def synthesize_voice():
            communicate = edge_tts.Communicate(
                narration, voice_name, rate="+0%", volume="+0%", pitch="+0Hz"
            )
            await communicate.save(str(voice_path))

        asyncio.run(synthesize_voice())
        duration_result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(voice_path)
        ], check=True, capture_output=True, text=True)
        audio_seconds = float(duration_result.stdout.strip())
        print(f"Using Edge neural voice: {voice_name}")
    except Exception as exc:
        print(f"Edge TTS unavailable ({exc}); using local neural voice: {piper_voice_name}")
        voice_path = WORK / "voice.wav"
        piper_voice = PiperVoice.load(f"{piper_voice_name}.onnx")
        with wave.open(str(voice_path), "wb") as wf:
            piper_voice.synthesize_wav(narration, wf)
        with wave.open(str(voice_path), "rb") as wf:
            audio_seconds = wf.getnframes() / float(wf.getframerate())

    total_seconds = max(audio_seconds + 0.8, 12.0)
    per_slide = total_seconds / len(slides)
    concat_file = WORK / "slides.txt"
    with concat_file.open("w", encoding="utf-8") as f:
        for slide in slides:
            f.write(f"file '{slide.resolve()}'\n")
            f.write(f"duration {per_slide:.3f}\n")
        f.write(f"file '{slides[-1].resolve()}'\n")

    output = OUT / "video.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(voice_path),
        "-vf", "fps=25,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart",
        str(output)
    ], check=True)

    print(f"Video created: {output}")
    print(f"Duration target: {total_seconds:.1f} seconds")
    print("Download output/video.mp4 and output/credits.txt from the workflow artifact.")


if __name__ == "__main__":
    main()
