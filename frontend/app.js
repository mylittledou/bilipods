let currentMid = null;
let currentRawVideos = [];
let filteredVideos = [];
let selectedBvids = new Set();
let qrPollTimer = null;
let currentQrKey = null;

function showToast(msg) {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; top: 20px; left: 50%; transform: translateX(-50%) translateY(-100px);
    background: var(--accent-1); color: white; border: 4px solid var(--border-color);
    box-shadow: 8px 8px 0px 0px var(--border-color); padding: 12px 24px;
    font-weight: 900; z-index: 10000; opacity: 0; transition: all 0.3s;
    max-width: 80%; text-align: center; word-break: break-word; white-space: pre-wrap;
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
  }, 3000);
}

document.addEventListener('DOMContentLoaded', () => {
  initAuthStatus();
  setupEventListeners();
});

// 1. Auth Status & QR Login
async function initAuthStatus() {
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
    }
  } catch (err) {
    console.error("Auth status check failed:", err);
  }
}

function setupEventListeners() {
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

  document.getElementById('btnSearchUp').addEventListener('click', handleUpSearch);
  document.getElementById('upQueryInput').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleUpSearch();
  });

  document.getElementById('subDurationMinInput').addEventListener('input', applyFiltersAndRender);
  document.getElementById('subKeywordInput').addEventListener('input', applyFiltersAndRender);

  document.getElementById('btnShowSubs').addEventListener('click', showSubModal);
  document.getElementById('btnCloseSubModal').addEventListener('click', closeSubModal);
  document.getElementById('btnCheckAllSubsNow').addEventListener('click', checkAllSubsNow);
  
  // Sub Detail & Local Files Modal listeners
  document.getElementById('btnCloseSubDetail').addEventListener('click', () => {
    document.getElementById('subDetailModal').classList.add('hidden');
    document.getElementById('subModal').classList.remove('hidden'); // Show subModal again
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

  document.getElementById('btnShowFollowed').addEventListener('click', showFollowingsModal);
  document.getElementById('btnCloseFollowings').addEventListener('click', () => {
    document.getElementById('followingsModal').classList.add('hidden');
  });

  document.getElementById('btnCloseUnifiedSub').addEventListener('click', () => {
    document.getElementById('unifiedSubModal').classList.add('hidden');
  });

  document.getElementById('btnConfirmSub').addEventListener('click', confirmAddSubscription);
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
      showToast("登录成功！");
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

// Cookie Login
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

// 2. UP Search
async function performUpSearch(query) {
  document.getElementById('btnSearchUp').disabled = true;
  document.getElementById('btnSearchUp').textContent = "正在深度拉取全部视频(可能需要几秒)...";

  try {
    const res = await fetch(`/api/up/search?query=${encodeURIComponent(query)}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "解析失败");
    }
    const data = await res.json();

    currentMid = data.up_info.mid;
    currentRawVideos = data.videos;

    // Render UP Profile
    const avatarUrl = data.up_info.face ? (data.up_info.face.startsWith('http://') ? 'https://' + data.up_info.face.substring(7) : data.up_info.face) : '';
    const avatarEl = document.getElementById('upAvatar');
    avatarEl.src = avatarUrl;
    avatarEl.onerror = () => { avatarEl.src = `/api/proxy_img?url=${encodeURIComponent(avatarUrl)}`; };

    document.getElementById('upName').textContent = data.up_info.name;
    document.getElementById('upMid').textContent = `MID: ${data.up_info.mid}`;
    document.getElementById('upSign').textContent = data.up_info.sign || "无个人简介";
    document.getElementById('upTotalVideos').textContent = data.total;

    // Open Unified Modal
    document.getElementById('subDurationMinInput').value = 0;
    document.getElementById('subKeywordInput').value = '';
    document.getElementById('subHistoryCountInput').value = 0;
    
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

async function handleUpSearch() {
  const query = document.getElementById('upQueryInput').value.trim();
  if (!query) {
    showToast("请输入 UP 主主页链接或数字 MID");
    return;
  }
  await performUpSearch(query);
}

// 3. Filtering & Rendering (Preview in Modal)
function applyFiltersAndRender() {
  const minDurationMinutes = parseFloat(document.getElementById('subDurationMinInput').value) || 0;
  const minSeconds = minDurationMinutes * 60;
  const keyword = document.getElementById('subKeywordInput').value.trim().toLowerCase();

  filteredVideos = currentRawVideos.filter(v => {
    const passDuration = v.duration_seconds >= minSeconds;
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

  filteredVideos.forEach(v => {
    const card = document.createElement('div');
    const isPaid = v.is_paid || v.disabled;
    card.className = `video-card ${isPaid ? 'disabled' : ''}`;

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
        <div class="card-footer" style="justify-content: flex-start; color: var(--text-sub); font-weight: 700;">
          <span class="video-date">${dateStr}</span>
        </div>
      </div>
    `;
    grid.appendChild(card);
  });
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
    let historyCount = parseInt(document.getElementById('subHistoryCountInput').value) || 0;
    let matched = currentRawVideos.filter(v => {
      if (v.is_paid) return false;
      if (v.duration_seconds < minDuration * 60) return false;
      if (keywords.length > 0) {
        const text = (v.title + " " + (v.description || "")).toLowerCase();
        if (!keywords.some(k => text.includes(k.toLowerCase()))) return false;
      }
      return true;
    });
    
    const toDownload = matched.slice(0, historyCount).map(v => v.bvid);
    // Ignore all other videos that were fetched so they don't get downloaded in the background check later!
    const toIgnore = currentRawVideos.map(v => v.bvid).filter(bvid => !toDownload.includes(bvid));

    const res = await fetch('/api/subscriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mid: currentMid,
        up_name: upName,
        up_avatar: upAvatar,
        min_duration_minutes: minDuration,
        keywords: keywords,
        auto_download: true,
        ignore_bvids: toIgnore,
        keep_count: historyCount
      })
    });
    if (!res.ok) throw new Error("保存订阅失败");
    
    let historyMsg = "";
    if (historyCount > 0 && toDownload.length > 0) {
      const dlRes = await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mid: currentMid, bvid_list: toDownload })
      });
      if (dlRes.ok) {
        historyMsg = `\n\n✅ 附加任务：已自动为您挑选最新的 ${toDownload.length} 个历史音频并加入下载队列！`;
      } else {
        historyMsg = `\n\n⚠️ 附加任务：未在历史视频中找到符合条件的音频。`;
      }
    }

    showToast(`已成功添加【${upName}】的自动更新订阅！\n系统将每 15 分钟后台轮询新上传的非付费视频（时长 > ${minDuration} 分钟${keywords.length ? '，匹配关键字: ' + keywords.join('/') : ''}）。${historyMsg}`);
    document.getElementById('unifiedSubModal').classList.add('hidden');
  } catch (err) {
    showToast("添加订阅失败: " + err.message);
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

    let globalSubsData = subs; // store for openSubDetailModal

    container.innerHTML = '';
    subs.forEach(s => {
      const card = document.createElement('div');
      card.className = 'sub-card';
      card.style.cursor = 'pointer';
      card.style.display = 'flex';
      card.style.alignItems = 'center';
      card.style.gap = '15px';
      
      card.innerHTML = `
        <img class="sub-avatar" style="width:50px; height:50px; border-radius:0; border: 4px solid var(--border-color); object-fit:cover; flex-shrink: 0;" src="${s.up_avatar || '/favicon.ico'}" alt="${s.up_name}" onerror="this.onerror=null;this.src='/api/proxy_img?url=${encodeURIComponent(s.up_avatar)}';">
        <div style="flex: 1; min-width: 0; overflow: hidden;">
          <div class="sub-name" style="font-size: 16px; font-weight:bold; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${s.up_name}</div>
        </div>
        <div style="display:flex; align-items:center; gap: 8px;">
          <span style="background: var(--bg-color); border: 2px solid var(--border-color); padding: 4px 10px; font-size: 12px; font-weight: 900; color: var(--border-color);">已转存: ${s.downloaded_count || 0} 首 ↗</span>
          <button class="btn btn-secondary btn-sm btn-quick-remove" style="width:28px; height:28px; padding:0; display:flex; justify-content:center; align-items:center; background: var(--accent-1); color: white;" title="取消订阅并清理">❌</button>
        </div>
      `;
      
      card.querySelector('.btn-quick-remove').addEventListener('click', (e) => {
        e.stopPropagation();
        quickRemoveSub(s.mid);
      });
      card.addEventListener('click', () => openSubDetailModal(s));
      container.appendChild(card);
    });

  } catch (err) {
    container.innerHTML = `<div style="color: #EF4444; text-align: center;">加载订阅列表失败: ${err.message}</div>`;
  }
}

