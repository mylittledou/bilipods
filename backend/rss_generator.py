import os
import time
import urllib.parse
from email.utils import formatdate
import xml.etree.ElementTree as ET
from mutagen.mp4 import MP4

def generate_podcast_rss(
    up_name: str,
    mid: int,
    base_download_dir: str,
    server_base_url: str
) -> str:
    """Generate Apple Podcasts compliant RSS 2.0 XML feed for an UP host"""
    up_dir = os.path.join(base_download_dir, up_name)
    
    # Root RSS element
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = ET.SubElement(rss, "channel")
    
    # Channel metadata
    ET.SubElement(channel, "title").text = f"{up_name} - BiliPods 播客"
    ET.SubElement(channel, "link").text = f"https://space.bilibili.com/{mid}"
    ET.SubElement(channel, "description").text = f"BiliPods 自动生成的 B 站 UP 主【{up_name}】视频音频播客订阅源"
    ET.SubElement(channel, "language").text = "zh-cn"
    
    ET.SubElement(channel, "itunes:author").text = up_name
    owner = ET.SubElement(channel, "itunes:owner")
    ET.SubElement(owner, "itunes:name").text = up_name
    ET.SubElement(owner, "itunes:email").text = "bilipods@bilibili.com"
    
    # Show Cover (Album Cover: cover.jpg in UP directory)
    encoded_up_name = urllib.parse.quote(up_name)
    show_cover_url = f"{server_base_url}/downloads/{encoded_up_name}/cover.jpg"
    ET.SubElement(channel, "itunes:image", {"href": show_cover_url})
    
    category = ET.SubElement(channel, "itunes:category", {"text": "Leisure"})
    ET.SubElement(category, "itunes:category", {"text": "Video Games"})
    ET.SubElement(channel, "itunes:explicit").text = "false"
    
    if not os.path.exists(up_dir):
        xml_str = ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")
        return xml_str
        
    m4a_files = [f for f in os.listdir(up_dir) if f.endswith(".m4a") and not f.startswith("_temp_")]
    
    for filename in sorted(m4a_files, key=lambda f: os.path.getmtime(os.path.join(up_dir, f)), reverse=True):
        filepath = os.path.join(up_dir, filename)
        file_stat = os.stat(filepath)
        file_size = file_stat.st_size
        file_mtime = file_stat.st_mtime
        
        # Read MP4 metadata tags
        title = os.path.splitext(filename)[0]
        desc = ""
        date_str = None
        duration_sec = 0
        
        try:
            m4a = MP4(filepath)
            if m4a.get("\xa9nam"):
                title = m4a["\xa9nam"][0]
            if m4a.get("\xa9cmt"):
                desc = m4a["\xa9cmt"][0]
            if m4a.get("\xa9day"):
                date_str = m4a["\xa9day"][0]
            if m4a.info:
                duration_sec = int(m4a.info.length)
        except Exception as e:
            print(f"Error reading metadata for {filename}: {e}")
            
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = desc or title
        
        pub_time = file_mtime
        if date_str:
            try:
                t_struct = time.strptime(date_str, "%Y-%m-%d")
                pub_time = time.mktime(t_struct)
            except Exception:
                pass
        ET.SubElement(item, "pubDate").text = formatdate(pub_time, usegmt=True)
        
        # Audio file enclosure URL
        encoded_filename = urllib.parse.quote(filename)
        audio_file_url = f"{server_base_url}/downloads/{encoded_up_name}/{encoded_filename}"
        ET.SubElement(item, "enclosure", {
            "url": audio_file_url,
            "length": str(file_size),
            "type": "audio/mp4"
        })
        
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = f"bilipods-{filename}"
        ET.SubElement(item, "itunes:author").text = up_name
        if duration_sec > 0:
            ET.SubElement(item, "itunes:duration").text = str(duration_sec)
        
        # Episode Cover URL (serves embedded artwork via endpoint /api/artwork/{up_name}/{filename}/cover.jpg)
        ep_cover_url = f"{server_base_url}/api/artwork/{encoded_up_name}/{encoded_filename}/cover.jpg"
        ET.SubElement(item, "itunes:image", {"href": ep_cover_url})
        
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")
