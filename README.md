# BiliPods & YTPods

将 **B 站 UP 主** 与 **YouTube 频道 / 播放列表 / 单集视频** 一键转为符合 Apple Podcasts 规范的高音质 `.m4a` 播客音频，支持 **自动后台订阅追更**、**原片发布时间校准**、**Apple Podcasts RSS 生成** 与 **Audiobookshelf 本地目录无缝入库**。

---

## ✨ 核心特性

- **双平台统一支持**：同时支持 Bilibili（UP 主主页 / MID / 我的关注）与 YouTube（视频链接、播放列表、频道 `@Handle` / `UC...` ID / 关键词 / 我的关注）。
- **高音质零损直出封装**：
  - B 站优先提取无损/高码率音轨并封装为 `.m4a`（FastStart 优化）；
  - YouTube 优先直取原生 DASH AAC 流（itag 140）免重编码封装，大幅降低 CPU 占用。
- **Apple Podcasts 标准封面与元数据**：
  - 自动裁切 1:1 居中并优化为 1400~3000px JPG 封面（专辑 `cover.jpg` + 单集内嵌 `covr`）；
  - 自动写入标题、作者、专辑、简介（含原视频链接）与精确发布日期（`©day` 及文件 `mtime`），确保客户端严格按真实发布时间排序。
- **会员 / 付费专属过滤**：自动识别 B 站充电专属、YouTube 会员专属视频并在列表置灰标记，后台轮询自动跳过。
- **自动追更与滚动保留**：每 15 分钟后台自动检查更新；支持最小时长、关键词过滤，以及「保留最新 N 集」或「`0` = 永久保留全部」。
- **内置标准 RSS 与本地管理**：提供 `/rss/{mid_or_name}` 订阅链接、本地音频批量管理与可选 Bark 更新通知。

---

## 🚀 快速部署（Docker Compose，推荐）

镜像支持 `linux/amd64` 与 `linux/arm64`（Linux / NAS / macOS / Windows / 树莓派开箱即用），内置 `ffmpeg`、`yt-dlp[default]` 与 `deno` 运行时。

### 1. 创建目录与配置文件

```bash
mkdir -p bilipods/data bilipods/downloads
cd bilipods
echo '{}' > cookies.json
echo '{}' > subscriptions.json
```

> 注意：请提前用空 JSON `{}` 初始化 `cookies.json` 和 `subscriptions.json`，避免 Docker 挂载时将其创建为目录。

### 2. 创建 `docker-compose.yml`

```yaml
services:
  bilipods:
    image: ghcr.io/mylittledou/bilipods:latest
    container_name: bilipods
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./downloads:/app/downloads                 # 音频输出目录（可直接映射为 Audiobookshelf 播客库目录）
      - ./cookies.json:/app/cookies.json           # B 站登录凭证
      - ./subscriptions.json:/app/subscriptions.json # 订阅配置持久化
      - ./data:/app/data                           # YouTube Cookie 存储目录（youtube_cookies.txt）
    environment:
      - PYTHONUNBUFFERED=1
      # 可选：配置 Bark 推送通知（新剧集自动更新完成后推送汇总提醒）
      # - BARK_KEY=your_bark_key
      # - BARK_SERVER=https://api.day.app
```

### 3. 启动服务

```bash
docker compose up -d
```

启动后访问：`http://<你的服务器IP>:8000`

*(如需自行从源码构建，请下载源码并运行 `docker build -t bilipods:latest .`)*

---

## 📖 使用指南

### 一、B 站账号登录（两种方式）

点击右上角 **「📱 登录 B 站」**：

1. **方式一：APP 扫码登录**
   - 直接使用手机 B 站 App 扫描弹窗二维码并确认即可。
2. **方式二：手动输入 Cookie（海外服务器推荐）**
   - 若服务器位于海外，B 站 App 扫码可能触发「异地登录风险拦截」，推荐使用 Cookie 登录：
   - 在电脑浏览器打开 `https://www.bilibili.com` 并登录账号；
   - 按 `F12` 打开开发者工具 $\to$ **Application（应用）** $\to$ **Cookies** $\to$ `https://www.bilibili.com`；
   - 复制并按如下格式粘贴保存即可：
     ```text
     SESSDATA=你的SESSDATA; bili_jct=你的bili_jct; DedeUserID=你的DedeUserID;
     ```

