let currentPlatform = 'bilibili';
let currentMid = null;
let currentRawVideos = [];
let filteredVideos = [];
let currentSubPlatform = 'bilibili';
let currentSingleYtVideo = null;
let currentLocalFilesMid = null;
let currentLocalFilesUpName = null;
let subPlatformFilter = 'all';
let qrPollTimer = null;
let currentQrKey = null;
let sseSource = null;

function showToast(msg) {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; top: 20px; left: 50%; transform: translateX(-50%) translateY(-100px);
    background: var(--accent-1); color: white; border: 4px solid var(--border-color);
    box-shadow: 8px 8px 0px 0px var(--border-color); padding: 12px 24px;
    font-weight: 900; z-index: 10000; opacity: 0; transition: all 0.3s;
    max-width: 85%; text-align: center; word-break: break-word; white-space: pre-wrap;
  `;
  toast.textContent = msg;
  document.body.appendChild(toast);
  requestAnimationFrame(() => {
    toast.style.transform = 'translateX(-50%) translateY(0)';
    toast.style.opacity = '1';
  });
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(-50%) translateY(-100px)';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function initApp() {
  initAuthStatus();
  checkYtCookieStatus();
  setupEventListeners();
  switchPlatform('bilibili');
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}

// ----------------- Platform Switcher -----------------
function switchPlatform(platform) {
  currentPlatform = platform;
  const tabBili = document.getElementById('tabBilibili');
  const tabYt = document.getElementById('tabYouTube');
  const secBili = document.getElementById('bilibiliSection');
  const secYt = document.getElementById('youtubeSection');
  const btnShowFollowed = document.getElementById('btnShowFollowed');
  const btnShowYtCookie = document.getElementById('btnShowYtCookie');
  const btnShowYtChannels = document.getElementById('btnShowYtChannels');
  const loggedOutView = document.getElementById('loggedOutView');
  const loggedInView = document.getElementById('loggedInView');

  if (platform === 'youtube') {
    tabYt.classList.add('active');
    tabBili.classList.remove('active');
    secYt.classList.remove('hidden');
    secBili.classList.add('hidden');
    btnShowYtCookie.classList.remove('hidden');
    btnShowFollowed.classList.add('hidden');
    loggedOutView.classList.add('hidden');
    loggedInView.classList.add('hidden');
    checkYtCookieStatus();
  } else {
    tabBili.classList.add('active');
    tabYt.classList.remove('active');
    secBili.classList.remove('hidden');
    secYt.classList.add('hidden');
    btnShowYtCookie.classList.add('hidden');
    btnShowYtChannels.classList.add('hidden');
    initAuthStatus(); // restore Bilibili login view state
  }
}

// ----------------- Event Listeners -----------------
function setupEventListeners() {
  // Tab Switcher
  document.getElementById('tabBilibili').addEventListener('click', () => switchPlatform('bilibili'));
  document.getElementById('tabYouTube').addEventListener('click', () => switchPlatform('youtube'));

  // Bilibili Auth
  document.getElementById('btnShowQr').addEventListener('click', showQrModal);
  document.getElementById('btnCloseQr').addEventListener('click', closeQrModal);
  document.getElementById('btnRefreshQr').addEventListener('click', showQrModal);
  document.getElementById('btnSubmitCookie').addEventListener('click', submitCookieLogin);
  document.getElementById('btnLogout').addEventListener('click', async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
      document.getElementById('loggedInView').classList.add('hidden');
      document.getElementById('loggedOutView').classList.remove('hidden');
      document.getElementById('btnShowFollowed').classList.add('hidden');
      showToast("已成功退出登录！");
    } catch (e) {
      console.error(e);
    }
  });

  // YouTube Channels Modal
  document.getElementById('btnShowYtChannels').addEventListener('click', showYtChannelsModal);

  // YouTube Cookie Modal
  document.getElementById('btnShowYtCookie').addEventListener('click', showYtCookieModal);
  document.getElementById('btnCloseYtCookie').addEventListener('click', () => {
    document.getElementById('ytCookieModal').classList.add('hidden');
  });
  document.getElementById('btnSaveYtCookie').addEventListener('click', saveYtCookie);
  document.getElementById('btnClearYtCookie').addEventListener('click', clearYtCookie);

  // Search Buttons
  document.getElementById('btnSearchUp').addEventListener('click', handleUpSearch);
  document.getElementById('upQueryInput').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleUpSearch();
  });

  document.getElementById('btnSearchYt').addEventListener('click', handleYtSearch);
  document.getElementById('ytQueryInput').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleYtSearch();
  });

  // Quick Links
  const quickBili = document.getElementById('btnQuickFollowedBili');
  if (quickBili) quickBili.addEventListener('click', showFollowingsModal);

  const quickYt = document.getElementById('btnQuickFollowedYt');
  if (quickYt) quickYt.addEventListener('click', showYtChannelsModal);

  const quickYtCookie = document.getElementById('btnQuickYtCookie');
  if (quickYtCookie) quickYtCookie.addEventListener('click', showYtCookieModal);

  // Single YouTube Extraction Button
  document.getElementById('btnExtractSingleYt').addEventListener('click', handleExtractSingleYt);

  // Filters inside Unified Sub Modal
  document.getElementById('subDurationMinInput').addEventListener('input', applyFiltersAndRender);
  document.getElementById('subKeywordInput').addEventListener('input', applyFiltersAndRender);
  document.getElementById('btnConfirmSub').addEventListener('click', confirmAddSubscription);
  document.getElementById('btnCloseUnifiedSub').addEventListener('click', () => {
    document.getElementById('unifiedSubModal').classList.add('hidden');
  });

  const btnSelectAllHistory = document.getElementById('btnSelectAllHistory');
  if (btnSelectAllHistory) {
    btnSelectAllHistory.addEventListener('click', () => {
      const minDuration = parseFloat(document.getElementById('subDurationMinInput').value) || 0;
      const kwStr = document.getElementById('subKeywordInput').value.trim();
      const keywords = kwStr ? kwStr.split(/[,，\s]+/).filter(k => k) : [];
      const matched = currentRawVideos.filter(v => {
        if (v.is_paid || v.disabled) return false;
        if ((v.duration_seconds || 0) < minDuration * 60) return false;
        if (keywords.length > 0) {
          const text = (v.title + " " + (v.description || "")).toLowerCase();
          if (!keywords.some(k => text.includes(k.toLowerCase()))) return false;
        }
        return true;
      });
      document.getElementById('subHistoryCountInput').value = matched.length;
      showToast(`已一键填入符合条件的全部 ${matched.length} 集视频！`);
    });
  }

  // Subscriptions Modal
  document.getElementById('btnShowSubs').addEventListener('click', showSubModal);
  document.getElementById('btnCloseSubModal').addEventListener('click', closeSubModal);
  document.getElementById('btnCheckAllSubsNow').addEventListener('click', checkAllSubsNow);

  // Subscription Platform Filter Buttons
  const subFilterBtns = document.querySelectorAll('#subFilterPlatformBtns button');
  subFilterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      subFilterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      subPlatformFilter = btn.getAttribute('data-filter');
      loadSubscriptions();
    });
  });

  // Sub Detail & Local Files
  document.getElementById('btnCloseSubDetail').addEventListener('click', () => {
    document.getElementById('subDetailModal').classList.add('hidden');
    document.getElementById('subModal').classList.remove('hidden');
  });
  document.getElementById('btnLocalFilesSelectAll').addEventListener('click', () => {
    document.querySelectorAll('.local-file-checkbox').forEach(cb => cb.checked = true);
    updateLocalFilesSelectedCount();
  });
  document.getElementById('btnLocalFilesUnselectAll').addEventListener('click', () => {
    document.querySelectorAll('.local-file-checkbox').forEach(cb => cb.checked = false);
    updateLocalFilesSelectedCount();
  });
  document.getElementById('btnDeleteSelectedFiles').addEventListener('click', deleteSelectedFiles);

  // Progress Modal Close
  document.getElementById('btnCloseProgress').addEventListener('click', () => {
    document.getElementById('progressModal').classList.add('hidden');
  });

  // Followed UPs
  document.getElementById('btnShowFollowed').addEventListener('click', showFollowingsModal);
  document.getElementById('btnCloseFollowings').addEventListener('click', () => {
    document.getElementById('followingsModal').classList.add('hidden');
  });
}

// ----------------- Auth Status (Bilibili) -----------------
async function initAuthStatus() {
  if (currentPlatform === 'youtube') return;
  try {
    const res = await fetch('/api/auth/status?t=' + Date.now());
    const data = await res.json();
    if (data.is_login) {
      document.getElementById('loggedOutView').classList.add('hidden');
      document.getElementById('loggedInView').classList.remove('hidden');
      document.getElementById('userAvatar').src = data.face;
      document.getElementById('userName').textContent = data.uname;
      document.getElementById('btnShowFollowed').classList.remove('hidden');
      if (data.vip_status) {
        document.getElementById('vipBadge').classList.remove('hidden');
      }
    } else {
      document.getElementById('loggedOutView').classList.remove('hidden');
      document.getElementById('loggedInView').classList.add('hidden');
      document.getElementById('btnShowFollowed').classList.add('hidden');
    }
  } catch (err) {
    console.error("Auth status check failed:", err);
  }
}

// ----------------- YouTube Cookie Status & Actions -----------------
async function checkYtCookieStatus() {
  try {
    const res = await fetch('/api/youtube/auth/status');
    const data = await res.json();
    const btn = document.getElementById('btnShowYtCookie');
    const btnChannels = document.getElementById('btnShowYtChannels');
    const statusText = document.getElementById('ytCookieStatusText');
    if (data.has_cookies) {
      btn.innerHTML = `<span class="icon">🔑</span> YouTube Cookie <span style="color:#10B981; font-weight:900;">(已配置)</span>`;
      if (statusText) statusText.innerHTML = `当前状态: <strong style="color:#10B981;">✅ 已配置 Cookie</strong> (${data.date_str || '有效'})`;
      if (currentPlatform === 'youtube') {
        btnChannels.classList.remove('hidden');
      }
    } else {
      btn.innerHTML = `<span class="icon">🔑</span> YouTube Cookie <span style="color:#F59E0B;">(未配置)</span>`;
      if (statusText) statusText.innerHTML = `当前状态: <strong style="color:#F59E0B;">⚠️ 未配置 Cookie</strong> (普通视频可直下，配置后支持全部限制视频)`;
      btnChannels.classList.add('hidden');
    }
  } catch (e) {
    console.error(e);
  }
}

async function showYtCookieModal() {
  document.getElementById('ytCookieModal').classList.remove('hidden');
  await checkYtCookieStatus();
}

async function saveYtCookie() {
  const content = document.getElementById('ytCookieInput').value.trim();
  if (!content) {
    showToast("请先粘贴 Cookie 内容！");
    return;
  }
  const btn = document.getElementById('btnSaveYtCookie');
  btn.disabled = true;
  btn.textContent = "保存中...";
  try {
    const res = await fetch('/api/youtube/cookie', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookie_string: content })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("YouTube Cookie 保存成功！");
      document.getElementById('ytCookieInput').value = '';
      document.getElementById('ytCookieModal').classList.add('hidden');
      checkYtCookieStatus();
    } else {
      showToast("保存失败: " + data.detail);
    }
  } catch (e) {
    showToast("请求失败: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "💾 保存 Cookie";
  }
}

async function clearYtCookie() {
  if (!confirm("确定要清空已保存的 YouTube Cookie 吗？")) return;
  try {
    await fetch('/api/youtube/cookie', { method: 'DELETE' });
    showToast("YouTube Cookie 已清空！");
    document.getElementById('ytCookieInput').value = '';
    document.getElementById('ytCookieModal').classList.add('hidden');
    checkYtCookieStatus();
  } catch (e) {
    showToast("清空失败: " + e.message);
  }
}

// ----------------- QR Login Flow (Bilibili) -----------------
async function showQrModal() {
  document.getElementById('qrModal').classList.remove('hidden');
  document.getElementById('qrOverlay').classList.add('hidden');
  document.getElementById('qrStatusText').textContent = "正在生成登录二维码...";
  
  try {
    const res = await fetch('/api/auth/qrcode');
    const data = await res.json();
    if (!res.ok || !data.qr_img_b64) {
      throw new Error(data.detail || "二维码接口返回异常");
    }
    currentQrKey = data.qrcode_key;
    document.getElementById('qrCodeImg').src = data.qr_img_b64;
    document.getElementById('qrStatusText').textContent = "请使用 B 站 App 扫码登录";

    if (qrPollTimer) clearInterval(qrPollTimer);
    qrPollTimer = setInterval(pollQrStatus, 2000);
  } catch (err) {
    document.getElementById('qrStatusText').textContent = "获取二维码失败: " + err.message;
  }
}

function closeQrModal() {
  document.getElementById('qrModal').classList.add('hidden');
  if (qrPollTimer) {
    clearInterval(qrPollTimer);
    qrPollTimer = null;
  }
}

async function pollQrStatus() {
  if (!currentQrKey) return;
  try {
    const res = await fetch(`/api/auth/poll?qrcode_key=${currentQrKey}`);
    const data = await res.json();
    document.getElementById('qrStatusText').textContent = data.message;
    if (data.code === 0) {
      closeQrModal();
      initAuthStatus();
      showToast("登录成功！");
    } else if (data.code === 86038) {
      clearInterval(qrPollTimer);
      document.getElementById('qrOverlayMsg').textContent = "二维码已失效";
      document.getElementById('qrOverlay').classList.remove('hidden');
    }
  } catch (err) {
    console.error("Poll QR status error:", err);
  }
}

async function submitCookieLogin() {
  const cookieStr = document.getElementById('cookieInput').value.trim();
  if (!cookieStr) {
    showToast("请先输入 Cookie！");
    return;
  }
  const btn = document.getElementById('btnSubmitCookie');
  btn.disabled = true;
  btn.textContent = "验证中...";
  try {
    const res = await fetch('/api/auth/cookie', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookie_string: cookieStr })
    });
    const data = await res.json();
    if (res.ok && data.is_login) {
      showToast("登录成功！");
      closeQrModal();
      initAuthStatus();
    } else {
      showToast("登录失败：" + (data.detail || data.message || "Cookie无效"));
    }
  } catch (err) {
    showToast("请求出错：" + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "💾 验证并保存";
  }
}

async function readApiResponse(res, fallbackMsg = "请求失败") {
  const rawText = await res.text();
  let data = null;
  try {
    data = rawText ? JSON.parse(rawText) : {};
  } catch (_) {
    data = null;
  }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || rawText.slice(0, 120) || `${fallbackMsg} (HTTP ${res.status})`;
    throw new Error(detail);
  }
  if (data === null) {
    throw new Error(`服务返回异常响应 (HTTP ${res.status}): ${rawText.slice(0, 120)}`);
  }
  return data;
}

// ----------------- Bilibili UP Search -----------------
async function handleUpSearch() {
  const query = document.getElementById('upQueryInput').value.trim();
  if (!query) {
    showToast("请输入 UP 主主页链接或数字 MID");
    return;
  }
  currentSubPlatform = 'bilibili';
  document.getElementById('btnSearchUp').disabled = true;
  document.getElementById('btnSearchUp').textContent = "正在拉取 UP 主视频...";

  try {
    const res = await fetch(`/api/up/search?query=${encodeURIComponent(query)}`);
    const data = await readApiResponse(res, "解析失败");

    currentMid = data.up_info.mid;
    currentRawVideos = data.videos;

    // Render UP Profile
    const avatarUrl = data.up_info.face ? (data.up_info.face.startsWith('http://') ? 'https://' + data.up_info.face.substring(7) : data.up_info.face) : '';
    const avatarEl = document.getElementById('upAvatar');
    avatarEl.src = avatarUrl;
    avatarEl.onerror = () => { avatarEl.src = `/api/proxy_img?url=${encodeURIComponent(avatarUrl)}`; };

    document.getElementById('unifiedSubModalTitle').textContent = "⭐ 配置 B站 UP 主订阅 / 批量提取";
    document.getElementById('upName').textContent = data.up_info.name;
    document.getElementById('upMid').textContent = `MID: ${data.up_info.mid}`;
    document.getElementById('upSign').textContent = data.up_info.sign || "无个人简介";
    document.getElementById('upTotalVideos').textContent = data.total;

    document.getElementById('subDurationMinInput').value = 0;
    document.getElementById('subKeywordInput').value = '';
    document.getElementById('subHistoryCountInput').value = 0;
    document.getElementById('subKeepCountInput').value = 0;
    
    document.getElementById('unifiedSubModal').classList.remove('hidden');
    document.getElementById('followingsModal').classList.add('hidden');
    
    applyFiltersAndRender();
  } catch (err) {
    showToast("解析 UP 主失败: " + err.message);
  } finally {
    document.getElementById('btnSearchUp').disabled = false;
    document.getElementById('btnSearchUp').innerHTML = '<span class="icon">🔍</span> 解析 UP 主视频';
  }
}

// ----------------- YouTube Search -----------------
async function handleYtSearch() {
  const query = document.getElementById('ytQueryInput').value.trim();
  if (!query) {
    showToast("请输入 YouTube 视频链接、播放列表链接或频道 Handle/URL");
    return;
  }
  currentSubPlatform = 'youtube';
  const btn = document.getElementById('btnSearchYt');
  btn.disabled = true;
  btn.textContent = "正在解析 YouTube...";

  try {
    const res = await fetch('/api/youtube/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query })
    });
    const data = await readApiResponse(res, "解析 YouTube 失败");

    if (data.result_type === 'video') {
      // Single video result
      currentSingleYtVideo = data.video;
      document.getElementById('ytSingleTitle').textContent = data.video.title;
      document.getElementById('ytSingleChannel').textContent = data.video.channel;
      document.getElementById('ytSingleDate').textContent = data.video.upload_date || '近期';
      document.getElementById('ytSingleDuration').textContent = data.video.duration_str || '00:00';
      
      const coverEl = document.getElementById('ytSingleCover');
      coverEl.src = data.video.thumbnail || data.video.pic;
      coverEl.onerror = function() { this.src = '/api/proxy_img?url=' + encodeURIComponent(data.video.thumbnail); };

      document.getElementById('ytSingleVideoCard').classList.remove('hidden');
      showToast(`已识别单集视频: 《${data.video.title}》`);
    } else {
      // Channel or Playlist result -> Open Unified Sub Modal!
      document.getElementById('ytSingleVideoCard').classList.add('hidden');
      currentMid = data.channel.id;
      currentRawVideos = data.videos;

      const avatarEl = document.getElementById('upAvatar');
      avatarEl.src = data.channel.avatar || data.channel.face || '/favicon.ico';
      avatarEl.onerror = function() { this.src = '/api/proxy_img?url=' + encodeURIComponent(data.channel.avatar); };

      document.getElementById('unifiedSubModalTitle').textContent = `⭐ 配置 YouTube 频道【${data.channel.name}】订阅 / 提取`;
      document.getElementById('upName').textContent = data.channel.name;
      document.getElementById('upMid').textContent = `ID: ${data.channel.id}`;
      document.getElementById('upSign').textContent = data.channel.description || "";
      document.getElementById('upTotalVideos').textContent = data.total;

      document.getElementById('subDurationMinInput').value = 0;
      document.getElementById('subKeywordInput').value = '';
      document.getElementById('subHistoryCountInput').value = 0;
      document.getElementById('subKeepCountInput').value = 0;

      document.getElementById('unifiedSubModal').classList.remove('hidden');
      applyFiltersAndRender();
    }
  } catch (err) {
    showToast("解析 YouTube 失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="icon">🔍</span> 解析 YouTube';
  }
}

// ----------------- Single YouTube Video Extraction -----------------
async function handleExtractSingleYt() {
  if (!currentSingleYtVideo) return;
  const btn = document.getElementById('btnExtractSingleYt');
  btn.disabled = true;
  btn.textContent = "启动任务中...";

  try {
    const res = await fetch('/api/youtube/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel_name: currentSingleYtVideo.channel || 'YouTube',
        channel_avatar: currentSingleYtVideo.channel_avatar || '',
        videos: [currentSingleYtVideo]
      })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "启动任务失败");
    }

    startSseProgress();
  } catch (err) {
    showToast("提取失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "🎙️ 立即提取为播客音频 (Apple Podcasts 标准)";
  }
}

// ----------------- Live SSE Progress Stream -----------------
function startSseProgress() {
  const modal = document.getElementById('progressModal');
  const bar = document.getElementById('downloadProgressBar');
  const statusMsg = document.getElementById('progressStatusMsg');
  const percentText = document.getElementById('progressPercent');
  const consoleEl = document.getElementById('progressLogConsole');

  modal.classList.remove('hidden');
  bar.style.width = '0%';
  statusMsg.textContent = '准备开始任务...';
  percentText.textContent = '0%';
  consoleEl.textContent = '>>> 任务已就绪，正在连接实时状态流...\n';

  if (sseSource) {
    sseSource.close();
  }

  sseSource = new EventSource('/api/download/progress');
  
  sseSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'start') {
        statusMsg.textContent = data.message;
        consoleEl.textContent += `[START] ${data.message}\n`;
      } else if (data.type === 'item_start') {
        statusMsg.textContent = data.message;
        consoleEl.textContent += `[${data.index}/${data.total}] ${data.message}\n`;
      } else if (data.type === 'item_progress') {
        const pct = data.percent || 0;
        bar.style.width = `${pct}%`;
        percentText.textContent = `${pct}%`;
        statusMsg.textContent = `[${data.index}/${data.total}] ${data.message}`;
      } else if (data.type === 'item_complete') {
        bar.style.width = '100%';
        percentText.textContent = '100%';
        statusMsg.textContent = `[${data.index}/${data.total}] 提取成功`;
        consoleEl.textContent += `✅ ${data.message}\n`;
      } else if (data.type === 'item_error') {
        consoleEl.textContent += `❌ ${data.message}\n`;
      } else if (data.type === 'finish') {
        bar.style.width = '100%';
        percentText.textContent = '100%';
        statusMsg.textContent = '🎉 任务全部完成！';
        consoleEl.textContent += `\n🎉 ${data.message}\n`;
        sseSource.close();
        sseSource = null;
        showToast("音频提取完成并成功入库 Audiobookshelf！");
      }
      consoleEl.scrollTop = consoleEl.scrollHeight;
    } catch (err) {
      console.error("SSE parse error:", err);
    }
  };

  sseSource.onerror = () => {
    if (sseSource) {
      sseSource.close();
      sseSource = null;
    }
  };
}

// ----------------- Video Filtering & Grid Preview -----------------
function applyFiltersAndRender() {
  const minDurationMinutes = parseFloat(document.getElementById('subDurationMinInput').value) || 0;
  const minSeconds = minDurationMinutes * 60;
  const keyword = document.getElementById('subKeywordInput').value.trim().toLowerCase();

  filteredVideos = currentRawVideos.filter(v => {
    const passDuration = (v.duration_seconds || 0) >= minSeconds;
    const passKeyword = !keyword || v.title.toLowerCase().includes(keyword) || (v.description && v.description.toLowerCase().includes(keyword));
    return passDuration && passKeyword;
  });

  document.getElementById('filteredCount').textContent = filteredVideos.length;
  renderVideoGrid();
}

function renderVideoGrid() {
  const grid = document.getElementById('videoGrid');
  grid.innerHTML = '';

  if (filteredVideos.length === 0) {
    grid.innerHTML = `<div style="text-align: center; font-weight: 900; color: var(--border-color); padding: 40px;">未找到符合条件的视频</div>`;
    return;
  }

  const MAX_PREVIEW = 300;
  const previewList = filteredVideos.slice(0, MAX_PREVIEW);

  previewList.forEach(v => {
    const card = document.createElement('div');
    const isPaid = v.is_paid || v.disabled;
    card.className = `video-card ${isPaid ? 'disabled' : ''}`;

    const dateStr = v.upload_date ? v.upload_date : (v.created ? new Date(v.created * 1000).toLocaleDateString() : '');

    let picUrl = v.pic || v.thumbnail || '';
    if (typeof picUrl === 'string') {
      if (picUrl.startsWith('http://')) picUrl = 'https://' + picUrl.substring(7);
      if (picUrl.startsWith('//')) picUrl = 'https:' + picUrl;
    }

    card.innerHTML = `
      <div class="cover-wrapper">
        <img src="${picUrl}" alt="${v.title}" loading="lazy" onerror="this.onerror=null;this.src='/api/proxy_img?url=${encodeURIComponent(picUrl)}';">
        <span class="duration-badge">${v.duration_str || v.length || '00:00'}</span>
        ${isPaid ? `<span class="pay-badge">${v.pay_badge || '付费专属'}</span>` : ''}
      </div>
      <div class="card-content">
        <div class="video-title" title="${v.title}">${v.title}</div>
        <div class="card-footer" style="justify-content: flex-start; color: var(--text-sub); font-weight: 700;">
          <span class="video-date">${dateStr}</span>
        </div>
      </div>
    `;
    grid.appendChild(card);
  });

  if (filteredVideos.length > MAX_PREVIEW) {
    const tip = document.createElement('div');
    tip.style.cssText = 'text-align:center; padding:10px; font-size:12px; color:var(--text-muted); font-weight:bold;';
    tip.textContent = `列表仅预览前 ${MAX_PREVIEW} 集（共 ${filteredVideos.length} 集），筛选与「全部」历史下载均对全部集数生效`;
    grid.appendChild(tip);
  }
}

// ----------------- Confirm Add Subscription (Unified) -----------------
async function confirmAddSubscription() {
  if (!currentMid) return;
  const upName = document.getElementById('upName').textContent;
  const upAvatar = document.getElementById('upAvatar').src;
  const minDuration = parseFloat(document.getElementById('subDurationMinInput').value) || 0;
  const kwStr = document.getElementById('subKeywordInput').value.trim();
  const keywords = kwStr ? kwStr.split(/[,，\s]+/).filter(k => k) : [];

  document.getElementById('btnConfirmSub').disabled = true;
  document.getElementById('btnConfirmSub').textContent = "提交中...";

  try {
    const keepCount = parseInt(document.getElementById('subKeepCountInput').value) || 0;
    const historyCount = parseInt(document.getElementById('subHistoryCountInput').value) || 0;

    let matched = currentRawVideos.filter(v => {
      if (v.is_paid || v.disabled) return false;
      if ((v.duration_seconds || 0) < minDuration * 60) return false;
      if (keywords.length > 0) {
        const text = (v.title + " " + (v.description || "")).toLowerCase();
        if (!keywords.some(k => text.includes(k.toLowerCase()))) return false;
      }
      return true;
    });
    
    const toDownload = historyCount > 0 ? matched.slice(0, historyCount) : [];
    const toDownloadIds = toDownload.map(v => v.id || v.bvid);

    const isYt = currentSubPlatform === 'youtube';

    const res = await fetch('/api/subscriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mid: currentMid,
        up_name: upName,
        up_avatar: upAvatar,
        platform: isYt ? 'youtube' : 'bilibili',
        min_duration_minutes: minDuration,
        keywords: keywords,
        auto_download: true,
        keep_count: keepCount
      })
    });
    if (!res.ok) throw new Error("保存订阅失败");
    
    document.getElementById('unifiedSubModal').classList.add('hidden');

    if (toDownload.length > 0) {
      if (isYt) {
        await fetch('/api/youtube/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            channel_name: upName,
            channel_avatar: upAvatar,
            videos: toDownload
          })
        });
      } else {
        await fetch('/api/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mid: parseInt(currentMid), bvid_list: toDownloadIds })
        });
      }
      startSseProgress();
    } else {
      showToast(`已成功添加【${upName}】的自动更新订阅！\n保留模式: ${keepCount === 0 ? '全部永久保留' : keepCount + '集'}，系统将每 15 分钟自动监听新视频。`);
    }

  } catch (err) {
    showToast("添加订阅失败: " + err.message);
  } finally {
    document.getElementById('btnConfirmSub').disabled = false;
    document.getElementById('btnConfirmSub').textContent = "确定订阅 / 下载";
  }
}

// ----------------- Subscriptions Management List -----------------
async function showSubModal() {
  document.getElementById('subModal').classList.remove('hidden');
  await loadSubscriptions();
}

function closeSubModal() {
  document.getElementById('subModal').classList.add('hidden');
}

async function loadSubscriptions() {
  const container = document.getElementById('subListContainer');
  container.innerHTML = '<div style="text-align: center; color: var(--text-sub); padding: 20px;">正在加载订阅列表...</div>';

  try {
    const res = await fetch('/api/subscriptions');
    const allSubs = await res.json();

    if (!allSubs || allSubs.length === 0) {
      container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 30px;">暂无订阅。解析 UP 主/YouTube 频道后点击“确定订阅”即可添加。</div>';
      return;
    }

    const subs = allSubs.filter(s => {
      if (subPlatformFilter === 'bilibili') return (s.platform || 'bilibili') === 'bilibili';
      if (subPlatformFilter === 'youtube') return s.platform === 'youtube';
      return true;
    });

    if (subs.length === 0) {
      container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 30px;">暂无 ${subPlatformFilter === 'youtube' ? 'YouTube' : 'B站'} 订阅</div>`;
      return;
    }

    container.innerHTML = '';
    subs.forEach(s => {
      const isYt = s.platform === 'youtube';
      const card = document.createElement('div');
      card.className = 'sub-card';
      card.style.cursor = 'pointer';
      
      const badgeHtml = isYt 
        ? `<span class="platform-badge badge-youtube">YouTube</span>`
        : `<span class="platform-badge badge-bili">B站</span>`;

      card.innerHTML = `
        <img class="sub-avatar" style="width:50px; height:50px; border-radius:0; border: 4px solid var(--border-color); object-fit:cover; flex-shrink: 0;" src="${s.up_avatar || '/favicon.ico'}" alt="${s.up_name}" onerror="this.onerror=null;this.src='/api/proxy_img?url=${encodeURIComponent(s.up_avatar)}';">
        <div style="flex: 1; min-width: 0; overflow: hidden;">
          <div style="display: flex; align-items: center; gap: 6px;">
            ${badgeHtml}
            <div class="sub-name" style="font-size: 15px; font-weight:bold; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${s.up_name}</div>
          </div>
        </div>
        <div style="display:flex; align-items:center; gap: 8px;">
          <span style="background: var(--bg-color); border: 2px solid var(--border-color); padding: 4px 10px; font-size: 12px; font-weight: 900; color: var(--border-color);">已转存: ${s.downloaded_count || 0} 首 ↗</span>
          <button class="btn btn-secondary btn-sm btn-quick-remove" style="width:28px; height:28px; padding:0; display:flex; justify-content:center; align-items:center; background: var(--accent-1); color: white;" title="取消订阅并清理">❌</button>
        </div>
      `;
      
      card.querySelector('.btn-quick-remove').addEventListener('click', (e) => {
        e.stopPropagation();
        quickRemoveSub(s.id || s.mid);
      });
      card.addEventListener('click', () => openSubDetailModal(s));
      container.appendChild(card);
    });

  } catch (err) {
    container.innerHTML = `<div style="color: #EF4444; text-align: center;">加载订阅列表失败: ${err.message}</div>`;
  }
}

