let currentMid = null;
let currentRawVideos = [];
let filteredVideos = [];
let selectedBvids = new Set();
let qrPollTimer = null;
let currentQrKey = null;

document.addEventListener('DOMContentLoaded', () => {
  initAuthStatus();
  setupEventListeners();
});

// 1. Auth Status & QR Login
async function initAuthStatus() {
  try {
    const res = await fetch('/api/auth/status');
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
    }
  } catch (err) {
    console.error("Auth status check failed:", err);
  }
}

function setupEventListeners() {
  document.getElementById('btnShowQr').addEventListener('click', showQrModal);
  document.getElementById('btnCloseQr').addEventListener('click', closeQrModal);
  document.getElementById('btnRefreshQr').addEventListener('click', showQrModal);

  document.getElementById('btnSearchUp').addEventListener('click', handleUpSearch);
  document.getElementById('upQueryInput').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleUpSearch();
  });

  document.getElementById('durationMinInput').addEventListener('input', applyFiltersAndRender);
  document.getElementById('keywordInput').addEventListener('input', applyFiltersAndRender);

  document.getElementById('btnSelectAll').addEventListener('click', selectAll);
  document.getElementById('btnUnselectAll').addEventListener('click', unselectAll);
  document.getElementById('btnInvertSelect').addEventListener('click', invertSelect);

  document.getElementById('btnCopyRss').addEventListener('click', copyRssUrl);
  document.getElementById('btnAddSub').addEventListener('click', handleAddSubscription);
  document.getElementById('btnShowSubs').addEventListener('click', showSubModal);
  document.getElementById('btnCloseSubModal').addEventListener('click', closeSubModal);
  document.getElementById('btnCheckAllSubsNow').addEventListener('click', checkAllSubsNow);

  document.getElementById('btnShowFollowed').addEventListener('click', showFollowingsModal);
  document.getElementById('btnCloseFollowings').addEventListener('click', () => {
    document.getElementById('followingsModal').classList.add('hidden');
  });

  document.getElementById('btnCloseSubConfig').addEventListener('click', () => {
    document.getElementById('subConfigModal').classList.add('hidden');
  });
  document.getElementById('btnConfirmSub').addEventListener('click', confirmAddSubscription);

  document.getElementById('btnConfirmDownload').addEventListener('click', startDownload);
  document.getElementById('btnCloseProgress').addEventListener('click', () => {
    document.getElementById('progressModal').classList.add('hidden');
  });
}

// QR Login Flow
async function showQrModal() {
  document.getElementById('qrModal').classList.remove('hidden');
  document.getElementById('qrOverlay').classList.add('hidden');
  document.getElementById('qrStatusText').textContent = "正在生成登录二维码...";
  
  try {
    const res = await fetch('/api/auth/qrcode');
    const data = await res.json();
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
      // Login success
      closeQrModal();
      initAuthStatus();
      alert("登录成功！");
    } else if (data.code === 86038) {
      // Expired
      clearInterval(qrPollTimer);
      document.getElementById('qrOverlayMsg').textContent = "二维码已失效";
      document.getElementById('qrOverlay').classList.remove('hidden');
    }
  } catch (err) {
    console.error("Poll QR status error:", err);
  }
}

