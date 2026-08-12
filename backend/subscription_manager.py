import os
import json
import time
from typing import Dict, Any, List, Optional
from backend.audio_processor import process_audio_file, sanitize_filename
from backend.bilibili_client import BilibiliClient

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
        mid: int,
        up_name: str,
        up_avatar: str,
        min_duration_minutes: float = 0,
        keywords: Optional[List[str]] = None,
        auto_download: bool = True
    ) -> dict:
        key = str(mid)
        existing = self.subscriptions.get(key, {})
        downloaded_bvids = existing.get('downloaded_bvids', [])
        
        # Populate downloaded_bvids from existing downloads directory if present
        up_dir = os.path.join(self.download_dir, sanitize_filename(up_name))
        if os.path.exists(up_dir):
            for fname in os.listdir(up_dir):
                if fname.endswith(".m4a") and not fname.startswith("_temp_"):
                    # We can store downloaded files
                    pass

        sub = {
            "mid": mid,
            "up_name": up_name,
            "up_avatar": up_avatar,
            "enabled": auto_download,
            "min_duration_minutes": float(min_duration_minutes),
            "keywords": keywords or [],
            "last_check_time": int(time.time()),
            "downloaded_bvids": downloaded_bvids
        }
        self.subscriptions[key] = sub
        self.save()
        return sub

    def remove_subscription(self, mid: int) -> bool:
        key = str(mid)
        if key in self.subscriptions:
            del self.subscriptions[key]
            self.save()
            return True
        return False

    def get_subscription(self, mid: int) -> Optional[dict]:
        return self.subscriptions.get(str(mid))

    def list_subscriptions(self) -> List[dict]:
        return list(self.subscriptions.values())

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

        print(f"Checking subscription updates for UP: {up_name} (MID: {mid})...")
        
        # Fetch recent 30 videos
        videos_res = client.get_up_videos(mid, page=1, page_size=30)
        videos = videos_res.get('videos', [])
        
        downloaded_new = []
        for v in videos:
            bvid = v['bvid']
            title = v['title']
            desc = v.get('description', '')
            is_paid = v.get('is_paid') or v.get('disabled')

            # 1. Must be free video (non-member / non-paid)
            if is_paid:
                continue

            # 2. Must meet duration requirement
            if v.get('duration_seconds', 0) < min_seconds:
                continue

            # 3. Must match keywords if specified
            if keywords:
                title_desc = f"{title} {desc}".lower()
                if not any(k in title_desc for k in keywords):
                    continue

            # 4. Must not have been downloaded yet
            if bvid in downloaded_bvids:
                continue

            # Download & process new video audio
            try:
                print(f"New video found for {up_name}: [{bvid}] {title}")
                play_info = client.get_play_info(bvid)
                filepath = process_audio_file(
                    play_info,
                    up_name,
                    up_avatar,
                    client.session,
                    self.download_dir
                )
                downloaded_bvids.add(bvid)
                downloaded_new.append({"bvid": bvid, "title": title, "filepath": filepath})
            except Exception as e:
                print(f"Error downloading update for video {bvid}: {e}")

        # Update subscription record
        sub['downloaded_bvids'] = list(downloaded_bvids)
        sub['last_check_time'] = int(time.time())
        self.subscriptions[key] = sub
        self.save()

        return {
            "mid": mid,
            "up_name": up_name,
            "downloaded_count": len(downloaded_new),
            "new_episodes": downloaded_new
        }

    def check_all_subscriptions(self, client: BilibiliClient) -> List[dict]:
        results = []
        for key, sub in list(self.subscriptions.items()):
            if sub.get('enabled', True):
                try:
                    res = self.check_up_updates(sub['mid'], client)
                    results.append(res)
                except Exception as e:
                    print(f"Error checking subscription for MID {key}: {e}")
        return results