### 二、YouTube Cookie 配置（推荐）

用于绕过人机验证、提取高音质音频及解锁 **「❤️ 我的关注」** 频道列表：

1. 在浏览器安装扩展 **Get cookies.txt LOCALLY**（Chrome / Edge 商店可搜）；
2. 打开并登录 `https://www.youtube.com`，点击扩展导出 Netscape 格式的 Cookie 内容；
3. 切换到页面 **YouTube** 标签页 $\to$ 点击右上角 **「🔑 YouTube Cookie」** $\to$ 粘贴保存。

### 三、解析、全量下载与自动追更

1. **输入目标或从关注挑选**：
   - 支持直接点击 **「❤️ 我的关注」** 挑选，或粘贴 UP 主主页 / MID / YouTube `@Handle` / 频道链接 / 播放列表 / 单集链接。
2. **设置过滤与保留规则**：
   - **时长(分)** & **关键词**：过滤短视频或特定栏目；
   - **下载历史**：填写本次立即拉取的最新集数，或点击右侧 **「全部」** 一键填入全部符合条件的存量历史音频；
   - **保留数**：
     - **`0`（默认）**：永久保留全部历史音频，后续自动更新**绝不删除旧文件**；
     - **`N`（如 `20`）**：滚动保留最新 `N` 集，新增入库时自动清理更早的剧集。
3. **点击「确定订阅 / 下载」**：
   - 系统立即开始提取所选历史音频，并每 15 分钟在后台自动巡检新视频。

### 四、接入 Audiobookshelf / Apple Podcasts

- **Audiobookshelf（推荐）**：将 `docker-compose.yml` 中的 `./downloads` 直接映射到 Audiobookshelf 的播客媒体库目录，Audiobookshelf 会自动读取频道封面（`cover.jpg`）与单集 M4A 内嵌标签和发布时间。
- **RSS 订阅**：点击 **「⭐ 我的订阅」** 中对应频道的 RSS 链接（`http://<host>:8000/rss/<mid_or_channel>`），即可导入 Apple Podcasts、AntennaPod 等任意播客客户端。

---

## ❓ 常见问题 (FAQ)

- **未登录直接解析 B 站 UP 主报错 `-352 风控校验失败` 或 `request was banned`？**
  - 云服务器机房 IP 极易被 B 站 WBI 接口拦截，请先在右上角通过 **扫码** 或 **Cookie** 登录 B 站账号后再解析。
- **YouTube 提取单集提示 `Sign in to confirm you're not a bot`？**
  - 云服务器 IP 解析 YouTube 音频流通常需要身份验证，请按上文导入浏览器导出的 Netscape 格式 YouTube Cookie 后重试。
- **为什么保留数设为 `0` 时点击订阅一集也没下载？**
  - **保留数 `0`** 表示「永久保留已有文件、不删除旧音频」，而**首次要立即拉取的历史集数**由左侧 **「下载历史」**（或点击 **`全部`** 按钮）控制。

---

## 🔧 环境变量说明

| 变量名 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `BARK_KEY` | 空（不推送） | 可选，填写 Bark 推送 Key 后将在后台定时更新完成时发送汇总通知 |
| `BARK_SERVER` | `https://api.day.app` | 可选，自建 Bark 服务端地址 |
| `PYTHONUNBUFFERED` | `1` | 实时输出容器日志 |

---

## 🤝 社区与致谢

- 感谢 **[LINUX DO](https://linux.do)** 社区与各位佬友的交流与灵感分享（欢迎前往 [LINUX DO](https://linux.do) 探讨折腾播客与自托管工具）。
- 本项目使用了 [yt-dlp](https://github.com/yt-dlp/yt-dlp)、[FastAPI](https://fastapi.tiangolo.com/)、[Mutagen](https://mutagen.readthedocs.io/)、[FFmpeg](https://ffmpeg.org/) 等优秀开源组件。

---

## ⚠️ 免责声明

- 本项目以 [MIT License](LICENSE) 开源，仅供个人学习与私人离线播客归档使用；
- 请严格遵守相关平台服务条款及内容创作者版权规定，勿用于任何商业用途或公开二次分发。
