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
from backend.audio_processor import process_audio_file, sanitize_filename
from backend.rss_generator import generate_podcast_rss
from backend.subscription_manager import SubscriptionManager

app = FastAPI(title="BiliPods", version="1.0.0")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.json")
SUBSCRIPTION_FILE = os.path.join(BASE_DIR, "subscriptions.json")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(FRONTEND_DIR, exist_ok=True)

bilibili_client = BilibiliClient(cookie_file=COOKIE_FILE)
subscription_mgr = SubscriptionManager(filepath=SUBSCRIPTION_FILE, download_dir=DOWNLOAD_DIR)

# Global download progress store for SSE
download_events = []
current_download_task = None

class DownloadRequest(BaseModel):
    mid: int
    bvid_list: List[str]

class SubscriptionRequest(BaseModel):
    mid: int
    up_name: str
    up_avatar: Optional[str] = ""
    min_duration_minutes: float = 0.0
    keywords: Optional[List[str]] = []
    auto_download: bool = True
    ignore_bvids: Optional[List[str]] = []

class SubscriptionUpdateRequest(BaseModel):
    min_duration_minutes: Optional[float] = None
    keywords: Optional[List[str]] = None

async def background_subscription_checker():
    """Periodically check all subscribed UP hosts every 15 minutes"""
    while True:
        try:
            print("[Scheduler] Running periodic check for subscribed UP hosts...")
            await asyncio.to_thread(subscription_mgr.check_all_subscriptions, bilibili_client)
        except Exception as e:
            print(f"[Scheduler] Error in periodic check: {e}")
        await asyncio.sleep(900)  # Check every 15 minutes

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_subscription_checker())

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

async def run_download_batch(mid: int, bvid_list: List[str]):
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
            
            # Fetch play info
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

@app.post("/api/download")
async def start_download(req: DownloadRequest):
    global current_download_task
    if not req.bvid_list:
        raise HTTPException(status_code=400, detail="未选择任何视频")
    
    current_download_task = asyncio.create_task(run_download_batch(req.mid, req.bvid_list))
    return {"status": "ok", "message": f"包含 {len(req.bvid_list)} 个视频的下载任务已启动"}

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

@app.get("/rss/{mid_or_name}")
def get_rss(mid_or_name: str, request: Request):
    mid = BilibiliClient.parse_mid(mid_or_name)
    up_name = mid_or_name
    
    if mid:
        try:
            info = bilibili_client.get_up_info(mid)
            up_name = info['name']
        except Exception:
            pass
            
    server_base_url = str(request.base_url).rstrip('/')
    rss_xml = generate_podcast_rss(
        up_name=up_name,
        mid=mid or 0,
        base_download_dir=DOWNLOAD_DIR,
        server_base_url=server_base_url
    )
    return Response(content=rss_xml, media_type="application/xml")

@app.api_route("/api/artwork/{up_name}/cover.jpg", methods=["GET", "HEAD"])
def get_channel_artwork(up_name: str):
    # 1. Try to serve the UP host's avatar from subscription metadata
    avatar_url = None
    for sub in subscription_mgr.subscriptions.values():
        if sub.get('up_name') == up_name:
            avatar_url = sub.get('up_avatar')
            break
            
    if avatar_url:
        try:
            import requests
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://space.bilibili.com/'
            }
            resp = requests.get(avatar_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                return Response(content=resp.content, media_type=content_type)
        except Exception as e:
            print(f"Failed to fetch avatar for {up_name}: {e}")

    # 2. Fallback to embedded cover from latest audio file
    dir_path = os.path.join(DOWNLOAD_DIR, up_name)
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
    filepath = os.path.join(DOWNLOAD_DIR, up_name, filename)
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

@app.get("/api/subscriptions")
def get_subscriptions():
    return subscription_mgr.list_subscriptions()

@app.post("/api/subscriptions")
def add_subscription(req: SubscriptionRequest):
    sub = subscription_mgr.add_subscription(
        mid=req.mid,
        up_name=req.up_name,
        up_avatar=req.up_avatar or "",
        min_duration_minutes=req.min_duration_minutes,
        keywords=req.keywords,
        auto_download=req.auto_download,
        ignore_bvids=req.ignore_bvids
    )
    return {"status": "ok", "subscription": sub}

@app.post("/api/subscriptions/{mid}/update")
def update_subscription(mid: int, req: SubscriptionUpdateRequest):
    sub = subscription_mgr.update_subscription(
        mid=mid,
        min_duration_minutes=req.min_duration_minutes,
        keywords=req.keywords
    )
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return {"status": "ok", "subscription": sub}

@app.delete("/api/subscriptions/{mid}")
def delete_subscription(mid: int):
    # Retrieve sub to get the up_name for deleting local files
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
                
    return {"status": "ok", "message": f"MID {mid} 订阅已取消，本地文件已清理"}

@app.post("/api/subscriptions/check")
async def check_subscriptions_now(mid: Optional[int] = None):
    if mid:
        res = await asyncio.to_thread(subscription_mgr.check_up_updates, mid, bilibili_client)
        return {"status": "ok", "results": [res]}
    else:
        results = await asyncio.to_thread(subscription_mgr.check_all_subscriptions, bilibili_client)
        return {"status": "ok", "results": results}

class DeleteFilesRequest(BaseModel):
    filenames: List[str]

@app.get("/api/subscriptions/{mid}/files")
def get_subscription_files(mid: int):
    sub = subscription_mgr.get_subscription(mid)
    if not sub or not sub.get("up_name"):
        raise HTTPException(status_code=404, detail="订阅不存在")
    
    up_dir = os.path.join(DOWNLOAD_DIR, sub["up_name"])
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
def delete_subscription_files(mid: int, req: DeleteFilesRequest):
    sub = subscription_mgr.get_subscription(mid)
    if not sub or not sub.get("up_name"):
        raise HTTPException(status_code=404, detail="订阅不存在")
        
    up_dir = os.path.join(DOWNLOAD_DIR, sub["up_name"])
    deleted_count = 0
    errors = []
    
    for fname in req.filenames:
        if not fname.endswith(".m4a") or ".." in fname or "/" in fname or "\\" in fname:
            continue
            
        filepath = os.path.join(up_dir, fname)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                deleted_count += 1
            except Exception as e:
                errors.append(f"删除 {fname} 失败: {str(e)}")
                
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
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://www.bilibili.com'
    }
    try:
        resp = bilibili_client.session.get(url, headers=headers, timeout=6)
        content_type = resp.headers.get('content-type', 'image/jpeg')
        return Response(content=resp.content, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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


# Mount downloads directory for static audio & cover serving
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

# Mount frontend web application
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