// 2. UP Search
async function performUpSearch(query) {
  document.getElementById('btnSearchUp').disabled = true;
  document.getElementById('btnSearchUp').textContent = "解析中...";

  try {
    const res = await fetch(`/api/up/search?query=${encodeURIComponent(query)}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "解析失败");
    }
    const data = await res.json();

    currentMid = data.up_info.mid;
    currentRawVideos = data.videos;
    selectedBvids.clear();

    // Render UP Profile
    const avatarUrl = data.up_info.face ? (data.up_info.face.startsWith('http://') ? 'https://' + data.up_info.face.substring(7) : data.up_info.face) : '';
    const avatarEl = document.getElementById('upAvatar');
    avatarEl.src = avatarUrl;
    avatarEl.onerror = () => { avatarEl.src = `/api/proxy_img?url=${encodeURIComponent(avatarUrl)}`; };

    document.getElementById('upName').textContent = data.up_info.name;
    document.getElementById('upMid').textContent = `MID: ${data.up_info.mid}`;
    document.getElementById('upSign').textContent = data.up_info.sign || "无个人简介";
    document.getElementById('upTotalVideos').textContent = data.total;

    document.getElementById('upProfileCard').classList.remove('hidden');
    document.getElementById('filterControls').classList.remove('hidden');
    document.getElementById('videoGridSection').classList.remove('hidden');

    applyFiltersAndRender();
    document.getElementById('followingsModal').classList.add('hidden');
  } catch (err) {
    alert("解析 UP 主失败: " + err.message);
  } finally {
    document.getElementById('btnSearchUp').disabled = false;
    document.getElementById('btnSearchUp').innerHTML = '<span class="icon">🔍</span> 解析 UP 主视频';
  }
}

async function handleUpSearch() {
  const query = document.getElementById('upQueryInput').value.trim();
  if (!query) {
    alert("请输入 UP 主主页链接或数字 MID");
    return;
  }
  await performUpSearch(query);
}

// 3. Filtering & Rendering
function applyFiltersAndRender() {
  const minDurationMinutes = parseFloat(document.getElementById('durationMinInput').value) || 0;
  const minSeconds = minDurationMinutes * 60;
  const keyword = document.getElementById('keywordInput').value.trim().toLowerCase();

  filteredVideos = currentRawVideos.filter(v => {
    const passDuration = v.duration_seconds >= minSeconds;
    const passKeyword = !keyword || v.title.toLowerCase().includes(keyword) || (v.description && v.description.toLowerCase().includes(keyword));
    return passDuration && passKeyword;
  });

  document.getElementById('upFilteredVideos').textContent = filteredVideos.length;
  renderVideoGrid();
  updateSelectedSummary();
}

function renderVideoGrid() {
  const grid = document.getElementById('videoGrid');
  grid.innerHTML = '';

  if (filteredVideos.length === 0) {
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 40px;">未找到符合条件的视频</div>`;
    return;
  }

  filteredVideos.forEach(v => {
    const card = document.createElement('div');
    const isPaid = v.is_paid || v.disabled;
    card.className = `video-card ${isPaid ? 'disabled' : ''}`;

    const isChecked = selectedBvids.has(v.bvid);
    const dateStr = v.created ? new Date(v.created * 1000).toLocaleDateString() : '';

    let picUrl = v.pic || '';
    if (typeof picUrl === 'string') {
      if (picUrl.startsWith('http://')) picUrl = 'https://' + picUrl.substring(7);
      if (picUrl.startsWith('//')) picUrl = 'https:' + picUrl;
    }

    card.innerHTML = `
      <div class="cover-wrapper">
        <img src="${picUrl}" alt="${v.title}" loading="lazy" onerror="this.onerror=null;this.src='/api/proxy_img?url=${encodeURIComponent(picUrl)}';">
        <span class="duration-badge">${v.length}</span>
        ${isPaid ? `<span class="pay-badge">${v.pay_badge || '付费/充电专属'}</span>` : ''}
      </div>
      <div class="card-content">
        <div class="video-title" title="${v.title}">${v.title}</div>
        <div class="card-footer">
          <span class="video-date">${dateStr}</span>
          <input type="checkbox" class="card-checkbox" data-bvid="${v.bvid}" ${isChecked ? 'checked' : ''} ${isPaid ? 'disabled' : ''}>
        </div>
      </div>
    `;

    // Click card to toggle checkbox (if not paid)
    if (!isPaid) {
      card.addEventListener('click', (e) => {
        if (e.target.tagName !== 'INPUT') {
          const cb = card.querySelector('.card-checkbox');
          cb.checked = !cb.checked;
          toggleSelect(v.bvid, cb.checked);
        }
      });

      const cb = card.querySelector('.card-checkbox');
      cb.addEventListener('change', (e) => {
        toggleSelect(v.bvid, e.target.checked);
      });
    }

    grid.appendChild(card);
  });
}

function toggleSelect(bvid, selected) {
  if (selected) {
    selectedBvids.add(bvid);
  } else {
    selectedBvids.delete(bvid);
  }
  updateSelectedSummary();
}

function selectAll() {
  filteredVideos.forEach(v => {
    if (!v.is_paid && !v.disabled) {
      selectedBvids.add(v.bvid);
    }
  });
  renderVideoGrid();
  updateSelectedSummary();
}

function unselectAll() {
  selectedBvids.clear();
  renderVideoGrid();
  updateSelectedSummary();
}

function invertSelect() {
  filteredVideos.forEach(v => {
    if (!v.is_paid && !v.disabled) {
      if (selectedBvids.has(v.bvid)) {
        selectedBvids.delete(v.bvid);
      } else {
        selectedBvids.add(v.bvid);
      }
    }
  });
  renderVideoGrid();
  updateSelectedSummary();
}

function updateSelectedSummary() {
  const count = selectedBvids.size;
  document.getElementById('selectedCountBadge').textContent = `已选择 ${count} 个视频`;
  document.getElementById('barSelectedCount').textContent = count;

  if (count > 0) {
    document.getElementById('downloadBar').classList.remove('hidden');
  } else {
    document.getElementById('downloadBar').classList.add('hidden');
  }
}

// 4. Download & Progress Modal
async function startDownload() {
  if (selectedBvids.size === 0) {
    alert("请至少选择一个可下载的视频");
    return;
  }

  const bvidList = Array.from(selectedBvids);
  document.getElementById('progressModal').classList.remove('hidden');
  document.getElementById('downloadProgressBar').style.width = '0%';
  document.getElementById('progressPercent').textContent = '0%';
  document.getElementById('progressStatusMsg').textContent = '初始化提取任务...';

  const logConsole = document.getElementById('progressLogConsole');
  logConsole.innerHTML = '<div>> 准备启动后台音频提取任务...</div>';

  try {
    const res = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mid: currentMid, bvid_list: bvidList })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "启动失败");
    }

    // Connect SSE for progress updates
    const eventSource = new EventSource('/api/download/progress');
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      appendLog(data.message);

      if (data.type === 'item_progress') {
        const pct = data.percent;
        document.getElementById('downloadProgressBar').style.width = `${pct}%`;
        document.getElementById('progressPercent').textContent = `${pct}%`;
        document.getElementById('progressStatusMsg').textContent = data.message;
      } else if (data.type === 'finish') {
        eventSource.close();
        document.getElementById('downloadProgressBar').style.width = '100%';
        document.getElementById('progressPercent').textContent = '100%';
        document.getElementById('progressStatusMsg').textContent = "音频处理完成！";
        appendLog("✨ 提示：可以在 Audiobookshelf 引入下载目录或复制 RSS Feed 在 Apple Podcasts 格式订阅！");
      }
    };

    eventSource.onerror = (err) => {
      console.error("SSE Error:", err);
      eventSource.close();
    };

  } catch (err) {
    appendLog(`❌ 错误: ${err.message}`);
  }
}

