import io
import os
import re
import shutil
import subprocess
import time
from typing import Callable, Optional
from PIL import Image
from mutagen.mp4 import MP4, MP4Cover
import requests

def get_ffmpeg_cmd() -> str:
    """Check whether system ffmpeg or static ffmpeg exists."""
    return "ffmpeg"

def sanitize_filename(filename: str) -> str:
    """Sanitize invalid filename characters for safe filesystem storage."""
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    filename = filename.strip('. ')
    return filename or 'untitled'

def process_artwork(
    image_url: str,
    session: requests.Session,
    target_min: int = 1400,
    target_max: int = 2000,
    target_kb_min: int = 300,
    target_kb_max: int = 500
) -> bytes:
    """Crop image to 1:1 square, resize to 1400~2000px, compress to 300KB-500KB JPG"""
    if image_url.startswith('http://'):
        image_url = 'https://' + image_url[7:]
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    }
    if 'bilibili.com' in image_url or 'hdslb.com' in image_url:
        headers['Referer'] = 'https://www.bilibili.com'
    elif 'youtube.com' in image_url or 'ytimg.com' in image_url or 'ggpht.com' in image_url:
        headers['Referer'] = 'https://www.youtube.com'

    resp = session.get(image_url, headers=headers, timeout=10)
    resp.raise_for_status()
    
    img = Image.open(io.BytesIO(resp.content)).convert('RGB')
    
    # 1. Crop to 1:1 square
    w, h = img.size
    min_dim = min(w, h)
    left = (w - min_dim) // 2
    top = (h - min_dim) // 2
    img = img.crop((left, top, left + min_dim, top + min_dim))
    
    # 2. Resize to target dimension (min 1400 for Apple Podcasts spec)
    target_dim = max(target_min, min(target_max, min_dim))
    if target_dim < target_min:
        target_dim = target_min
        
    img = img.resize((target_dim, target_dim), Image.Resampling.LANCZOS)
    
    # 3. Compress with quality tuning to stay within 300KB - 500KB
    quality = 85
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=quality, optimize=True)
    data = out.getvalue()
    size_kb = len(data) / 1024
    
    while size_kb > target_kb_max and quality > 45:
        quality -= 5
        out = io.BytesIO()
        img.save(out, format='JPEG', quality=quality, optimize=True)
        data = out.getvalue()
        size_kb = len(data) / 1024
        
    print(f"Processed artwork: {img.size[0]}x{img.size[1]} px, Quality: {quality}, Size: {size_kb:.2f} KB")
    return data

def ensure_album_cover(up_name: str, up_avatar: str, session: requests.Session, base_download_dir: str = "downloads") -> bool:
    """Download UP's/Channel's avatar and save as cover.jpg in the album directory if it doesn't exist."""
    up_dir = os.path.join(base_download_dir, sanitize_filename(up_name))
    cover_path = os.path.join(up_dir, "cover.jpg")
    
    if os.path.exists(cover_path):
        return True
    if not up_avatar:
        return False
        
    try:
        os.makedirs(up_dir, exist_ok=True)
        img_bytes = process_artwork(up_avatar, session, target_min=1400, target_max=3000)
        with open(cover_path, 'wb') as f:
            f.write(img_bytes)
        return True
    except Exception as e:
        print(f"Error generating album cover for {up_name}: {e}")
        return False