async function quickRemoveSub(mid) {
  if (!confirm(`确定要彻底取消订阅并清理全部文件吗？\n\n警告：这将会同步删除服务器本地该频道的整个文件夹！此操作不可逆。`)) return;
  try {
    const res = await fetch(`/api/subscriptions/${mid}`, { method: 'DELETE' });
    if (!res.ok) throw new Error("删除失败");
    loadSubscriptions();
  } catch (err) {
    showToast("删除失败: " + err.message);
  }
}

async function checkSingleSub(mid) {
  try {
    const res = await fetch('/api/subscriptions/check?mid=' + encodeURIComponent(mid), { method: 'POST' });
    const data = await res.json();
    const result = data.results[0];
    showToast(`检查完成！获取到 ${result.downloaded_count} 个符合规则的新单集。`);
    loadSubscriptions();
  } catch (err) {
    showToast("检查失败: " + err.message);
  }
}

async function checkAllSubsNow() {
  const btn = document.getElementById('btnCheckAllSubsNow');
  btn.disabled = true;
  btn.textContent = "全量检查中...";
  try {
    const res = await fetch('/api/subscriptions/check', { method: 'POST' });
    const data = await res.json();
    let totalNew = 0;
    data.results.forEach(r => { totalNew += (r.downloaded_count || 0); });
    showToast(`全量检查完成！共处理获得 ${totalNew} 个新单集。`);
    loadSubscriptions();
  } catch (err) {
    showToast("全量检查失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "⚡ 立即全量检查更新";
  }
}

// ----------------- Sub Detail Modal -----------------
async function openSubDetailModal(s) {
  const mid = s.id || s.mid;
  const upName = s.up_name;
  
  currentLocalFilesMid = mid;
  currentLocalFilesUpName = upName;
  
  document.getElementById('subModal').classList.add('hidden');
  const modal = document.getElementById('subDetailModal');
  modal.classList.remove('hidden');
  
  document.getElementById('subDetailAvatar').src = s.up_avatar || '/favicon.ico';
  document.getElementById('subDetailAvatar').onerror = function() { this.src = '/api/proxy_img?url=' + encodeURIComponent(s.up_avatar); };
  document.getElementById('subDetailName').textContent = upName;
  document.getElementById('subDetailMid').textContent = `(${s.platform === 'youtube' ? 'YouTube ID' : 'MID'}: ${mid})`;
  
  const baseUrl = window.location.origin;
  const rssNative = `${baseUrl}/rss/${encodeURIComponent(upName)}`;
  document.getElementById('subDetailRss').textContent = rssNative;
  document.getElementById('btnCopyRss').onclick = () => {
    navigator.clipboard.writeText(rssNative);
    showToast('播客 RSS 订阅链接已复制！');
  };
  
  document.getElementById('subDetailMinDuration').value = s.min_duration_minutes || 0;
  document.getElementById('subDetailKeywords').value = (s.keywords && s.keywords.length) ? s.keywords.join(', ') : '';
  document.getElementById('subDetailKeepCount').value = s.keep_count || 0;
  
  document.getElementById('btnSaveSubRules').onclick = () => saveSubRules(mid);
  document.getElementById('btnCheckSingleSubDetail').onclick = () => checkSingleSub(mid);
  document.getElementById('btnRegenCoverSubDetail').onclick = () => regenCover(mid);
  document.getElementById('btnDeleteSubDetail').onclick = () => removeSub(mid);
  
  document.getElementById('localFilesSelectedCount').textContent = `已选: 0`;
  await loadLocalFiles(mid);
}

async function saveSubRules(mid) {
  const btn = document.getElementById('btnSaveSubRules');
  const minDuration = parseFloat(document.getElementById('subDetailMinDuration').value) || 0;
  const kwStr = document.getElementById('subDetailKeywords').value.trim();
  const keywords = kwStr ? kwStr.split(/[,，\s]+/).filter(k => k) : [];
  const keepCount = parseInt(document.getElementById('subDetailKeepCount').value) || 0;
  
  btn.disabled = true;
  btn.textContent = "保存中...";
  
  try {
    const res = await fetch(`/api/subscriptions/${encodeURIComponent(mid)}/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        min_duration_minutes: minDuration,
        keywords: keywords,
        keep_count: keepCount
      })
    });
    if (!res.ok) throw new Error("保存失败");
    showToast("规则已保存！下一次后台轮询将应用新规则。");
    loadSubscriptions();
  } catch (err) {
    showToast("保存失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "💾 保存";
  }
}

async function loadLocalFiles(mid) {
  const container = document.getElementById('localFilesListContainer');
  container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 30px;">正在加载音频列表...</div>';
  
  try {
    const res = await fetch(`/api/subscriptions/${encodeURIComponent(mid)}/files`);
    if (!res.ok) throw new Error("获取文件列表失败");
    const data = await res.json();
    const files = data.files;
    
    if (!files || files.length === 0) {
      container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 30px;">该频道暂无已下载的本地音频。</div>';
      return;
    }
    
    container.innerHTML = '';
    files.forEach(f => {
      const item = document.createElement('label');
      item.className = 'local-file-item';
      item.style.display = 'flex';
      item.style.alignItems = 'center';
      item.style.gap = '10px';
      item.style.padding = '8px';
      item.style.background = 'rgba(0,0,0,0.02)';
      item.style.border = '1px solid var(--border-color)';
      item.style.cursor = 'pointer';
      
      const dateStr = new Date(f.mtime * 1000).toLocaleString();
      
      item.innerHTML = `
        <input type="checkbox" class="local-file-checkbox" value="${f.filename}" style="width: 18px; height: 18px; accent-color: var(--accent-1);">
        <div style="flex: 1; overflow: hidden;">
          <div style="font-size: 13px; font-weight: 700; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${f.filename}">${f.filename}</div>
          <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">
            <span style="display:inline-block; width: 70px;">${f.size_mb} MB</span>
            <span>🕒 ${dateStr}</span>
          </div>
        </div>
      `;
      
      item.querySelector('input').addEventListener('change', updateLocalFilesSelectedCount);
      container.appendChild(item);
    });
  } catch (err) {
    container.innerHTML = `<div style="text-align: center; color: #EF4444; padding: 30px;">加载失败: ${err.message}</div>`;
  }
}

function updateLocalFilesSelectedCount() {
  const count = document.querySelectorAll('.local-file-checkbox:checked').length;
  document.getElementById('localFilesSelectedCount').textContent = `已选: ${count}`;
}

async function deleteSelectedFiles() {
  const checkboxes = document.querySelectorAll('.local-file-checkbox:checked');
  if (checkboxes.length === 0) {
    showToast("请先勾选需要删除的音频");
    return;
  }
  
  const filenames = Array.from(checkboxes).map(cb => cb.value);
  if (!confirm(`确定要永久删除这 ${filenames.length} 个音频文件吗？\n（删除后不会再次被自动下载）`)) {
    return;
  }
  
  const btn = document.getElementById('btnDeleteSelectedFiles');
  btn.disabled = true;
  btn.textContent = "删除中...";
  
  try {
    const res = await fetch(`/api/subscriptions/${encodeURIComponent(currentLocalFilesMid)}/files/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filenames })
    });
    
    if (!res.ok) throw new Error("删除请求失败");
    const data = await res.json();
    
    if (data.errors && data.errors.length > 0) {
      showToast(`部分文件删除失败:\n${data.errors.join('\n')}`);
    } else {
      showToast(`成功删除了 ${data.deleted_count} 个音频！`);
    }
    
    await loadLocalFiles(currentLocalFilesMid);
    loadSubscriptions(); 
  } catch (err) {
    showToast("删除出错: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "🗑️ 删除";
  }
}

