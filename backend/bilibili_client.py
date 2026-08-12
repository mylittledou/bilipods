import os
import json
import re
import time
import urllib.parse
import hashlib
import io
from functools import reduce
from typing import Dict, Any, List, Optional, Tuple
import requests
import qrcode

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

class BilibiliClient:
    def __init__(self, cookie_file: str = "cookies.json"):
        self.cookie_file = cookie_file
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': 'https://www.bilibili.com',
            'Accept': 'application/json, text/plain, */*'
        })
        self.wbi_img_key = None
        self.wbi_sub_key = None
        self.wbi_last_update = 0
        self.load_cookies()

    def load_cookies(self):
        if os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, 'r', encoding='utf-8') as f:
                    cookies_dict = json.load(f)
                    for k, v in cookies_dict.items():
                        self.session.cookies.set(k, v, domain='.bilibili.com')
            except Exception as e:
                print(f"Error loading cookies: {e}")

    def save_cookies(self):
        try:
            cookies_dict = requests.utils.dict_from_cookiejar(self.session.cookies)
            with open(self.cookie_file, 'w', encoding='utf-8') as f:
                json.dump(cookies_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving cookies: {e}")

    def init_buvid(self):
        """Fetch buvid3 & buvid4 if not present in cookies"""
        if not self.session.cookies.get('buvid3'):
            try:
                self.session.get('https://www.bilibili.com', timeout=5)
                r = self.session.get('https://api.bilibili.com/x/frontend/finger/spi', timeout=5)
                data = r.json()
                if data.get('code') == 0:
                    b3 = data['data'].get('b_3')
                    b4 = data['data'].get('b_4')
                    if b3:
                        self.session.cookies.set('buvid3', b3, domain='.bilibili.com')
                    if b4:
                        self.session.cookies.set('buvid4', b4, domain='.bilibili.com')
                    self.save_cookies()
            except Exception as e:
                print(f"Error fetching SPI buvid: {e}")

    def get_wbi_keys(self) -> Tuple[str, str]:
        now = time.time()
        if self.wbi_img_key and self.wbi_sub_key and (now - self.wbi_last_update < 3600):
            return self.wbi_img_key, self.wbi_sub_key
        
        resp = self.session.get('https://api.bilibili.com/x/web-interface/nav', timeout=5).json()
        img_url = resp['data']['wbi_img']['img_url']
        sub_url = resp['data']['wbi_img']['sub_url']
        self.wbi_img_key = img_url.rsplit('/', 1)[1].split('.')[0]
        self.wbi_sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
        self.wbi_last_update = now
        return self.wbi_img_key, self.wbi_sub_key

    def enc_wbi(self, params: dict) -> dict:
        img_key, sub_key = self.get_wbi_keys()
        mixin_key = reduce(lambda s, i: s + (img_key + sub_key)[i], MIXIN_KEY_ENC_TAB, '')[:32]
        curr_time = int(time.time())
        params['wts'] = curr_time
        params = dict(sorted(params.items()))
        params = {
            k: ''.join(filter(lambda chr: chr not in "!'()*", str(v)))
            for k, v in params.items()
        }
        query = urllib.parse.urlencode(params)
        w_rid = hashlib.md5((query + mixin_key).encode('utf-8')).hexdigest()
        params['w_rid'] = w_rid
        return params

    def get_qr_code(self) -> dict:
        resp = self.session.get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate', timeout=5).json()
        if resp.get('code') == 0:
            qr_url = resp['data']['url']
            qrcode_key = resp['data']['qrcode_key']
            
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            import base64
            img_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode('utf-8')
            
            return {
                "qrcode_key": qrcode_key,
                "qr_url": qr_url,
                "qr_img_b64": img_b64
            }
        raise Exception(resp.get('message', 'Failed to generate QR code'))

    def poll_qr_code(self, qrcode_key: str) -> dict:
        url = f'https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={qrcode_key}'
        resp = self.session.get(url, timeout=5).json()
        code = resp.get('data', {}).get('code')
        message = resp.get('data', {}).get('message')
        
        if code == 0:
            self.save_cookies()
            user_info = self.get_login_user_info()
            return {"status": "success", "code": 0, "message": "登录成功", "user": user_info}
        elif code == 86101:
            return {"status": "pending", "code": 86101, "message": "未扫码"}
        elif code == 86090:
            return {"status": "scanned", "code": 86090, "message": "已扫码，请在手机上确认"}
        elif code == 86038:
            return {"status": "expired", "code": 86038, "message": "二维码已失效"}
        else:
            return {"status": "error", "code": code, "message": message or "未知状态"}

    def get_login_user_info(self) -> Optional[dict]:
        try:
            resp = self.session.get('https://api.bilibili.com/x/web-interface/nav', timeout=5).json()
            if resp.get('code') == 0 and resp.get('data', {}).get('isLogin'):
                data = resp['data']
                return {
                    "is_login": True,
                    "uname": data.get('uname'),
                    "mid": data.get('mid'),
                    "face": data.get('face'),
                    "vip_status": data.get('vipStatus')
                }
        except Exception as e:
            print(f"Error checking login info: {e}")
        return {"is_login": False}

    def get_followings(self, vmid: int, pn: int = 1, ps: int = 50) -> dict:
        url = f"https://api.bilibili.com/x/relation/followings?vmid={vmid}&pn={pn}&ps={ps}"
        resp = self.session.get(url, timeout=5).json()
        if resp.get('code') == 0:
            return resp.get('data', {})
        raise Exception(resp.get('message', '获取关注列表失败'))

    def get_all_followings(self, vmid: int) -> list:
        all_list = []
        pn = 1
        import time
        while True:
            try:
                url = f"https://api.bilibili.com/x/relation/followings?vmid={vmid}&pn={pn}&ps=50"
                resp = self.session.get(url, timeout=5).json()
                if resp.get('code') != 0:
                    break
                
                data = resp.get('data', {})
                items = data.get('list') or []
                all_list.extend(items)
                
                if len(items) < 50:
                    break
                
                total = data.get('total', 0)
                if len(all_list) >= total:
                    break
                    
                pn += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"Error fetching page {pn}: {e}")
                break
        return all_list

    @staticmethod
    def parse_mid(input_str: str) -> Optional[int]:
        input_str = input_str.strip()
        if input_str.isdigit():
            return int(input_str)
        match = re.search(r'space\.bilibili\.com/(\d+)', input_str)
        if match:
            return int(match.group(1))
        match_any = re.search(r'(\d+)', input_str)
        if match_any:
            return int(match_any.group(1))
        return None

    def get_up_info(self, mid: int) -> dict:
        """Fetch UP host space profile info with fallback to Card API"""
        self.init_buvid()
        # 1. Try Card API (most resilient unauthenticated API)
        try:
            card_resp = self.session.get(f'https://api.bilibili.com/x/web-interface/card?mid={mid}', timeout=5).json()
            if card_resp.get('code') == 0 and 'card' in card_resp.get('data', {}):
                card = card_resp['data']['card']
                return {
                    "mid": int(card.get('mid', mid)),
                    "name": card.get('name'),
                    "face": card.get('face'),
                    "sign": card.get('sign'),
                    "sex": card.get('sex'),
                    "level": card.get('level_info', {}).get('current_level')
                }
        except Exception as e:
            print(f"Card API error: {e}")

        # 2. Fallback to WBI acc info API
        params = self.enc_wbi({'mid': mid})
        url = f'https://api.bilibili.com/x/space/wbi/acc/info?{urllib.parse.urlencode(params)}'
        resp = self.session.get(url, headers={'Referer': f'https://space.bilibili.com/{mid}'}, timeout=5).json()
        if resp.get('code') == 0:
            data = resp['data']
            return {
                "mid": data.get('mid'),
                "name": data.get('name'),
                "face": data.get('face'),
                "sign": data.get('sign'),
                "sex": data.get('sex'),
                "level": data.get('level')
            }
        raise Exception(resp.get('message', f"无法获取 MID {mid} 的 UP 主信息"))

    def get_up_videos(self, mid: int, page: int = 1, page_size: int = 50) -> dict:
        """Fetch UP host videos and auto-flag paid/charging content"""
        self.init_buvid()
        params = self.enc_wbi({'mid': mid, 'pn': page, 'ps': page_size, 'order': 'pubdate'})
        url = f'https://api.bilibili.com/x/space/wbi/arc/search?{urllib.parse.urlencode(params)}'
        
        headers = {
            'Referer': f'https://space.bilibili.com/{mid}/video',
            'Origin': 'https://space.bilibili.com'
        }
        resp = self.session.get(url, headers=headers, timeout=8).json()
        
        if resp.get('code') != 0:
            raise Exception(resp.get('message', '获取视频列表失败'))
            
        data = resp['data']
        vlist = data.get('list', {}).get('vlist', [])
        page_info = data.get('page', {})
        
        processed_videos = []
        for v in vlist:
            is_charging = bool(v.get('is_charging_arc'))
            is_pay = bool(v.get('is_pay')) or bool(v.get('rights', {}).get('pay'))
            badge = v.get('badge', '')
            is_paid = is_charging or is_pay or badge in ["付费", "充电专属", "独家", "会员"]
            
            length_str = v.get('length', '0:00')
            parts = [int(p) for p in length_str.split(':')]
            duration_sec = 0
            if len(parts) == 2:
                duration_sec = parts[0] * 60 + parts[1]
            elif len(parts) == 3:
                duration_sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
                
            processed_videos.append({
                "bvid": v.get('bvid'),
                "title": v.get('title'),
                "pic": v.get('pic'),
                "length": length_str,
                "duration_seconds": duration_sec,
                "created": v.get('created'),
                "description": v.get('description'),
                "comment_count": v.get('comment'),
                "play_count": v.get('play'),
                "is_paid": is_paid,
                "disabled": is_paid,
                "pay_badge": badge or ("充电专属" if is_charging else ("付费" if is_pay else ""))
            })
            
        return {
            "videos": processed_videos,
            "total": page_info.get('count', len(processed_videos)),
            "page": page_info.get('pn', page),
            "page_size": page_info.get('ps', page_size)
        }

    def get_play_info(self, bvid: str, cid: Optional[int] = None) -> dict:
        if not cid:
            view_resp = self.session.get(f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}', timeout=5).json()
            if view_resp.get('code') != 0:
                raise Exception(view_resp.get('message', '获取视频详情失败'))
            cid = view_resp['data']['cid']
            title = view_resp['data']['title']
            pic = view_resp['data']['pic']
            pubdate = view_resp['data']['pubdate']
            desc = view_resp['data']['desc']
        else:
            title, pic, pubdate, desc = "", "", 0, ""

        play_params = self.enc_wbi({'bvid': bvid, 'cid': cid, 'fnval': 4048})
        play_url = f'https://api.bilibili.com/x/player/wbi/playurl?{urllib.parse.urlencode(play_params)}'
        play_resp = self.session.get(play_url, headers={'Referer': f'https://www.bilibili.com/video/{bvid}'}, timeout=8).json()
        
        # Fallback to standard playurl if WBI returns -412 or error
        if play_resp.get('code') != 0:
            std_url = f'https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16'
            play_resp = self.session.get(std_url, headers={'Referer': f'https://www.bilibili.com/video/{bvid}'}, timeout=8).json()

        if play_resp.get('code') != 0:
            raise Exception(play_resp.get('message', '获取播放地址失败'))
            
        dash_data = play_resp.get('data', {}).get('dash', {})
        audio_streams = []
        if dash_data.get('audio'):
            audio_streams.extend(dash_data['audio'])
        if dash_data.get('dolby') and dash_data['dolby'].get('audio'):
            audio_streams.extend(dash_data['dolby']['audio'])
        if dash_data.get('flac') and dash_data['flac'].get('audio'):
            audio_streams.extend(dash_data['flac']['audio'])
            
        if not audio_streams:
            raise Exception("未能找到可用的音频流")

        audio_streams.sort(key=lambda x: (x.get('id', 0), x.get('bandwidth', 0)), reverse=True)
        best_audio = audio_streams[0]
        audio_download_url = best_audio.get('baseUrl') or best_audio.get('base_url')

        return {
            "bvid": bvid,
            "cid": cid,
            "title": title,
            "pic": pic,
            "pubdate": pubdate,
            "desc": desc,
            "audio_url": audio_download_url,
            "audio_id": best_audio.get('id'),
            "mime_type": best_audio.get('mimeType')
        }
