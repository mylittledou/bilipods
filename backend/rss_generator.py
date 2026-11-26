import os
import re
import time
import urllib.parse
from email.utils import formatdate
import xml.etree.ElementTree as ET
from mutagen.mp4 import MP4
import hashlib

# Explicitly register XML namespaces for podcast spec compliance
ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
ET.register_namespace("content", "http://purl.org/rss/1.0/modules/content/")

def sanitize_xml_text(text: str) -> str:
    if not text:
        return ""
    # Strip illegal XML control characters
    cleaned = re.sub(r"[--]", "", str(text))
    return cleaned.replace(chr(0), "").strip()

def generate_podcast_rss(
    up_name: str,
    mid: int,
    base_download_dir: str,
    server_base_url: str,
    podcast_type: str = "episodic",
    order: str = "desc"
) -> str:
    """Generate Apple Podcasts & Audiobookshelf compliant RSS 2.0 XML feed for an UP host"""
    up_dir = os.path.join(base_download_dir, up_name)
    
    # Root RSS element
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = ET.SubElement(rss, "channel")
    
    clean_up_name = sanitize_xml_text(up_name)
    
    # Channel metadata
    ET.SubElement(channel, "title").text = f"{clean_up_name} - BiliPods 播客"
    ET.SubElement(channel, "link").text = f"https://space.bilibili.com/{mid}"
    ET.SubElement(channel, "description").text = f"BiliPods 自动生成的 B 站 UP 主【{clean_up_name}】视频音频播客订阅源"
    ET.SubElement(channel, "language").text = "zh-cn"
    
    # Apple Podcasts show type (serial: sequential story/history listening, episodic: newest first)
    ET.SubElement(channel, "itunes:type").text = podcast_type
    ET.SubElement(channel, "itunes:author").text = clean_up_name
    owner = ET.SubElement(channel, "itunes:owner")
    ET.SubElement(owner, "itunes:name").text = clean_up_name
    ET.SubElement(owner, "itunes:email").text = "bilipods@bilibili.com"
    
    # Show Cover (Podcast Album Cover) uses the dynamic artwork API
    encoded_up_name = urllib.parse.quote(up_name)
    show_cover_url = f"{server_base_url}/api/artwork/{encoded_up_name}/cover.jpg?v={int(time.time())}"
    ET.SubElement(channel, "itunes:image", {"href": show_cover_url})
    
    category = ET.SubElement(channel, "itunes:category", {"text": "Leisure"})
    ET.SubElement(category, "itunes:category", {"text": "Video Games"})
    ET.SubElement(channel, "itunes:explicit").text = "false"
    
    if not os.path.exists(up_dir):
        return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")
        
    m4a_files = [f for f in os.listdir(up_dir) if f.endswith(".m4a") and not f.startswith("_temp_")]
    
    # Collect all audio info
    episodes = []
    for filename in m4a_files:
        filepath = os.path.join(up_dir, filename)
        try:
            file_stat = os.stat(filepath)
            file_size = file_stat.st_size
            file_mtime = file_stat.st_mtime
        except Exception:
            continue
            
        title = os.path.splitext(filename)[0]
        desc = ""
        date_str = None
        duration_sec = 0
        
        try:
            m4a = MP4(filepath)
            if m4a.get("©nam"):
                title = m4a["©nam"][0]
            if m4a.get("©cmt"):
                desc = m4a["©cmt"][0]
            if m4a.get("©day"):
                date_str = m4a["©day"][0]
            if m4a.info:
                duration_sec = int(m4a.info.length)
        except Exception:
            pass
            
        # Prioritize exact file_mtime as pub_time (synced with Bilibili created timestamp)
        pub_time = file_mtime
        
        episodes.append({
            "filename": filename,
            "title": title,
            "desc": desc or title,
            "pub_time": pub_time,
            "file_size": file_size,
            "duration_sec": duration_sec
        })

    # Sort all episodes chronologically (oldest first) to assign sequential episode numbers
    episodes.sort(key=lambda x: x["pub_time"])
    for idx, ep in enumerate(episodes):
        ep["episode_num"] = idx + 1

    # Sort for feed output
    if order == "asc":
        # Oldest to newest
        feed_episodes = episodes
    else:
        # Newest to oldest (standard podcast RSS specification)
        feed_episodes = sorted(episodes, key=lambda x: x["pub_time"], reverse=True)
        
    for ep in feed_episodes:
        filename = ep["filename"]
        clean_title = sanitize_xml_text(ep["title"])
        clean_desc = sanitize_xml_text(ep["desc"])
        
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = clean_title
        ET.SubElement(item, "itunes:title").text = clean_title
        ET.SubElement(item, "description").text = clean_desc
        ET.SubElement(item, "pubDate").text = formatdate(ep["pub_time"], usegmt=True)
        
        # Audio file enclosure URL
        encoded_filename = urllib.parse.quote(filename)
        audio_file_url = f"{server_base_url}/downloads/{encoded_up_name}/{encoded_filename}"
        ET.SubElement(item, "enclosure", {
            "url": audio_file_url,
            "length": str(ep["file_size"]),
            "type": "audio/mp4"
        })
        
        guid_hash = hashlib.md5(f"bilipods-{filename}".encode("utf-8")).hexdigest()
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = f"bilipods-{guid_hash}"
        ET.SubElement(item, "itunes:author").text = clean_up_name
        ET.SubElement(item, "itunes:episode").text = str(ep["episode_num"])
        ET.SubElement(item, "itunes:episodeType").text = "full"
        
        if ep["duration_sec"] > 0:
            ET.SubElement(item, "itunes:duration").text = str(ep["duration_sec"])
            
        # Episode Cover URL
        ep_cover_url = f"{server_base_url}/api/artwork/{encoded_up_name}/{encoded_filename}/cover.jpg?v={int(ep['pub_time'])}"
        ET.SubElement(item, "itunes:image", {"href": ep_cover_url})
        
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")