function appendLog(msg) {
  const logConsole = document.getElementById('progressLogConsole');
  const div = document.createElement('div');
  div.textContent = `> ${msg}`;
  logConsole.appendChild(div);
  logConsole.scrollTop = logConsole.scrollHeight;
}

function copyRssUrl() {
  if (!currentMid) return;
  const rssUrl = `${window.location.origin}/rss/${currentMid}`;
  navigator.clipboard.writeText(rssUrl).then(() => {
    alert(`RSS 链接已复制到剪贴板:\n${rssUrl}\n\n可在 Apple Podcasts 或 Audiobookshelf 中作为 RSS 源添加！`);
  }).catch(() => {
    prompt("请手动复制 RSS 链接:", rssUrl);
  });
}

// 5. Subscriptions Management
async function handleAddSubscription() {
  if (!currentMid) return;
  const upName = document.getElementById('upName').textContent;
  
  document.getElementById('subConfigUpName').textContent = upName;
  document.getElementById('subDurationMinInput').value = document.getElementById('durationMinInput').value || 0;
  document.getElementById('subKeywordInput').value = document.getElementById('keywordInput').value || '';
  
  document.getElementById('subConfigModal').classList.remove('hidden');
}

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
    const res = await fetch('/api/subscriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mid: currentMid,
        up_name: upName,
        up_avatar: upAvatar,
        min_duration_minutes: minDuration,
        keywords: keywords,
        auto_download: true
      })
    });
    if (!res.ok) throw new Error("保存订阅失败");
    alert(`已成功添加【${upName}】的自动更新订阅！\n系统将每 15 分钟后台轮询新上传的非付费视频（时长 > ${minDuration} 分钟${keywords.length ? '，匹配关键字: ' + keywords.join('/') : ''}）。`);
    document.getElementById('subConfigModal').classList.add('hidden');
  } catch (err) {
    alert("添加订阅失败: " + err.message);
  } finally {
    document.getElementById('btnConfirmSub').disabled = false;
    document.getElementById('btnConfirmSub').textContent = "确定订阅";
  }
}

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
    const subs = await res.json();

    if (!subs || subs.length === 0) {
      container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 30px;">暂无订阅的 UP 主。解析 UP 主后点击“⭐ 订阅该 UP 主自动更新”即可添加。</div>';
      return;
    }

    container.innerHTML = '';
    subs.forEach(s => {
      const card = document.createElement('div');
      card.className = 'sub-card';
      const lastCheck = s.last_check_time ? new Date(s.last_check_time * 1000).toLocaleString() : '未检查';
      const kwText = (s.keywords && s.keywords.length) ? s.keywords.join('/') : '无限制';

      const baseUrl = window.location.origin;
      const rssNative = `${baseUrl}/downloads/${encodeURIComponent(s.up_name)}/rss.xml`;
      const rssAbs = `${baseUrl}/api/abs-proxy/rss?up_name=${encodeURIComponent(s.up_name)}&url=`;

      card.innerHTML = `
        <div class="sub-card-info" style="align-items: flex-start; gap: 15px;">
          <img class="sub-avatar" style="width:60px; height:60px;" src="${s.up_avatar || '/favicon.ico'}" alt="${s.up_name}" onerror="this.onerror=null;this.src='/api/proxy_img?url=${encodeURIComponent(s.up_avatar)}';">
          <div style="flex: 1;">
            <div class="sub-name" style="font-size: 16px; margin-bottom: 5px;">${s.up_name} <span style="font-size:12px; color: var(--text-muted); font-weight:normal;">(MID: ${s.mid})</span></div>
            <div class="sub-meta" style="margin-bottom: 8px;">
              <span>⏱️ > ${s.min_duration_minutes} 分钟</span>
              <span>🔑 关键字: ${kwText}</span>
              <span style="color: var(--bili-blue);">📁 本地已转存音频: ${s.downloaded_bvids ? s.downloaded_bvids.length : 0} 个</span>
            </div>
            <div style="font-size: 12px; display: flex; flex-direction: column; gap: 4px; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 4px;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:var(--text-sub);">原生 RSS 链接 (Apple Podcasts):</span>
                <button class="btn btn-text btn-sm" style="padding: 2px 6px; font-size:11px;" onclick="navigator.clipboard.writeText('${rssNative}');alert('原生 RSS 链接已复制');">复制</button>
              </div>
              <div style="color:var(--text-muted); word-break: break-all;">${rssNative}</div>
              <div style="display:flex; justify-content:space-between; align-items:center; margin-top: 5px;">
                <span style="color:var(--text-sub);">ABS 修复代理 RSS (方案A):</span>
                <button class="btn btn-text btn-sm" style="padding: 2px 6px; font-size:11px;" onclick="navigator.clipboard.writeText('${rssAbs}');alert('代理 RSS 前缀已复制，请在末尾加上 UrlEncode 后的 ABS 源链接');">复制前缀</button>
              </div>
            </div>
          </div>
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px; justify-content: center; min-width: 100px;">
          <button class="btn btn-glass btn-sm btn-check-single" data-mid="${s.mid}">⚡ 手动检查</button>
          <button class="btn btn-secondary btn-sm btn-del-sub" data-mid="${s.mid}" style="color: #EF4444; border-color: rgba(239,68,68,0.4);">删除与清理</button>
        </div>
      `;

      card.querySelector('.btn-check-single').addEventListener('click', () => checkSingleSub(s.mid));
      card.querySelector('.btn-del-sub').addEventListener('click', () => removeSub(s.mid));
      container.appendChild(card);
    });

  } catch (err) {
    container.innerHTML = `<div style="color: #EF4444; text-align: center;">加载订阅列表失败: ${err.message}</div>`;
  }
}