async function quickRemoveSub(mid) {
  if (!confirm(`确定要彻底取消订阅并清理全部文件吗？\n\n警告：这将会同步删除服务器本地该 UP 主的整个文件夹！此操作不可逆。`)) return;
  try {
    const res = await fetch(`/api/subscriptions/${mid}`, { method: 'DELETE' });
    if (!res.ok) throw new Error("删除失败");
    loadSubscriptions(); // Refresh list immediately
  } catch (err) {
    showToast("删除失败: " + err.message);
  }
}

async function checkSingleSub(mid) {
  try {
    const res = await fetch('/api/subscriptions/check?mid=' + mid, { method: 'POST' });
    const data = await res.json();
    const result = data.results[0];
    showToast(`【${result.up_name}】检查完成！获取到 ${result.downloaded_count} 个符合规则的新单集。`);
    loadSubscriptions();
  } catch (err) {
    showToast("检查失败: " + err.message);
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
    showToast(`全量检查完成！共处理获得 ${totalNew} 个新单集。`);
    loadSubscriptions();
  } catch (err) {
    showToast("全量检查失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "⚡ 立即手动全量检查更新";
  }
}

// --- Sub Detail & Local Files Manager ---
let currentLocalFilesMid = null;
let currentLocalFilesUpName = null;

async function openSubDetailModal(s) {
  const mid = s.mid;
  const upName = s.up_name;
  
  currentLocalFilesMid = mid;
  currentLocalFilesUpName = upName;
  
  // Hide main subModal
  document.getElementById('subModal').classList.add('hidden');
  
  // Show subDetailModal
  const modal = document.getElementById('subDetailModal');
  modal.classList.remove('hidden');
  
  // Basic Info
  document.getElementById('subDetailAvatar').src = s.up_avatar || '/favicon.ico';
  document.getElementById('subDetailAvatar').onerror = function() { this.onerror = null; this.src = '/api/proxy_img?url=' + encodeURIComponent(s.up_avatar); };
  document.getElementById('subDetailName').textContent = upName;
  document.getElementById('subDetailMid').textContent = `(MID: ${mid})`;
  
  // RSS Link
  const baseUrl = window.location.origin;
  const rssNative = `${baseUrl}/rss/${mid}`;
  document.getElementById('subDetailRss').textContent = rssNative;
  document.getElementById('btnCopyRss').onclick = () => {
    navigator.clipboard.writeText(rssNative);
    showToast('原生 RSS 链接已复制');
  };
  
  // Rules Settings
  document.getElementById('subDetailMinDuration').value = s.min_duration_minutes || 0;
  document.getElementById('subDetailKeywords').value = (s.keywords && s.keywords.length) ? s.keywords.join(', ') : '';
  document.getElementById('subDetailKeepCount').value = s.keep_count || 0;
  
  // Re-bind actions (remove old listeners by cloning or just assigning onclick to prevent duplicates)
  document.getElementById('btnSaveSubRules').onclick = () => saveSubRules(mid);
  document.getElementById('btnCheckSingleSubDetail').onclick = () => checkSingleSub(mid);
  document.getElementById('btnDeleteSubDetail').onclick = () => {
    removeSub(mid);
  };
  
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
    const res = await fetch(`/api/subscriptions/${mid}/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        min_duration_minutes: minDuration,
        keywords: keywords,
        keep_count: keepCount
      })
    });
    if (!res.ok) throw new Error("保存失败");
    showToast("规则已保存！下一次后台检查将应用新规则。");
    // Background refresh subList so main view is updated when we go back
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
    const res = await fetch(`/api/subscriptions/${mid}/files`);
    if (!res.ok) throw new Error("获取文件列表失败");
    const data = await res.json();
    const files = data.files;
    
    if (!files || files.length === 0) {
      container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 30px;">该 UP 主暂无已下载的本地音频。</div>';
      return;
    }
    
    container.innerHTML = '';
    files.forEach(f => {
      const item = document.createElement('label');
      item.className = 'local-file-item';
      item.style.display = 'flex';
      item.style.alignItems = 'center';
      item.style.gap = '10px';
      item.style.padding = '10px';
      item.style.background = 'rgba(255,255,255,0.02)';
      item.style.borderRadius = 'var(--radius-sm)';
      item.style.cursor = 'pointer';
      
      const dateStr = new Date(f.mtime * 1000).toLocaleString();
      
      item.innerHTML = `
        <input type="checkbox" class="local-file-checkbox" value="${f.filename}" style="width: 18px; height: 18px; accent-color: var(--accent-1);">
        <div style="flex: 1; overflow: hidden;">
          <div style="font-size: 14px; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${f.filename}">${f.filename}</div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            <span style="display:inline-block; width: 80px;">${f.size_mb} MB</span>
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
    const res = await fetch(`/api/subscriptions/${currentLocalFilesMid}/files/delete`, {
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
    
    // Reload local files
    await loadLocalFiles(currentLocalFilesMid);
    // Also trigger background update of subscription count
    loadSubscriptions(); 
  } catch (err) {
    showToast("删除出错: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "🗑️ 永久删除选中的音频";
  }
}

async function removeSub(mid) {
  if (!confirm(`确定要彻底取消订阅并清理全部文件吗？\n\n警告：这将会同步删除服务器本地该 UP 主的整个文件夹（包含所有已下载的音频和封面）！此操作不可逆。`)) return;

  const btn = document.getElementById('btnDeleteSubDetail');
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "清理中...";

  try {
    const res = await fetch(`/api/subscriptions/${mid}`, { method: 'DELETE' });
    if (!res.ok) throw new Error("删除失败");
    showToast("已彻底删除该订阅及所有本地文件。");
    document.getElementById('subDetailModal').classList.add('hidden');
    showSubModal(); // Re-open list view
  } catch (err) {
    showToast("删除失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

// 6. Followed UPs
async function showFollowingsModal() {
  document.getElementById('followingsModal').classList.remove('hidden');
  const container = document.getElementById('followingsListContainer');
  container.innerHTML = '<div style="text-align: center; color: var(--border-color); font-weight: 900; padding: 30px;">正在深度拉取您账号下全量的关注列表，请耐心等待（如果您关注了非常多 UP 主，这可能需要几秒钟）...<br><br><div style="font-size:24px; animation: spin 1s linear infinite;">⏳</div></div>';

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
        <div class="sub-card-info" style="pointer-events: none; display: flex; align-items: center; gap: 16px; width: 100%;">
          <img class="sub-avatar" style="width: 50px; height: 50px; border-radius: 0; border: 4px solid var(--border-color); object-fit: cover; flex-shrink: 0;" src="${avatar}" alt="${up.uname}" onerror="this.onerror=null;this.src='/api/proxy_img?url=${encodeURIComponent(avatar)}';">
          <div style="flex: 1; min-width: 0; overflow: hidden;">
            <div class="sub-name" style="font-size: 16px; font-weight: 900; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${up.uname}</div>
            <div class="sub-meta" style="font-size: 13px; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${sign}">${sign}</div>
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

