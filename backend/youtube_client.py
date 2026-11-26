import os
import io
import re
import time
import datetime
import shutil
import subprocess
import urllib.parse
from typing import Dict, Any, List, Optional, Callable
from PIL import Image
from mutagen.mp4 import MP4, MP4Cover
import requests
import yt_dlp

from backend.audio_processor import sanitize_filename, process_artwork, ensure_album_cover, get_ffmpeg_cmd, send_bark_summary

def format_duration(seconds: Optional[int]) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if not seconds or seconds < 0:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

class YouTubeClient:
    def __init__(self, cookie_file: str = "data/youtube_cookies.txt", download_dir: str = "downloads"):
        self.cookie_file = cookie_file
        self.download_dir = download_dir
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        })
        os.makedirs(os.path.dirname(os.path.abspath(self.cookie_file)), exist_ok=True)
        os.makedirs(self.download_dir, exist_ok=True)

    def has_valid_cookies(self) -> bool:
        return os.path.exists(self.cookie_file) and os.path.getsize(self.cookie_file) > 10

    def get_auth_status(self) -> dict:
        has_cookies = self.has_valid_cookies()
        mtime = os.path.getmtime(self.cookie_file) if has_cookies else 0
        return {
            "has_cookies": has_cookies,
            "cookie_file": self.cookie_file,
            "mtime": mtime,
            "date_str": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime)) if mtime else None
        }

    def get_user_subscriptions(self) -> List[dict]:
        """Fetch all subscribed YouTube channels of the logged-in user using cookies."""
        if not self.has_valid_cookies():
            raise Exception("尚未配置 YouTube Cookie，请先配置 Cookie")

        ydl_opts = self._get_base_ydl_opts({
            'extract_flat': True
        })
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info('https://www.youtube.com/feed/channels', download=False)
            entries = list(info.get('entries', []))
            channels = []
            for e in entries:
                if not e:
                    continue
                name = e.get('title') or e.get('uploader') or e.get('channel') or '未知频道'
                url = e.get('url') or ''
                c_id = e.get('id') or (url.split('/')[-1] if url else 'unknown')
                thumbs = e.get('thumbnails', [])
                avatar = thumbs[-1].get('url', '') if thumbs else ''
                if avatar.startswith('//'):
                    avatar = f'https:{avatar}'
                channels.append({
                    'id': c_id,
                    'mid': c_id,
                    'name': name,
                    'uname': name,
                    'avatar': avatar,
                    'face': avatar,
                    'url': url,
                    'sign': e.get('description', '')
                })
            return channels

    def save_cookies(self, raw_cookie_content: str) -> bool:
        """Parse raw cookie header or Netscape format and save to cookie_file."""
        raw_cookie_content = raw_cookie_content.strip()
        if not raw_cookie_content:
            if os.path.exists(self.cookie_file):
                os.remove(self.cookie_file)
            return True

        # Check if already Netscape format
        if '# Netscape' in raw_cookie_content or '\t' in raw_cookie_content:
            netscape_content = raw_cookie_content
        else:
            lines = [
                '# Netscape HTTP Cookie File',
                '# https://curl.haxx.se/rfc/cookie_spec.html',
                ''
            ]
            parts = [p.strip() for p in raw_cookie_content.split(';') if p.strip()]
            for p in parts:
                if '=' in p:
                    k, v = p.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    lines.append(f'.youtube.com\tTRUE\t/\tTRUE\t2147483647\t{k}\t{v}')
            netscape_content = '\n'.join(lines) + '\n'

        with open(self.cookie_file, 'w', encoding='utf-8') as f:
            f.write(netscape_content)
        return True

    def _get_base_ydl_opts(self, extra_opts: Optional[dict] = None) -> dict:
        opts = {
            'quiet': True,
            'no_warnings': True
        }
        if self.has_valid_cookies():
            opts['cookiefile'] = self.cookie_file
        if extra_opts:
            opts.update(extra_opts)
        return opts

    @staticmethod
    def parse_query_type(query: str) -> dict:
        """Identify if query is a video, playlist, channel, or plain search string."""
        q = query.strip()
        
        # 1. Single video check
        # e.g., https://www.youtube.com/watch?v=xxx, https://youtu.be/xxx, https://www.youtube.com/shorts/xxx
        video_id = None
        if 'youtu.be/' in q:
            video_id = q.split('youtu.be/')[1].split('?')[0].split('&')[0].split('/')[0]
        elif 'youtube.com/watch' in q and 'v=' in q:
            parsed = urllib.parse.urlparse(q)
            qs = urllib.parse.parse_qs(parsed.query)
            if 'v' in qs:
                video_id = qs['v'][0]
        elif 'youtube.com/shorts/' in q:
            video_id = q.split('youtube.com/shorts/')[1].split('?')[0].split('&')[0].split('/')[0]
        elif re.match(r'^[a-zA-Z0-9_-]{11}$', q):
            video_id = q

        if video_id:
            return {
                "type": "video",
                "id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}"
            }

        # 2. Playlist check
        if 'playlist?list=' in q or ('youtube.com' in q and '&list=' in q):
            parsed = urllib.parse.urlparse(q)
            qs = urllib.parse.parse_qs(parsed.query)
            if 'list' in qs:
                playlist_id = qs['list'][0]
                return {
                    "type": "playlist",
                    "id": playlist_id,
                    "url": f"https://www.youtube.com/playlist?list={playlist_id}"
                }

        # 3. Channel / Handle / Channel ID check
        if q.startswith('@'):
            return {
                "type": "channel",
                "id": q,
                "url": f"https://www.youtube.com/{q}"
            }
        if re.match(r'^(UC|HC)[a-zA-Z0-9_-]{22}$', q):
            return {
                "type": "channel",
                "id": q,
                "url": f"https://www.youtube.com/channel/{q}"
            }
        if 'youtube.com/@' in q or 'youtube.com/channel/' in q or 'youtube.com/c/' in q or 'youtube.com/user/' in q:
            clean_url = q.split('?')[0].split('#')[0].rstrip('/')
            return {
                "type": "channel",
                "id": clean_url.split('/')[-1],
                "url": clean_url
            }

        # 4. Fallback search
        return {
            "type": "search",
            "id": q,
            "url": f"ytsearch10:{q}"
        }

    def search_or_parse(self, query: str, max_results: Optional[int] = None) -> dict:
        """Universal parser/search for YouTube URLs or text."""
        parsed_type = self.parse_query_type(query)
        target_type = parsed_type["type"]
        target_url = parsed_type["url"]

        if target_type == "video":
            video_info = self.get_video_info(target_url)
            return {
                "result_type": "video",
                "video": video_info,
                "channel": {
                    "id": video_info.get("channel_id", ""),
                    "name": video_info.get("channel", "YouTube"),
                    "avatar": video_info.get("channel_avatar", ""),
                    "url": video_info.get("channel_url", "")
                }
            }
        
        elif target_type in ["channel", "playlist", "search"]:
            fetch_url = target_url
            if target_type == "channel" and not any(x in fetch_url for x in ['/videos', '/shorts', '/streams']):
                fetch_url = f"{fetch_url.rstrip('/')}/videos"

            extra_opts = {
                'extract_flat': True
            }
            if max_results and max_results > 0:
                extra_opts['playlistend'] = max_results
            elif target_type == "search" and not max_results:
                extra_opts['playlistend'] = 30

            ydl_opts = self._get_base_ydl_opts(extra_opts)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(fetch_url, download=False)
                if not info:
                    raise Exception("未能获取 YouTube 页面内容")

                channel_name = info.get('uploader') or info.get('channel') or info.get('title') or "YouTube 播客"
                if channel_name.endswith(" - Videos"):
                    channel_name = channel_name[:-9]

                channel_id = info.get('channel_id') or info.get('id') or parsed_type.get('id') or "youtube"
                channel_url = info.get('channel_url') or info.get('uploader_url') or target_url

                # Extract avatar/thumbnail
                avatar_url = ""
                thumbnails = info.get('thumbnails', [])
                if thumbnails:
                    # Pick square-ish or avatar thumbnail
                    avatars = [t.get('url') for t in thumbnails if 'avatar' in t.get('id', '') or 'avatar' in t.get('url', '') or 's176' in t.get('url', '') or 's900' in t.get('url', '')]
                    avatar_url = avatars[-1] if avatars else thumbnails[-1].get('url', '')

                raw_entries = info.get('entries', [])
                videos = []
                for entry in raw_entries:
                    if not entry:
                        continue
                    v_id = entry.get('id')
                    v_title = entry.get('title', '未知标题')
                    v_dur = entry.get('duration') or 0
                    v_dur_str = format_duration(v_dur)
                    v_thumb = ""
                    entry_thumbs = entry.get('thumbnails', [])
                    if entry_thumbs:
                        v_thumb = entry_thumbs[-1].get('url', '')
                    elif v_id:
                        v_thumb = f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                    # Check if video is member-only / paid
                    availability = entry.get('availability', '')
                    is_member_availability = availability in ['subscriber_only', 'premium_only', 'needs_auth']
                    title_keywords = ['【会员视频】', '【会员】', '[会员]', '(会员)', '[Members Only]', '(Members Only)', '会员专享', '会员限定', '会员专属', '频道会员', '充电专属']
                    is_member_title = any(kw in v_title for kw in title_keywords)
                    is_paid = is_member_availability or is_member_title
                    pay_badge = "会员专属" if is_paid else ""

                    videos.append({
                        "bvid": v_id,  # unified key for compatibility with frontend/subscription
                        "id": v_id,
                        "title": v_title,
                        "duration_seconds": v_dur,
                        "duration_str": v_dur_str,
                        "pic": v_thumb,
                        "thumbnail": v_thumb,
                        "url": entry.get('url') or f"https://www.youtube.com/watch?v={v_id}",
                        "channel": channel_name,
                        "channel_id": channel_id,
                        "is_paid": is_paid,
                        "disabled": is_paid,
                        "pay_badge": pay_badge
                    })

                return {
                    "result_type": target_type,
                    "channel": {
                        "id": channel_id,
                        "mid": channel_id, # for unified frontend handling
                        "name": channel_name,
                        "title": channel_name,
                        "avatar": avatar_url,
                        "face": avatar_url, # for unified frontend handling
                        "url": channel_url,
                        "description": info.get('description', '')
                    },
                    "videos": videos,
                    "total": info.get('playlist_count') or len(videos)
                }

    def get_video_info(self, video_url_or_id: str) -> dict:
        """Get complete details for a single YouTube video."""
        if not video_url_or_id.startswith('http'):
            video_url = f"https://www.youtube.com/watch?v={video_url_or_id}"
        else:
            video_url = video_url_or_id

        ydl_opts = self._get_base_ydl_opts({
            'extract_flat': False
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info:
                raise Exception("无法解析视频信息")

            v_id = info.get('id')
            title = info.get('title', '未知标题')
            channel = info.get('channel') or info.get('uploader') or 'YouTube'
            channel_id = info.get('channel_id') or info.get('uploader_id') or ''
            channel_url = info.get('channel_url') or info.get('uploader_url') or ''
            duration = info.get('duration', 0)
            upload_date = info.get('upload_date', '') # YYYYMMDD
            desc = info.get('description', '')

            # Thumbnail
            thumbnail = info.get('thumbnail') or f"https://i.ytimg.com/vi/{v_id}/maxresdefault.jpg"
            
            availability = info.get('availability', '')
            is_member_availability = availability in ['subscriber_only', 'premium_only', 'needs_auth']
            title_keywords = ['【会员视频】', '【会员】', '[会员]', '(会员)', '[Members Only]', '(Members Only)', '会员专享', '会员限定', '会员专属', '频道会员', '充电专属']
            is_member_title = any(kw in title for kw in title_keywords)
            is_paid = is_member_availability or is_member_title
            pay_badge = "会员专属" if is_paid else ""

            return {
                "bvid": v_id,
                "id": v_id,
                "title": title,
                "channel": channel,
                "channel_id": channel_id,
                "channel_url": channel_url,
                "channel_avatar": "",
                "duration_seconds": duration,
                "duration_str": format_duration(duration),
                "upload_date": upload_date,
                "description": desc,
                "pic": thumbnail,
                "thumbnail": thumbnail,
                "url": video_url,
                "is_paid": is_paid,
                "disabled": is_paid,
                "pay_badge": pay_badge
            }

    def download_and_process_audio(
        self,
        video_data: dict,
        channel_name: str,
        channel_avatar_url: str = "",
        base_download_dir: Optional[str] = None,
        progress_cb: Optional[Callable[[str, float], None]] = None
    ) -> str:
        """Download YouTube audio with yt-dlp, embed Apple Podcasts metadata & artwork, and save to downloads/channel_name/."""
        target_download_dir = base_download_dir or self.download_dir
        ffmpeg_bin = get_ffmpeg_cmd()
        sanitized_channel = sanitize_filename(channel_name)
        channel_dir = os.path.join(target_download_dir, sanitized_channel)
        os.makedirs(channel_dir, exist_ok=True)

        v_id = video_data.get('id') or video_data.get('bvid')
        title = video_data.get('title', '未知标题')
        pic_url = video_data.get('pic') or video_data.get('thumbnail') or f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"
        desc = video_data.get('description', '')
        video_url = video_data.get('url') or f"https://www.youtube.com/watch?v={v_id}"

        # Ensure channel cover.jpg exists for Audiobookshelf
        if channel_avatar_url:
            ensure_album_cover(channel_name, channel_avatar_url, self.session, target_download_dir)
        elif pic_url and not os.path.exists(os.path.join(channel_dir, "cover.jpg")):
            # Fallback channel cover from video artwork
            ensure_album_cover(channel_name, pic_url, self.session, target_download_dir)

        filename = f"{sanitize_filename(title)}.m4a"
        final_filepath = os.path.join(channel_dir, filename)
        if os.path.exists(final_filepath):
            return final_filepath

        import uuid
        uid = uuid.uuid4().hex[:8]
        temp_dir = "/tmp/ytpods"
        os.makedirs(temp_dir, exist_ok=True)
        temp_raw_path = os.path.join(temp_dir, f"_temp_{v_id}_{uid}_raw.m4a")
        temp_out_path = os.path.join(temp_dir, f"_temp_{v_id}_{uid}_out.m4a")
        temp_meta_path = os.path.join(temp_dir, f"_temp_{v_id}_{uid}_meta.txt")

        try:
            # 1. Download best audio stream
            if progress_cb: progress_cb("正在通过 YouTube 高速流下载最高音质音频...", 0.2)
            
            def yt_dlp_hook(d):
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes') or 0
                    if total > 0 and progress_cb:
                        pct = 0.2 + 0.5 * (downloaded / total)
                        progress_cb(f"正在下载音频流 ({downloaded//1024} KB / {total//1024} KB)...", pct)

            ydl_opts = self._get_base_ydl_opts({
                'format': '140/ba[ext=m4a]/ba[acodec=aac]/bestaudio/best',
                'outtmpl': temp_raw_path,
                'progress_hooks': [yt_dlp_hook],
            })

            info_dict = None
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)

            if not os.path.exists(temp_raw_path):
                # Try finding any file starting with temp_raw_path prefix
                candidates = [f for f in os.listdir(temp_dir) if f.startswith(f"_temp_{v_id}_{uid}_raw")]
                if candidates:
                    temp_raw_path = os.path.join(temp_dir, candidates[0])
                else:
                    raise Exception("下载音频流未生成有效文件")

            # 2. FFmpeg remux & faststart
            if progress_cb: progress_cb("正在优化音频封装 (FFmpeg FastStart)...", 0.75)
            with open(temp_meta_path, "w", encoding="utf-8") as f:
                f.write(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=9999999999\ntitle=正文\n")

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

            # 3. Process Artwork
            if progress_cb: progress_cb("正在处理 Apple Podcasts 规范封面 (1400x1400)...", 0.85)
            ep_art_bytes = None
            if pic_url:
                try:
                    ep_art_bytes = process_artwork(pic_url, self.session, target_min=1400, target_max=2000)
                except Exception as e:
                    print(f"Error processing YouTube episode artwork: {e}")

            # 4. Extract accurate publication timestamp and date
            pub_timestamp = None
            if info_dict:
                pub_timestamp = info_dict.get('timestamp') or info_dict.get('release_timestamp')
                if not pub_timestamp and info_dict.get('upload_date'):
                    try:
                        u_date_str = str(info_dict.get('upload_date'))
                        if len(u_date_str) == 8:
                            dt = datetime.datetime.strptime(u_date_str, "%Y%m%d")
                            pub_timestamp = int(dt.timestamp())
                    except Exception:
                        pass

            if not pub_timestamp:
                u_date_str = str(video_data.get('upload_date') or '')
                if len(u_date_str) == 8:
                    try:
                        dt = datetime.datetime.strptime(u_date_str, "%Y%m%d")
                        pub_timestamp = int(dt.timestamp())
                    except Exception:
                        pass

            if pub_timestamp:
                date_str = time.strftime('%Y-%m-%d', time.localtime(pub_timestamp))
            elif video_data.get('upload_date') and len(str(video_data.get('upload_date'))) == 8:
                u_str = str(video_data.get('upload_date'))
                date_str = f"{u_str[:4]}-{u_str[4:6]}-{u_str[6:]}"
            else:
                date_str = time.strftime('%Y-%m-%d')

            # 5. Tag MP4 with Mutagen
            if progress_cb: progress_cb("正在写入播客元数据与章节标签...", 0.95)
            audio = MP4(temp_out_path)
            audio["\xa9nam"] = [title]
            audio["\xa9ART"] = [channel_name]
            audio["\xa9alb"] = [channel_name]
            audio["aART"] = [channel_name]
            audio["\xa9day"] = [date_str]
            audio["\xa9cmt"] = [f"{desc}\n\n原视频链接: {video_url}"]
            if ep_art_bytes:
                audio["covr"] = [MP4Cover(ep_art_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()

            # Move to final location
            if os.path.exists(final_filepath):
                os.remove(final_filepath)
            shutil.move(temp_out_path, final_filepath)

            # Set file mtime to actual publication time for correct chronological sorting & Audiobookshelf sync
            if pub_timestamp:
                try:
                    os.utime(final_filepath, (pub_timestamp, pub_timestamp))
                except Exception as e:
                    print(f"Failed to set utime for {final_filepath}: {e}")

            if progress_cb: progress_cb("YouTube 播客音频提取成功并入库！", 1.0)
            return final_filepath

        finally:
            for p in [temp_raw_path, temp_out_path, temp_meta_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