def process_audio_file(
    video_data: dict,
    up_name: str,
    up_avatar_url: str,
    session: requests.Session,
    base_download_dir: str = "downloads",
    progress_cb: Optional[Callable[[str, float], None]] = None,
    send_notification: bool = False
) -> str:
    """Download audio, remux with ffmpeg, tag with mutagen (Episode cover & metadata), save to downloads/UP_Name/"""
    ffmpeg_bin = get_ffmpeg_cmd()
    sanitized_up = sanitize_filename(up_name)
    up_dir = os.path.join(base_download_dir, sanitized_up)
    os.makedirs(up_dir, exist_ok=True)

    # Ensure a standalone cover.jpg (UP Avatar) exists for Audiobookshelf
    ensure_album_cover(up_name, up_avatar_url, session, base_download_dir)
    bvid = video_data['bvid']
    title = video_data['title']
    pic_url = video_data.get('pic', '')
    pubdate = video_data.get('pubdate', video_data.get('created', int(time.time())))
    date_str = time.strftime('%Y-%m-%d', time.localtime(pubdate))
    desc = video_data.get('description', video_data.get('desc', ''))
    audio_url = video_data['audio_url']

    filename = f"{sanitize_filename(title)}.m4a"
    final_filepath = os.path.join(up_dir, filename)
    if os.path.exists(final_filepath):
        return final_filepath

    import uuid
    uid = uuid.uuid4().hex[:8]
    temp_dir = "/tmp/bilipods"
    os.makedirs(temp_dir, exist_ok=True)
    temp_raw_path = os.path.join(temp_dir, f"_temp_{bvid}_{uid}_raw.m4a")
    temp_out_path = os.path.join(temp_dir, f"_temp_{bvid}_{uid}_out.m4a")
    temp_meta_path = os.path.join(temp_dir, f"_temp_{bvid}_{uid}_meta.txt")

    try:
        # 2. Download audio stream with auto-retry
        if progress_cb: progress_cb("正在下载最高音质音频流...", 0.3)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': f'https://www.bilibili.com/video/{bvid}'
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with session.get(audio_url, headers=headers, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    with open(temp_raw_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0 and progress_cb:
                                    pct = 0.3 + 0.4 * (downloaded / total_size)
                                    progress_cb(f"正在下载音频 ({downloaded//1024} KB / {total_size//1024} KB)...", pct)
                break
            except Exception as dl_err:
                if attempt < max_retries - 1:
                    print(f"Retry {attempt+1}/{max_retries} for {bvid} download: {dl_err}")
                    time.sleep(2)
                else:
                    raise dl_err

        # 3. Remux / re-encode using ffmpeg
        if progress_cb: progress_cb("正在转码优化音频封装 (FFmpeg)...", 0.75)
        
        # Create metadata file for single chapter (named as '正文')
        with open(temp_meta_path, "w", encoding="utf-8") as f:
            f.write(f";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=9999999999\ntitle=正文\n")

        cmd = [
            ffmpeg_bin, "-y", 
            "-i", temp_raw_path,
            "-i", temp_meta_path,
            "-map_metadata", "0", "-map_chapters", "1",
            "-c:a", "copy",
            "-movflags", "+faststart",
            temp_out_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            # Fallback re-encode if copy fails
            cmd_fallback = [
                ffmpeg_bin, "-y", 
                "-i", temp_raw_path,
                "-i", temp_meta_path,
                "-map_metadata", "0", "-map_chapters", "1",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                temp_out_path
            ]
            subprocess.run(cmd_fallback, check=True)

        # 4. Process Episode Artwork (video thumbnail pic)
        if progress_cb: progress_cb("正在处理单集封面 (视频原图)...", 0.85)
        ep_art_bytes = None
        if pic_url:
            try:
                ep_art_bytes = process_artwork(pic_url, session, target_min=1400, target_max=2000)
            except Exception as e:
                print(f"Error processing episode artwork: {e}")

        # 5. Embed Apple Podcasts metadata with Mutagen
        if progress_cb: progress_cb("正在嵌入苹果播客 ID3/MP4 元数据...", 0.95)
        audio = MP4(temp_out_path)
        audio["\xa9nam"] = [title]
        audio["\xa9ART"] = [up_name]
        audio["\xa9alb"] = [up_name]
        audio["aART"] = [up_name]
        audio["\xa9day"] = [date_str]
        audio["\xa9cmt"] = [f"{desc}\n\n原视频链接: https://www.bilibili.com/video/{bvid}"]
        if ep_art_bytes:
            audio["covr"] = [MP4Cover(ep_art_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()

        # Move to final location
        if os.path.exists(final_filepath):
            os.remove(final_filepath)
        shutil.move(temp_out_path, final_filepath)
        try:
            os.utime(final_filepath, (pubdate, pubdate))
        except Exception:
            pass

        if progress_cb: progress_cb("提取成功并存储！", 1.0)
        return final_filepath

    finally:
        # Clean temporary files
        if os.path.exists(temp_raw_path):
            try:
                os.remove(temp_raw_path)
            except Exception:
                pass
        if os.path.exists(temp_out_path):
            try:
                os.remove(temp_out_path)
            except Exception:
                pass
        if os.path.exists(temp_meta_path):
            try:
                os.remove(temp_meta_path)
            except Exception:
                pass

def send_bark_summary(up_name: str, up_avatar_url: str, new_episodes: list, platform: str = "bilibili"):
    """Send a single consolidated Bark notification for all new episodes of an UP host or YouTube channel."""
    bark_key = os.getenv("BARK_KEY", "").strip()
    if not new_episodes or not bark_key:
        return
    try:
        bark_server = os.getenv("BARK_SERVER", "https://api.day.app").rstrip("/")
        count = len(new_episodes)
        default_icon = "https://raw.githubusercontent.com/walkxcode/dashboard-icons/main/png/youtube.png" if platform == "youtube" else "https://raw.githubusercontent.com/walkxcode/dashboard-icons/main/png/bilibili.png"
        icon_url = up_avatar_url or default_icon
        if icon_url.startswith("//"):
            icon_url = f"https:{icon_url}"
        elif not icon_url.startswith("http"):
            icon_url = f"https://{icon_url}"

        tag_prefix = "YouTube" if platform == "youtube" else "B站"
        if count == 1:
            ep = new_episodes[0]
            title = ep.get('title', '新播客音频')
            push_title = f"🎙️ {tag_prefix}: {up_name} 更新播客"
            push_body = f"《{title}》\n已自动转制为 Podcast 播客，可随时收听！"
        else:
            push_title = f"🎙️ {tag_prefix}: {up_name} 更新 {count} 集播客"
            sample_titles = [f"• 《{ep.get('title', '')}》" for ep in new_episodes[:3] if ep.get('title')]
            more_text = f"\n...等共 {count} 集音频" if count > 3 else ""
            push_body = "最新剧集：\n" + "\n".join(sample_titles) + more_text + "\n已自动转制入库，可随时收听！"

        resp = requests.post(
            f"{bark_server}/{bark_key}",
            json={
                "title": push_title,
                "body": push_body,
                "group": "BiliPods" if platform == "bilibili" else "YouTubePods",
                "icon": icon_url,
                "sound": "bell"
            },
            timeout=10
        )
        print(f"✅ Consolidated Bark notification sent for [{platform}] {up_name} ({count} episodes) HTTP {resp.status_code}")
    except Exception as push_err:
        print(f"❌ Error sending Bark summary notification: {push_err}")
