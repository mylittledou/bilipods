import os
import json
import time
import re
from typing import Dict, Any, List, Optional
from mutagen.mp4 import MP4
from backend.audio_processor import process_audio_file, sanitize_filename, send_bark_summary
from backend.bilibili_client import BilibiliClient
from backend.youtube_client import YouTubeClient

class SubscriptionManager:
    def __init__(self, filepath: str = "subscriptions.json", download_dir: str = "downloads"):
        self.filepath = filepath
        self.download_dir = download_dir
        self.subscriptions: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    self.subscriptions = json.load(f)
            except Exception as e:
                print(f"Error loading subscriptions: {e}")
                self.subscriptions = {}

    def save(self):
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.subscriptions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving subscriptions: {e}")

    def add_subscription(
        self,
        mid: Any,
        up_name: str,
        up_avatar: str,
        min_duration_minutes: float = 0,
        keywords: Optional[List[str]] = None,
        auto_download: bool = True,
        ignore_bvids: Optional[List[str]] = None,
        keep_count: int = 0,
        platform: str = "bilibili",
        channel_url: str = ""
    ) -> dict:
        key = str(mid)
        if platform == "youtube" and not key.startswith("yt_"):
            key = f"yt_{key}"
            
        existing = self.subscriptions.get(key, {})
        downloaded_bvids = existing.get('downloaded_bvids', [])
        
        sub = {
            "mid": mid,
            "id": key,
            "platform": platform,
            "up_name": up_name,
            "channel_name": up_name,
            "up_avatar": up_avatar,
            "channel_url": channel_url,
            "enabled": auto_download,
            "min_duration_minutes": float(min_duration_minutes),
            "keywords": keywords or [],
            "keep_count": keep_count,
            "last_check_time": int(time.time()),
            "downloaded_bvids": downloaded_bvids
        }
        self.subscriptions[key] = sub
        self.save()
        return sub

    def update_subscription(
        self,
        mid: Any,
        min_duration_minutes: Optional[float] = None,
        keywords: Optional[List[str]] = None,
        keep_count: Optional[int] = None
    ) -> Optional[dict]:
        key = str(mid)
        if key not in self.subscriptions:
            # Try finding with yt_ prefix
            if f"yt_{key}" in self.subscriptions:
                key = f"yt_{key}"
            else:
                return None
            
        sub = self.subscriptions[key]
        if min_duration_minutes is not None:
            sub["min_duration_minutes"] = float(min_duration_minutes)
        if keywords is not None:
            sub["keywords"] = keywords
        if keep_count is not None:
            sub["keep_count"] = int(keep_count)
            
        self.subscriptions[key] = sub
        self.save()
        
        # Immediately trigger cleanup if keep_count was reduced
        if keep_count is not None and keep_count > 0:
            self.cleanup_old_audios(sub['up_name'], keep_count)
            
        return sub

    def remove_subscription(self, mid: Any) -> bool:
        key = str(mid)
        if key in self.subscriptions:
            del self.subscriptions[key]
            self.save()
            return True
        if f"yt_{key}" in self.subscriptions:
            del self.subscriptions[f"yt_{key}"]
            self.save()
            return True
        return False

    def get_subscription(self, mid: Any) -> Optional[dict]:
        key = str(mid)
        return self.subscriptions.get(key) or self.subscriptions.get(f"yt_{key}")

    def list_subscriptions(self) -> List[dict]:
        subs = list(self.subscriptions.values())
        for sub in subs:
            up_dir = os.path.join(self.download_dir, sanitize_filename(sub.get("up_name", "")))
            actual_count = 0
            if os.path.exists(up_dir):
                actual_count = len([f for f in os.listdir(up_dir) if f.endswith(".m4a") and not f.startswith("_temp_")])
            sub["downloaded_count"] = actual_count
            if "platform" not in sub:
                sub["platform"] = "bilibili"
        return subs

    def check_up_updates(self, mid: int, client: BilibiliClient) -> dict:
        key = str(mid)
        sub = self.subscriptions.get(key)
        if not sub or not sub.get('enabled', True):
            return {"mid": mid, "downloaded_count": 0, "message": "订阅已禁用或不存在"}

        up_name = sub['up_name']
        up_avatar = sub.get('up_avatar', '')
        min_seconds = sub.get('min_duration_minutes', 0) * 60
        keywords = [k.strip().lower() for k in sub.get('keywords', []) if k.strip()]
        downloaded_bvids = set(sub.get('downloaded_bvids', []))

        up_dir = os.path.join(self.download_dir, sanitize_filename(up_name))
        os.makedirs(up_dir, exist_ok=True)

        local_files = [f for f in os.listdir(up_dir) if f.endswith(".m4a") and not f.startswith("_temp_")]
        existing_local_filenames = set(local_files)

        keep_count = sub.get('keep_count', 0)
        max_target = keep_count if keep_count > 0 else 50

        # Collect existing normalized titles AND embedded BVIDs from local files
        local_norm_titles = set()
        local_bvids = set()
        for f in local_files:
            fpath = os.path.join(up_dir, f)
            try:
                m = MP4(fpath)
                cmt = m.get('\xa9cmt', [''])[0]
                if 'bilibili.com/video/' in cmt:
                    bvid_in_f = cmt.split('bilibili.com/video/')[1].split()[0].split('?')[0]
                    local_bvids.add(bvid_in_f)
            except Exception:
                pass
            norm_t = re.sub(r'[\s_|\｜\?？\(\)（）\-\—]+', '', f.replace('.m4a', '')).lower()
            local_norm_titles.add(norm_t)

        page = 1
        to_download = []
        valid_bili_videos = []
        
        while True:
            try:
                videos_res = client.get_up_videos(mid, page=page, page_size=50)
                vlist = videos_res.get('videos', [])
                if not vlist:
                    break
                
                for v in vlist:
                    if v.get('is_paid') or v.get('disabled'):
                        continue
                    if v.get('duration_seconds', 0) < min_seconds:
                        continue
                    if keywords:
                        title_desc = f"{v.get('title', '')} {v.get('description', '')}".lower()
                        if not any(k in title_desc for k in keywords):
                            continue

                    valid_bili_videos.append(v)
                    bvid = v['bvid']
                    title = v['title']
                    expected_filename = f"{sanitize_filename(title)}.m4a"
                    norm_v_title = re.sub(r'[\s_|\｜\?？\(\)（）\-\—]+', '', sanitize_filename(title)).lower()
                    
                    is_on_disk = (bvid in local_bvids) or (expected_filename in existing_local_filenames) or (norm_v_title in local_norm_titles)
                    if is_on_disk or (bvid in downloaded_bvids):
                        downloaded_bvids.add(bvid)
                    else:
                        to_download.append(v)

                    if len(valid_bili_videos) >= max_target:
                        break

                if len(valid_bili_videos) >= max_target:
                    break

                total_on_bili = videos_res.get('total', 0)
                if page * 50 >= total_on_bili:
                    break

                page += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"Error fetching page {page} for UP {up_name}: {e}")
                break

        downloaded_new = []
        for v in to_download:
            bvid = v['bvid']
            title = v['title']
            try:
                print(f"Downloading video for {up_name}: [{bvid}] {title}")
                play_info = client.get_play_info(bvid)
                filepath = process_audio_file(
                    play_info,
                    up_name,
                    up_avatar,
                    client.session,
                    self.download_dir
                )
                downloaded_bvids.add(bvid)
                existing_local_filenames.add(os.path.basename(filepath))
                downloaded_new.append({"bvid": bvid, "title": title, "filepath": filepath})
                time.sleep(0.5)
            except Exception as e:
                print(f"Error downloading update for video {bvid}: {e}")

        # Update subscription record
        sub['downloaded_bvids'] = list(downloaded_bvids)
        sub['last_check_time'] = int(time.time())
        self.subscriptions[key] = sub
        self.save()
        
        # Enforce retention policy
        if keep_count > 0:
            self.cleanup_old_audios(up_name, keep_count)

        # Send Bark summary (only for files that remain on disk after retention cleanup)
        downloaded_new = [ep for ep in downloaded_new if os.path.exists(ep['filepath'])]
        if downloaded_new:
            send_bark_summary(up_name, up_avatar, downloaded_new, platform="bilibili")

        return {
            "mid": mid,
            "up_name": up_name,
            "downloaded_count": len(downloaded_new),
            "new_episodes": downloaded_new
        }

    def check_youtube_updates(self, sub_key: str, client: YouTubeClient) -> dict:
        key = str(sub_key)
        if not key.startswith("yt_") and key not in self.subscriptions and f"yt_{key}" in self.subscriptions:
            key = f"yt_{key}"

        sub = self.subscriptions.get(key)
        if not sub or not sub.get('enabled', True):
            return {"id": sub_key, "downloaded_count": 0, "message": "订阅已禁用或不存在"}

        channel_name = sub.get('up_name') or sub.get('channel_name', 'YouTube')
        channel_avatar = sub.get('up_avatar', '')
        channel_url = sub.get('channel_url') or sub.get('mid') or key.replace('yt_', '')
        min_seconds = sub.get('min_duration_minutes', 0) * 60
        keywords = [k.strip().lower() for k in sub.get('keywords', []) if k.strip()]
        downloaded_bvids = set(sub.get('downloaded_bvids', []))

        channel_dir = os.path.join(self.download_dir, sanitize_filename(channel_name))
        os.makedirs(channel_dir, exist_ok=True)

        local_files = [f for f in os.listdir(channel_dir) if f.endswith(".m4a") and not f.startswith("_temp_")]
        existing_local_filenames = set(local_files)

        keep_count = sub.get('keep_count', 0)
        max_target = keep_count if keep_count > 0 else 30

        # Collect existing video IDs and titles from local files
        local_norm_titles = set()
        local_ids = set()
        for f in local_files:
            fpath = os.path.join(channel_dir, f)
            try:
                m = MP4(fpath)
                cmt = m.get('\xa9cmt', [''])[0]
                if 'youtube.com/watch?v=' in cmt:
                    vid = cmt.split('youtube.com/watch?v=')[1].split()[0].split('&')[0].split('?')[0]
                    local_ids.add(vid)
                elif 'youtu.be/' in cmt:
                    vid = cmt.split('youtu.be/')[1].split()[0].split('&')[0].split('?')[0]
                    local_ids.add(vid)
            except Exception:
                pass
            norm_t = re.sub(r'[\s_|\｜\?？\(\)（）\-\—]+', '', f.replace('.m4a', '')).lower()
            local_norm_titles.add(norm_t)

        try:
            parsed_res = client.search_or_parse(channel_url, max_results=max_target)
            vlist = parsed_res.get('videos', [])
        except Exception as e:
            print(f"Error fetching YouTube channel {channel_name}: {e}")
            return {"id": sub_key, "downloaded_count": 0, "message": f"拉取失败: {e}"}

        to_download = []
        for v in vlist:
            if v.get('is_paid') or v.get('disabled'):
                continue
            v_id = v['id']
            title = v['title']
            dur = v.get('duration_seconds', 0)
            if dur and dur < min_seconds:
                continue
            if keywords:
                title_lower = title.lower()
                if not any(k in title_lower for k in keywords):
                    continue

            expected_filename = f"{sanitize_filename(title)}.m4a"
            norm_v_title = re.sub(r'[\s_|\｜\?？\(\)（）\-\—]+', '', sanitize_filename(title)).lower()

            is_on_disk = (v_id in local_ids) or (expected_filename in existing_local_filenames) or (norm_v_title in local_norm_titles)
            if is_on_disk or (v_id in downloaded_bvids):
                downloaded_bvids.add(v_id)
            else:
                to_download.append(v)

            if len(to_download) >= max_target:
                break

        downloaded_new = []
        for v in to_download:
            v_id = v['id']
            title = v['title']
            try:
                print(f"Downloading YouTube video for {channel_name}: [{v_id}] {title}")
                filepath = client.download_and_process_audio(
                    video_data=v,
                    channel_name=channel_name,
                    channel_avatar_url=channel_avatar,
                    base_download_dir=self.download_dir
                )
                downloaded_bvids.add(v_id)
                existing_local_filenames.add(os.path.basename(filepath))
                downloaded_new.append({"id": v_id, "bvid": v_id, "title": title, "filepath": filepath})
                time.sleep(0.5)
            except Exception as e:
                print(f"Error downloading YouTube video {v_id}: {e}")

        # Update subscription record
        sub['downloaded_bvids'] = list(downloaded_bvids)
        sub['last_check_time'] = int(time.time())
        self.subscriptions[key] = sub
        self.save()

        # Enforce retention policy
        if keep_count > 0:
            self.cleanup_old_audios(channel_name, keep_count)

        # Send Bark summary (only for files that remain on disk after retention cleanup)
        downloaded_new = [ep for ep in downloaded_new if os.path.exists(ep['filepath'])]
        if downloaded_new:
            send_bark_summary(channel_name, channel_avatar, downloaded_new, platform="youtube")

        return {
            "id": sub_key,
            "channel_name": channel_name,
            "downloaded_count": len(downloaded_new),
            "new_episodes": downloaded_new
        }

    def check_all_subscriptions(self, bili_client: BilibiliClient, yt_client: Optional[YouTubeClient] = None) -> List[dict]:
        results = []
        for key, sub in list(self.subscriptions.items()):
            if sub.get('enabled', True):
                platform = sub.get('platform', 'bilibili')
                try:
                    if platform == "youtube" and yt_client:
                        res = self.check_youtube_updates(key, yt_client)
                        results.append(res)
                    else:
                        res = self.check_up_updates(int(sub.get('mid', key)), bili_client)
                        results.append(res)
                except Exception as e:
                    print(f"Error checking subscription for {key} [{platform}]: {e}")
        return results

    def cleanup_old_audios(self, up_name: str, keep_count: int):
        if keep_count <= 0:
            return
        
        up_dir = os.path.join(self.download_dir, sanitize_filename(up_name))
        if not os.path.exists(up_dir):
            return
            
        # 1. Deduplicate files (by ID and normalized title)
        id_map = {}
        title_map = {}
        all_files = [f for f in os.listdir(up_dir) if f.endswith(".m4a") and not f.startswith("_temp_")]
        
        for fname in all_files:
            fpath = os.path.join(up_dir, fname)
            if not os.path.isfile(fpath):
                continue
            item_id = None
            try:
                m = MP4(fpath)
                cmt = m.get('\xa9cmt', [''])[0]
                if 'bilibili.com/video/' in cmt:
                    item_id = cmt.split('bilibili.com/video/')[1].split()[0].split('?')[0]
                elif 'youtube.com/watch?v=' in cmt:
                    item_id = cmt.split('youtube.com/watch?v=')[1].split()[0].split('&')[0].split('?')[0]
                elif 'youtu.be/' in cmt:
                    item_id = cmt.split('youtu.be/')[1].split()[0].split('&')[0].split('?')[0]
            except Exception:
                pass
                
            norm_title = re.sub(r'[\s_|\｜\?？\(\)（）\-\—]+', '', fname.replace('.m4a', '')).lower()
            
            # Deduplicate by video ID
            if item_id:
                if item_id in id_map:
                    prev_name, prev_path = id_map[item_id]
                    if os.path.exists(prev_path) and os.path.exists(fpath):
                        to_del = fpath if '_' in fname and '_' not in prev_name else prev_path
                        try:
                            os.remove(to_del)
                            print(f"Cleanup: Removed duplicate audio {to_del}")
                        except Exception:
                            pass
                        if to_del == prev_path:
                            id_map[item_id] = (fname, fpath)
                        continue
                else:
                    id_map[item_id] = (fname, fpath)
                    
            # Deduplicate by title
            if norm_title in title_map:
                prev_name, prev_path = title_map[norm_title]
                if os.path.exists(prev_path) and os.path.exists(fpath):
                    to_del = fpath if '_' in fname and '_' not in prev_name else prev_path
                    try:
                        os.remove(to_del)
                        print(f"Cleanup: Removed duplicate audio {to_del}")
                    except Exception:
                        pass
                    if to_del == prev_path:
                        title_map[norm_title] = (fname, fpath)
            else:
                title_map[norm_title] = (fname, fpath)

        # 2. Trim retention after deduplication
        files = []
        for fname in os.listdir(up_dir):
            if fname.endswith(".m4a") and not fname.startswith("_temp_"):
                fpath = os.path.join(up_dir, fname)
                if os.path.isfile(fpath):
                    files.append((fpath, os.path.getmtime(fpath)))
                    
        if len(files) > keep_count:
            # Sort by mtime descending (newest first)
            files.sort(key=lambda x: x[1], reverse=True)
            files_to_delete = files[keep_count:]
            for fpath, _ in files_to_delete:
                try:
                    os.remove(fpath)
                    print(f"Cleanup: Removed old audio {fpath}")
                except Exception as e:
                    print(f"Error removing {fpath}: {e}")