async function checkSingleSub(mid) {
  try {
    const res = await fetch('/api/subscriptions/check?mid=' + mid, { method: 'POST' });
    const data = await res.json();
    const result = data.results[0];
    alert(`【${result.up_name}】检查完成！获取到 ${result.downloaded_count} 个符合规则的新单集。`);
    loadSubscriptions();
  } catch (err) {
    alert("检查失败: " + err.message);
  }
}

async function checkAllSubsNow() {
  const btn = document.getElementById('btnCheckAllSubsNow');
  btn.disabled = true;
  btn.textContent = "正在量检查更新中...";
  try {
    const res = await fetch('/api/subscriptions/check', { method: 'POST' });
    const data = await res.json();
    let totalNew = 0;
    data.results.forEach(r => { totalNew += (r.downloaded_count || 0); });
    alert(`全量检查完成！共处理获得 ${totalNew} 个新单集。`);
    loadSubscriptions();
  } catch (err) {
    alert("全量检查失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "⚡ 立即手动全量检查更新";
  }
}

async function removeSub(mid) {
  if (!confirm(`确定要彻底删除该订阅吗？\n\n警告：这将会同步删除服务器本地该 UP 主的整个文件夹（包含所有已下载的音频和封面）！此操作不可逆。`)) return;

  try {
    const res = await fetch(`/api/subscriptions/${mid}`, { method: 'DELETE' });
    if (!res.ok) throw new Error("取消订阅失败");
    const data = await res.json();
    alert(data.message || "删除成功");
    loadSubscriptions();
  } catch (err) {
    alert("删除失败: " + err.message);
  }
}

// 6. Followed UPs
async function showFollowingsModal() {
  document.getElementById('followingsModal').classList.remove('hidden');
  const container = document.getElementById('followingsListContainer');
  container.innerHTML = '<div style="text-align: center; color: var(--text-sub); padding: 30px;">正在深度拉取您账号下全量的关注列表，请耐心等待（如果您关注了非常多 UP 主，这可能需要几秒钟）...<br><br><div style="font-size:24px; animation: spin 1s linear infinite;">⏳</div></div>';

  try {
    const res = await fetch('/api/up/followings');
    if (!res.ok) {
      if (res.status === 401) throw new Error("请先扫码登录");
      throw new Error("获取关注列表失败");
    }
    const resData = await res.json();
    const list = resData.data.list;

    if (!list || list.length === 0) {
      container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 30px; grid-column: 1/-1;">你还没有关注任何 UP 主</div>';
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
        <div class="sub-card-info" style="pointer-events: none;">
          <img class="sub-avatar" src="${avatar}" alt="${up.uname}" onerror="this.onerror=null;this.src='/api/proxy_img?url=${encodeURIComponent(avatar)}';">
          <div style="overflow: hidden;">
            <div class="sub-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${up.uname}</div>
            <div class="sub-meta" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${sign}">${sign}</div>
          </div>
        </div>
      `;

      card.addEventListener('click', () => {
        document.getElementById('upQueryInput').value = up.mid;
        performUpSearch(String(up.mid));
      });

      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = `<div style="color: #EF4444; text-align: center; grid-column: 1/-1;">加载失败: ${err.message}</div>`;
  }
}

