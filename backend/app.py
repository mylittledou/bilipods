import os
import io
import json
import asyncio
import xml.etree.ElementTree as ET
import urllib.parse
import requests
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from mutagen.mp4 import MP4

from backend.bilibili_client import BilibiliClient
from backend.youtube_client import YouTubeClient
from backend.audio_processor import process_audio_file, sanitize_filename, ensure_album_cover, send_bark_summary
from backend.rss_generator import generate_podcast_rss
from backend.subscription_manager import SubscriptionManager

app = FastAPI(title="BiliPods & YTPods", version="2.0.0")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.json")
YT_COOKIE_FILE = os.path.join(BASE_DIR, "data", "youtube_cookies.txt")
SUBSCRIPTION_FILE = os.path.join(BASE_DIR, "subscriptions.json")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
os.makedirs(FRONTEND_DIR, exist_ok=True)

bilibili_client = BilibiliClient(cookie_file=COOKIE_FILE)
youtube_client = YouTubeClient(cookie_file=YT_COOKIE_FILE, download_dir=DOWNLOAD_DIR)
subscription_mgr = SubscriptionManager(filepath=SUBSCRIPTION_FILE, download_dir=DOWNLOAD_DIR)

# Global download progress store for SSE
download_events = []
current_download_task = None

class DownloadRequest(BaseModel):
    mid: int
    bvid_list: List[str]

class YouTubeSearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = None

class YouTubeDownloadRequest(BaseModel):
    channel_name: str
    channel_avatar: Optional[str] = ""
    videos: List[Dict[str, Any]]

class YouTubeSubscriptionRequest(BaseModel):
    channel_id: str
    channel_name: str
    channel_avatar: Optional[str] = ""
    channel_url: Optional[str] = ""
    min_duration_minutes: float = 0.0
    keywords: Optional[List[str]] = []
    auto_download: bool = True
    keep_count: int = 0

class YouTubeCookieRequest(BaseModel):
    cookie_string: str

class SubscriptionRequest(BaseModel):
    mid: Any
    up_name: str
    up_avatar: Optional[str] = ""
    channel_url: Optional[str] = ""
    platform: Optional[str] = "bilibili"
    min_duration_minutes: float = 0.0
    keywords: Optional[List[str]] = []
    auto_download: bool = True
    ignore_bvids: Optional[List[str]] = []
    keep_count: int = 0

class SubscriptionUpdateRequest(BaseModel):
    min_duration_minutes: Optional[float] = None
    keywords: Optional[List[str]] = None
    keep_count: Optional[int] = None

class DeleteFilesRequest(BaseModel):
    filenames: List[str]

class CookieLoginRequest(BaseModel):
    cookie_string: str