async function regenCover(mid) {
  const btn = document.getElementById('btnRegenCoverSubDetail');
  btn.disabled = true;
  btn.textContent = "更新中...";
  try {
    const res = await fetch(`/api/subscriptions/${encodeURIComponent(mid)}/cover`, { method: 'POST' });
    if (!res.ok) throw new Error("服务器处理失败");
    showToast("专辑封面已成功更新并保存到目录！");
  } catch (err) {
    showToast("封面更新失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "🔄 更新封面";
  }
}

async function removeSub(mid) {
  if (!confirm(`确定要彻底取消订阅并清理全部文件吗？\n\n警告：这将会同步删除服务器本地该频道的整个文件夹（包含所有已下载的音频和封面）！此操作不可逆。`)) return;

  const btn = document.getElementById('btnDeleteSubDetail');
  btn.disabled = true;
  btn.textContent = "清理中...";

  try {
    const res = await fetch(`/api/subscriptions/${encodeURIComponent(mid)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error("删除失败");
    showToast("已彻底删除该订阅及所有本地文件。");
    document.getElementById('subDetailModal').classList.add('hidden');
    showSubModal();
  } catch (err) {
    showToast("删除失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "🚨 取消订阅";
  }
}

// ----------------- Followed UPs (B站) -----------------
async function showFollowingsModal() {
  const titleEl = document.getElementById('followingsModalTitle');
  if (titleEl) titleEl.textContent = "❤️ 我关注的 UP 主 (B站)";
  document.getElementById('followingsModal').classList.remove('hidden');
  const container = document.getElementById('followingsListContainer');
  container.innerHTML = '<div style="text-align: center; color: var(--border-color); font-weight: 900; padding: 30px;">正在拉取关注列表...</div>';

  try {
    const res = await fetch('/api/up/followings');
    if (!res.ok) {
      if (res.status === 401) throw new Error("请先扫码登录");
      throw new Error("获取关注列表失败");
    }
    const resData = await res.json();
    const list = resData.data.list;

    if (!list || list.length === 0) {
      container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 30px;">你还没有关注任何 UP 主</div>';
      return;
    }

    container.innerHTML = '';
    list.forEach(up => {
      const card = document.createElement('div');
      card.className = 'sub-card';
      card.style.cursor = 'pointer';
      
      const avatar = up.face ? (up.face.startsWith('http://') ? 'https://' + up.face.substring(7) : up.face) : '';
      const sign = up.sign || '无简介';

      card.innerHTML = `
        <div class="sub-card-info" style="pointer-events: none; display: flex; align-items: center; gap: 14px; width: 100%;">
          <img class="sub-avatar" style="width: 44px; height: 44px; border-radius: 0; border: 3px solid var(--border-color); object-fit: cover; flex-shrink: 0;" src="${avatar}" alt="${up.uname}" onerror="this.onerror=null;this.src='/api/proxy_img?url=${encodeURIComponent(avatar)}';">
          <div style="flex: 1; min-width: 0; overflow: hidden;">
            <div class="sub-name" style="font-size: 15px; font-weight: 900; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${up.uname}</div>
            <div class="sub-meta" style="font-size: 12px; margin-top: 2px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${sign}">${sign}</div>
          </div>
        </div>
      `;

      card.addEventListener('click', () => {
        document.getElementById('upQueryInput').value = up.mid;
        document.getElementById('followingsModal').classList.add('hidden');
        handleUpSearch();
      });

      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = `<div style="color: #EF4444; text-align: center;">加载失败: ${err.message}</div>`;
  }
}

// ----------------- Followed Channels (YouTube) -----------------
async function showYtChannelsModal() {
  const titleEl = document.getElementById('followingsModalTitle');
  if (titleEl) titleEl.textContent = "❤️ 我关注的 YouTube 频道";
  document.getElementById('followingsModal').classList.remove('hidden');
  const container = document.getElementById('followingsListContainer');
  container.innerHTML = '<div style="text-align: center; color: var(--border-color); font-weight: 900; padding: 30px;">正在拉取 YouTube 关注频道列表...</div>';

  try {
    const res = await fetch('/api/youtube/channels');
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "请先配置有效 YouTube Cookie");
    }
    const resData = await res.json();
    const list = resData.data.list;

    if (!list || list.length === 0) {
      container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 30px;">未查询到任何关注频道 (请确保已配置有效 YouTube Cookie)</div>';
      return;
    }

    container.innerHTML = '';
    list.forEach(c => {
      const card = document.createElement('div');
      card.className = 'sub-card';
      card.style.cursor = 'pointer';
      
      const avatar = c.avatar || c.face || '';
      const sign = c.sign || 'YouTube 创作者频道';

      card.innerHTML = `
        <div class="sub-card-info" style="pointer-events: none; display: flex; align-items: center; gap: 14px; width: 100%;">
          <img class="sub-avatar" style="width: 44px; height: 44px; border-radius: 0; border: 3px solid var(--border-color); object-fit: cover; flex-shrink: 0;" src="${avatar}" alt="${c.name}" onerror="this.onerror=null;this.src='/api/proxy_img?url=${encodeURIComponent(avatar)}';">
          <div style="flex: 1; min-width: 0; overflow: hidden;">
            <div class="sub-name" style="font-size: 15px; font-weight: 900; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${c.name}</div>
            <div class="sub-meta" style="font-size: 12px; margin-top: 2px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${sign}">${sign}</div>
          </div>
        </div>
      `;

      card.addEventListener('click', () => {
        document.getElementById('ytQueryInput').value = c.url || c.id;
        document.getElementById('followingsModal').classList.add('hidden');
        handleYtSearch();
      });

      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = `<div style="color: #EF4444; text-align: center;">加载失败: ${err.message}</div>`;
  }
}