async def background_subscription_checker():
    """Periodically check all subscribed UP hosts and YouTube channels every 15 minutes"""
    CHECK_INTERVAL_SECONDS = 15 * 60
    await asyncio.sleep(10)
    while True:
        try:
            print("[Scheduler] Running periodic check for subscribed hosts (every 15m)...")
            await asyncio.to_thread(subscription_mgr.check_all_subscriptions, bilibili_client, youtube_client)
            print("[Scheduler] Check completed. Next check in 15 minutes.")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        except Exception as e:
            print(f"[Scheduler] Error in periodic check: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_subscription_checker())

# ----------------- Bilibili Auth & Search Endpoints -----------------

@app.get("/api/auth/qrcode")
def get_qr_code():
    try:
        return bilibili_client.get_qr_code()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/auth/poll")
def poll_qr_code(qrcode_key: str):
    try:
        return bilibili_client.poll_qr_code(qrcode_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/auth/status")
def get_auth_status():
    return bilibili_client.get_login_user_info()

@app.post("/api/auth/cookie")
def login_with_cookie(req: CookieLoginRequest):
    if not req.cookie_string:
        raise HTTPException(status_code=400, detail="Cookie不能为空")
    bilibili_client.set_cookies_from_string(req.cookie_string)
    user_info = bilibili_client.get_login_user_info()
    if user_info and user_info.get("is_login"):
        return user_info
    else:
        raise HTTPException(status_code=401, detail="Cookie无效或已过期")

@app.post("/api/auth/logout")
def logout():
    bilibili_client.session.cookies.clear()
    bilibili_client.save_cookies()
    return {"code": 0, "message": "Logged out"}

@app.get("/api/up/search")
def search_up(query: str):
    mid = BilibiliClient.parse_mid(query)
    if not mid:
        raise HTTPException(status_code=400, detail="无法从输入中解析出有效的 UP 主数字 ID 或主页链接")
    try:
        up_info = bilibili_client.get_up_info(mid)
        videos_res = bilibili_client.get_all_up_videos(mid)
        return {
            "up_info": up_info,
            "videos": videos_res["videos"],
            "total": videos_res["total"],
            "page": videos_res["page"],
            "page_size": videos_res["page_size"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取 UP 主信息失败: {str(e)}")

@app.get("/api/up/videos")
def get_up_videos(mid: int):
    try:
        return bilibili_client.get_all_up_videos(mid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取视频列表失败: {str(e)}")

@app.get("/api/up/followings")
def get_followings():
    user_info = bilibili_client.get_login_user_info()
    if not user_info or not user_info.get("is_login"):
        raise HTTPException(status_code=401, detail="未登录，无法获取关注列表")
    try:
        all_list = bilibili_client.get_all_followings(user_info["mid"])
        return {"status": "ok", "data": {"list": all_list, "total": len(all_list)}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- YouTube Endpoints -----------------

@app.post("/api/youtube/search")
def search_youtube(req: YouTubeSearchRequest):
    if not req.query:
        raise HTTPException(status_code=400, detail="请输入 YouTube 链接或搜索词")
    try:
        result = youtube_client.search_or_parse(req.query, max_results=req.max_results)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析 YouTube 失败: {str(e)}")

@app.get("/api/youtube/channels")
def get_youtube_user_channels():
    try:
        channels = youtube_client.get_user_subscriptions()
        return {"status": "ok", "data": {"list": channels, "total": len(channels)}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/youtube/auth/status")
def get_youtube_auth_status():
    return youtube_client.get_auth_status()

@app.post("/api/youtube/cookie")
def set_youtube_cookies(req: YouTubeCookieRequest):
    try:
        youtube_client.save_cookies(req.cookie_string)
        return {"status": "ok", "message": "YouTube Cookie 保存成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存 YouTube Cookie 失败: {str(e)}")

@app.delete("/api/youtube/cookie")
def clear_youtube_cookies():
    try:
        youtube_client.save_cookies("")
        return {"status": "ok", "message": "YouTube Cookie 已清空"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空 YouTube Cookie 失败: {str(e)}")

# ----------------- Download Batches & SSE Progress -----------------

async def run_bilibili_download_batch(mid: int, bvid_list: List[str]):
    global download_events
    download_events = []
    
    try:
        up_info = bilibili_client.get_up_info(mid)
        up_name = up_info['name']
        up_avatar = up_info['face']
    except Exception as e:
        download_events.append(json.dumps({"type": "error", "message": f"获取 UP 主 {mid} 信息失败: {e}"}))
        return

    total = len(bvid_list)
    download_events.append(json.dumps({
        "type": "start",
        "message": f"开始提取 UP 主【{up_name}】的 {total} 个视频音频...",
        "total": total
    }))

    for index, bvid in enumerate(bvid_list, 1):
        try:
            download_events.append(json.dumps({
                "type": "item_start",
                "index": index,
                "total": total,
                "bvid": bvid,
                "message": f"[{index}/{total}] 正在解析视频 {bvid}..."
            }))
            
            play_info = bilibili_client.get_play_info(bvid)
            
            def progress_cb(msg: str, pct: float):
                download_events.append(json.dumps({
                    "type": "item_progress",
                    "index": index,
                    "total": total,
                    "bvid": bvid,
                    "title": play_info['title'],
                    "message": msg,
                    "percent": round(pct * 100, 1)
                }))

            filepath = await asyncio.to_thread(
                process_audio_file,
                play_info,
                up_name,
                up_avatar,
                bilibili_client.session,
                DOWNLOAD_DIR,
                progress_cb
            )

            download_events.append(json.dumps({
                "type": "item_complete",
                "index": index,
                "total": total,
                "bvid": bvid,
                "title": play_info['title'],
                "filepath": filepath,
                "message": f"[{index}/{total}] 音频成功处理并保存: {os.path.basename(filepath)}"
            }))

        except Exception as e:
            download_events.append(json.dumps({
                "type": "item_error",
                "index": index,
                "total": total,
                "bvid": bvid,
                "message": f"[{index}/{total}] 处理视频 {bvid} 失败: {str(e)}"
            }))

    download_events.append(json.dumps({
        "type": "finish",
        "message": f"所有 {total} 个视频音频处理完毕！可添加至 Audiobookshelf 或使用 Apple Podcasts 订阅。",
        "up_name": up_name,
        "mid": mid
    }))

async def run_youtube_download_batch(channel_name: str, channel_avatar: str, video_list: List[Dict[str, Any]]):
    global download_events
    download_events = []

    total = len(video_list)
    download_events.append(json.dumps({
        "type": "start",
        "message": f"开始提取 YouTube 频道【{channel_name}】的 {total} 个视频音频...",
        "total": total
    }))

    for index, v in enumerate(video_list, 1):
        v_id = v.get('id') or v.get('bvid')
        v_title = v.get('title', '未知标题')
        try:
            download_events.append(json.dumps({
                "type": "item_start",
                "index": index,
                "total": total,
                "bvid": v_id,
                "message": f"[{index}/{total}] 正在提取 YouTube 视频: {v_title}..."
            }))

            def yt_progress_cb(msg: str, pct: float):
                download_events.append(json.dumps({
                    "type": "item_progress",
                    "index": index,
                    "total": total,
                    "bvid": v_id,
                    "title": v_title,
                    "message": msg,
                    "percent": round(pct * 100, 1)
                }))

            filepath = await asyncio.to_thread(
                youtube_client.download_and_process_audio,
                v,
                channel_name,
                channel_avatar,
                DOWNLOAD_DIR,
                yt_progress_cb
            )

            download_events.append(json.dumps({
                "type": "item_complete",
                "index": index,
                "total": total,
                "bvid": v_id,
                "title": v_title,
                "filepath": filepath,
                "message": f"[{index}/{total}] 音频成功处理并保存: {os.path.basename(filepath)}"
            }))

        except Exception as e:
            download_events.append(json.dumps({
                "type": "item_error",
                "index": index,
                "total": total,
                "bvid": v_id,
                "message": f"[{index}/{total}] 处理视频 {v_id} 失败: {str(e)}"
            }))

    download_events.append(json.dumps({
        "type": "finish",
        "message": f"所有 {total} 个 YouTube 播客音频处理完毕！已自动入库 Audiobookshelf。",
        "up_name": channel_name,
        "mid": channel_name
    }))

@app.post("/api/download")
async def start_download(req: DownloadRequest):
    global current_download_task
    if not req.bvid_list:
        raise HTTPException(status_code=400, detail="未选择任何视频")
    
    current_download_task = asyncio.create_task(run_bilibili_download_batch(req.mid, req.bvid_list))
    return {"status": "ok", "message": f"包含 {len(req.bvid_list)} 个视频的下载任务已启动"}

@app.post("/api/youtube/download")
async def start_youtube_download(req: YouTubeDownloadRequest):
    global current_download_task
    if not req.videos:
        raise HTTPException(status_code=400, detail="未选择任何 YouTube 视频")

    current_download_task = asyncio.create_task(
        run_youtube_download_batch(req.channel_name, req.channel_avatar or "", req.videos)
    )
    return {"status": "ok", "message": f"包含 {len(req.videos)} 个 YouTube 视频的下载任务已启动"}

@app.get("/api/download/progress")
async def download_progress():
    async def event_generator():
        last_index = 0
        while True:
            while last_index < len(download_events):
                data = download_events[last_index]
                last_index += 1
                yield f"data: {data}\n\n"
                
            if current_download_task and current_download_task.done():
                if last_index >= len(download_events):
                    break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ----------------- RSS & Artwork Endpoints -----------------

@app.get("/rss/{mid_or_name}")
def get_rss(
    mid_or_name: str, 
    request: Request,
    type: Optional[str] = None,
    order: Optional[str] = None
):
    mid = BilibiliClient.parse_mid(mid_or_name)
    up_name = mid_or_name
    
    if mid:
        try:
            info = bilibili_client.get_up_info(mid)
            up_name = info['name']
        except Exception:
            pass
            
    server_base_url = str(request.base_url).rstrip('/')
    pod_type = type if type in ["serial", "episodic"] else "episodic"
    pod_order = order if order in ["asc", "desc"] else "desc"
    
    rss_xml = generate_podcast_rss(
        up_name=up_name,
        mid=mid or 0,
        base_download_dir=DOWNLOAD_DIR,
        server_base_url=server_base_url,
        podcast_type=pod_type,
        order=pod_order
    )
    return Response(content=rss_xml, media_type="application/xml")

@app.api_route("/api/artwork/{up_name}/cover.jpg", methods=["GET", "HEAD"])
def get_channel_artwork(up_name: str):
    avatar_url = None
    for sub in subscription_mgr.subscriptions.values():
        if sub.get('up_name') == up_name or sub.get('channel_name') == up_name:
            avatar_url = sub.get('up_avatar')
            break
            
    if avatar_url:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            if 'bilibili.com' in avatar_url or 'hdslb.com' in avatar_url:
                headers['Referer'] = 'https://space.bilibili.com/'
            resp = requests.get(avatar_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                return Response(content=resp.content, media_type=content_type)
        except Exception as e:
            print(f"Failed to fetch avatar for {up_name}: {e}")

    # Fallback to local cover.jpg or embedded cover
    dir_path = os.path.join(DOWNLOAD_DIR, sanitize_filename(up_name))
    cover_file = os.path.join(dir_path, "cover.jpg")
    if os.path.exists(cover_file):
        with open(cover_file, 'rb') as f:
            return Response(content=f.read(), media_type="image/jpeg")

    if os.path.exists(dir_path):
        m4a_files = [f for f in os.listdir(dir_path) if f.endswith(".m4a")]
        if m4a_files:
            m4a_files.sort(key=lambda x: os.path.getmtime(os.path.join(dir_path, x)), reverse=True)
            for filename in m4a_files:
                filepath = os.path.join(dir_path, filename)
                try:
                    m4a = MP4(filepath)
                    covers = m4a.get("covr")
                    if covers:
                        art_data = bytes(covers[0])
                        content_type = "image/png" if art_data.startswith(b'\x89PNG') else "image/jpeg"
                        return Response(content=art_data, media_type=content_type)
                except Exception:
                    continue
            
    raise HTTPException(status_code=404, detail="未找到封面图片")

@app.api_route("/api/artwork/{up_name}/{filename}/cover.jpg", methods=["GET", "HEAD"])
def get_embedded_artwork(up_name: str, filename: str):
    filepath = os.path.join(DOWNLOAD_DIR, sanitize_filename(up_name), filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="音频文件不存在")
    try:
        m4a = MP4(filepath)
        covers = m4a.get("covr")
        if covers:
            art_data = bytes(covers[0])
            content_type = "image/png" if art_data.startswith(b'\x89PNG') else "image/jpeg"
            return Response(content=art_data, media_type=content_type)
    except Exception as e:
        print(f"Error extracting artwork from {filepath}: {e}")
    raise HTTPException(status_code=404, detail="未找到封面图片")

# ----------------- Subscriptions Management Endpoints -----------------

@app.get("/api/subscriptions")
def get_subscriptions():
    return subscription_mgr.list_subscriptions()

@app.post("/api/subscriptions")
def add_subscription(req: SubscriptionRequest):
    sub = subscription_mgr.add_subscription(
        mid=req.mid,
        up_name=req.up_name,
        up_avatar=req.up_avatar or "",
        channel_url=req.channel_url or "",
        platform=req.platform or "bilibili",
        min_duration_minutes=req.min_duration_minutes,
        keywords=req.keywords,
        auto_download=req.auto_download,
        ignore_bvids=req.ignore_bvids,
        keep_count=req.keep_count
    )
    return {"status": "ok", "subscription": sub}

@app.post("/api/subscriptions/{mid}/update")
def update_subscription(mid: str, req: SubscriptionUpdateRequest):
    sub = subscription_mgr.update_subscription(
        mid=mid,
        min_duration_minutes=req.min_duration_minutes,
        keywords=req.keywords,
        keep_count=req.keep_count
    )
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
        
    # Trigger background check immediately
    platform = sub.get("platform", "bilibili")
    if platform == "youtube":
        asyncio.create_task(asyncio.to_thread(subscription_mgr.check_youtube_updates, mid, youtube_client))
    else:
        asyncio.create_task(asyncio.to_thread(subscription_mgr.check_up_updates, int(sub.get('mid', mid)), bilibili_client))
    return {"status": "ok", "subscription": sub}

@app.post("/api/subscriptions/{mid}/cover")
def regenerate_album_cover(mid: str):
    sub = subscription_mgr.get_subscription(mid)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    up_avatar = sub.get('up_avatar')
    platform = sub.get('platform', 'bilibili')
    
    if not up_avatar and platform == "bilibili":
        try:
            up_info = bilibili_client.get_up_info(int(sub.get('mid', mid)))
            up_avatar = up_info.get('face', '')
            if up_avatar:
                sub['up_avatar'] = up_avatar
                subscription_mgr.save()
        except Exception:
            pass

    if not up_avatar:
        raise HTTPException(status_code=400, detail="Cannot find channel avatar")
        
    session = youtube_client.session if platform == "youtube" else bilibili_client.session
    success = ensure_album_cover(sub['up_name'], up_avatar, session, DOWNLOAD_DIR)
    if success:
        return {"code": 0, "message": "Cover generated successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to generate cover")

@app.delete("/api/subscriptions/{mid}")
def delete_subscription(mid: str):
    sub = subscription_mgr.get_subscription(mid)
    success = subscription_mgr.remove_subscription(mid)
    if not success:
        raise HTTPException(status_code=404, detail="订阅不存在")
        
    import shutil
    if sub and "up_name" in sub:
        up_dir = os.path.join(DOWNLOAD_DIR, sanitize_filename(sub["up_name"]))
        if os.path.exists(up_dir):
            try:
                shutil.rmtree(up_dir)
            except Exception as e:
                print(f"Failed to delete directory {up_dir}: {e}")
                
    return {"status": "ok", "message": f"订阅 {mid} 已取消，本地文件已清理"}

@app.post("/api/subscriptions/check")
async def check_subscriptions_now(mid: Optional[str] = None):
    if mid:
        sub = subscription_mgr.get_subscription(mid)
        if not sub:
            raise HTTPException(status_code=404, detail="订阅不存在")
        if sub.get('platform') == "youtube":
            res = await asyncio.to_thread(subscription_mgr.check_youtube_updates, mid, youtube_client)
        else:
            res = await asyncio.to_thread(subscription_mgr.check_up_updates, int(sub.get('mid', mid)), bilibili_client)
        return {"status": "ok", "results": [res]}
    else:
        results = await asyncio.to_thread(subscription_mgr.check_all_subscriptions, bilibili_client, youtube_client)
        return {"status": "ok", "results": results}

@app.get("/api/subscriptions/{mid}/files")
def get_subscription_files(mid: str):
    sub = subscription_mgr.get_subscription(mid)
    if not sub or not sub.get("up_name"):
        raise HTTPException(status_code=404, detail="订阅不存在")
    
    up_dir = os.path.join(DOWNLOAD_DIR, sanitize_filename(sub["up_name"]))
    if not os.path.exists(up_dir):
        return {"status": "ok", "files": []}
        
    files = []
    for fname in os.listdir(up_dir):
        if fname.endswith(".m4a") and not fname.startswith("_temp_"):
            filepath = os.path.join(up_dir, fname)
            stat = os.stat(filepath)
            files.append({
                "filename": fname,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "mtime": stat.st_mtime
            })
            
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return {"status": "ok", "files": files}

@app.post("/api/subscriptions/{mid}/files/delete")
def delete_subscription_files(mid: str, req: DeleteFilesRequest):
    sub = subscription_mgr.get_subscription(mid)
    if not sub or not sub.get("up_name"):
        raise HTTPException(status_code=404, detail="订阅不存在")
        
    up_dir = os.path.join(DOWNLOAD_DIR, sanitize_filename(sub["up_name"]))
    deleted_count = 0
    errors = []
    downloaded_bvids = set(sub.get("downloaded_bvids", []))
    bvids_updated = False
    
    for fname in req.filenames:
        if not fname.endswith(".m4a") or ".." in fname or "/" in fname or "\\" in fname:
            continue
            
        filepath = os.path.join(up_dir, fname)
        if os.path.exists(filepath):
            try:
                try:
                    m = MP4(filepath)
                    cmt = m.get("\xa9cmt", [""])[0]
                    item_id = None
                    if "bilibili.com/video/" in cmt:
                        item_id = cmt.split("bilibili.com/video/")[1].split()[0].split("?")[0]
                    elif "youtube.com/watch?v=" in cmt:
                        item_id = cmt.split("youtube.com/watch?v=")[1].split()[0].split("&")[0].split("?")[0]
                    elif "youtu.be/" in cmt:
                        item_id = cmt.split("youtu.be/")[1].split()[0].split("&")[0].split("?")[0]
                    if item_id and item_id not in downloaded_bvids:
                        downloaded_bvids.add(item_id)
                        bvids_updated = True
                except Exception:
                    pass
                os.remove(filepath)
                deleted_count += 1
            except Exception as e:
                errors.append(f"删除 {fname} 失败: {str(e)}")

    if bvids_updated:
        sub["downloaded_bvids"] = list(downloaded_bvids)
        subscription_mgr.save()
                
    return {
        "status": "ok", 
        "deleted_count": deleted_count, 
        "errors": errors
    }

@app.get("/api/proxy_img")
def proxy_img(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="Invalid image URL")
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[7:]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    if 'bilibili.com' in url or 'hdslb.com' in url:
        headers['Referer'] = 'https://www.bilibili.com'
    elif 'youtube.com' in url or 'ytimg.com' in url or 'ggpht.com' in url:
        headers['Referer'] = 'https://www.youtube.com'

    try:
        resp = youtube_client.session.get(url, headers=headers, timeout=6)
        content_type = resp.headers.get('content-type', 'image/jpeg')
        return Response(content=resp.content, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount downloads directory for static audio & cover serving
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

# Mount frontend web application
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
