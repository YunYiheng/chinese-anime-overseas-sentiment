// form.js —— Series / Film 通用页：筛选联动图 + 关联分析（封版）+ 评论浏览器
const FORM = document.body.dataset.form;
const SENT_CN = { positive: '正面', neutral: '中性', mixed: '混合', negative: '负面' };
const SENT_ORDER = ['positive', 'neutral', 'mixed', 'negative'];
const SENT_COLORS = { positive: '#2e7d32', neutral: '#90a4ae', mixed: '#f9a825', negative: '#c62828' };
const LIMIT = 20;
let commentOffset = 0;

const charts = {};
function getChart(id) {
  if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
  return charts[id];
}

async function fetchJSON(url) {
  const res = await fetch(url);
  return res.json();
}

function fillSelect(id, pairs) {
  document.getElementById(id).innerHTML = pairs
    .map(([v, label]) => `<option value="${v}">${label}</option>`).join('');
}

function currentParams() {
  const p = new URLSearchParams();
  const work = document.getElementById('filter-work').value;
  const platform = document.getElementById('filter-platform').value;
  const sentiment = document.getElementById('filter-sentiment').value;
  if (work) p.set('work', work);
  if (platform) p.set('platform', platform);
  if (sentiment) p.set('sentiment', sentiment);
  return p;
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function truncate(s, n) { return s.length > n ? s.slice(0, n) + '…' : s; }

// 把 post_time 统一格式化为 YYYY-MM-DD（原始 timestamp 保留在悬停里）
function formatDate(s) {
  if (!s) return '';
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);          // 2026-03-15 / ISO
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);          // MM/DD/YYYY（RT）
  if (m) return `${m[3]}-${String(+m[1]).padStart(2, '0')}-${String(+m[2]).padStart(2, '0')}`;
  m = s.match(/^([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})/); // Jul 9, 2021
  if (m) {
    const months = { Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6, Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12 };
    const mon = months[m[1].slice(0, 3)];
    if (mon) return `${m[3]}-${String(mon).padStart(2, '0')}-${String(+m[2]).padStart(2, '0')}`;
  }
  return s;
}

// ---- 筛选联动图 ----
function renderPlatformDist(data) {
  const chart = getChart('chart-platform');
  chart.setOption({
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: ps => {
        const d = data[ps[0].dataIndex];
        return `${d.platform}${d.admitted ? '' : '（未准入）'}<br/>样本量：${d.count}`;
      },
    },
    grid: { left: 90, right: 45, top: 10, bottom: 30 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: data.map(d => d.platform), inverse: true },
    series: [{
      type: 'bar', data: data.map(d => d.count),
      itemStyle: { color: p => data[p.dataIndex].admitted ? '#1565c0' : '#b0bec5' },
      label: { show: true, position: 'right' },
    }],
  });
}

function renderSentimentDist(data) {
  const chart = getChart('chart-sentiment');
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: ps => {
        const d = data[ps[0].dataIndex];
        return `${SENT_CN[d.sentiment]}<br/>占比：${d.pct}%<br/>条数：${d.count}`;
      },
    },
    grid: { left: 50, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: data.map(d => SENT_CN[d.sentiment]) },
    yAxis: { type: 'value', name: '占比（%）', max: 100 },
    series: [{
      type: 'bar', data: data.map(d => d.pct),
      itemStyle: { color: '#2e7d32' },
      label: { show: true, position: 'top', formatter: p => p.value + '%' },
    }],
  });
}

function renderTopicTop(data) {
  const chart = getChart('chart-topic');
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 130, right: 45, top: 10, bottom: 30 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: data.map(d => d.topic), inverse: true, axisLabel: { fontSize: 10 } },
    series: [{
      type: 'bar', data: data.map(d => d.count),
      itemStyle: { color: '#e65100' },
      label: { show: true, position: 'right' },
    }],
  });
}

// ---- 关联分析（封版，不随筛选变化） ----
function renderPlatformSentiment(data) {
  const chart = getChart('chart-psent');
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: SENT_ORDER.map(s => SENT_CN[s]), top: 0 },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: data.map(d => d.platform) },
    yAxis: { type: 'value', name: '评论数' },
    series: SENT_ORDER.map(sent => ({
      name: SENT_CN[sent], type: 'bar', stack: 'total',
      data: data.map(d => d[sent]),
      itemStyle: { color: SENT_COLORS[sent] },
    })),
  });
}

function renderResidual(data) {
  const chart = getChart('chart-residual');
  const platforms = data.map(d => d.platform);
  const heat = [];
  data.forEach((row, y) => SENT_ORDER.forEach((sent, x) => heat.push([x, y, row[sent]])));
  const maxAbs = Math.max(1, ...heat.map(d => Math.abs(d[2])));
  chart.setOption({
    tooltip: {
      position: 'top',
      formatter: p => `${platforms[p.value[1]]} · ${SENT_CN[SENT_ORDER[p.value[0]]]}：z = ${p.value[2].toFixed(2)}`,
    },
    grid: { left: 90, right: 30, top: 10, bottom: 60 },
    xAxis: { type: 'category', data: SENT_ORDER.map(s => SENT_CN[s]), splitArea: { show: true } },
    yAxis: { type: 'category', data: platforms, splitArea: { show: true } },
    visualMap: {
      min: -maxAbs, max: maxAbs, calculable: true, orient: 'horizontal',
      left: 'center', bottom: 0,
      inRange: { color: ['#2166ac', '#f7f7f7', '#b2182b'] },
    },
    series: [{
      type: 'heatmap', data: heat,
      label: { show: true, formatter: p => p.value[2].toFixed(1) },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } },
    }],
  });
}

// ---- 评论浏览器 ----
async function loadComments() {
  const p = currentParams();
  p.set('form', FORM);
  p.set('offset', commentOffset);
  p.set('limit', LIMIT);
  const data = await fetchJSON('/api/comments?' + p);
  renderComments(data);
}

function renderComments(data) {
  const body = document.getElementById('comments-body');
  if (data.rows.length === 0) {
    body.innerHTML = '<tr><td colspan="6" class="text-center text-muted">无评论</td></tr>';
  } else {
    body.innerHTML = data.rows.map(r => `
      <tr>
        <td><code>${r.record_id}</code></td>
        <td>${r.work}</td>
        <td>${r.platform}</td>
        <td><span class="badge" style="background:${SENT_COLORS[r.sentiment] || '#ccc'}">${SENT_CN[r.sentiment] || r.sentiment}</span></td>
        <td class="small" title="${escapeHtml(r.time)}">${formatDate(r.time)}</td>
        <td class="small" title="${escapeHtml(r.content)}">${escapeHtml(truncate(r.content, 120))}</td>
      </tr>`).join('');
  }
  const start = data.total === 0 ? 0 : commentOffset + 1;
  const end = Math.min(commentOffset + LIMIT, data.total);
  document.getElementById('comments-info').textContent = `第 ${start}–${end} 条 / 共 ${data.total} 条`;
  document.getElementById('btn-prev').disabled = commentOffset <= 0;
  document.getElementById('btn-next').disabled = commentOffset + LIMIT >= data.total;
}

async function loadData() {
  const data = await fetchJSON(`/api/${FORM}/data?` + currentParams());
  renderPlatformDist(data.platform_dist);
  renderSentimentDist(data.sentiment_dist);
  renderTopicTop(data.topic_top);
  document.getElementById('filter-total').textContent = `共 ${data.total} 条`;
  commentOffset = 0;
  await loadComments();
}

async function init() {
  const opt = await fetchJSON(`/api/${FORM}/options`);
  fillSelect('filter-work', [['', '全部作品'], ...opt.works.map(w => [w, w])]);
  fillSelect('filter-platform', [['', '全部平台'], ...opt.platforms.map(p => [p, p])]);
  fillSelect('filter-sentiment', [['', '全部情感'], ...opt.sentiments.map(s => [s, SENT_CN[s]])]);

  const bal = await fetchJSON(`/api/${FORM}/balanced`);
  document.getElementById('balanced-strip').innerHTML =
    '情感主口径 <b>platform_balanced</b>（准入平台等权）：' +
    SENT_ORDER.map(s => `${SENT_CN[s]} ${bal[s].toFixed(1)}%`).join(' · ') +
    '　—　下方三张联动图为<b>当前筛选内 pooled</b>分布，与主口径不同，勿直接比较。';

  const assoc = await fetchJSON(`/api/${FORM}/association`);
  renderPlatformSentiment(assoc.platform_sentiment);
  renderResidual(assoc.residual);

  await loadData();

  ['filter-work', 'filter-platform', 'filter-sentiment'].forEach(id =>
    document.getElementById(id).addEventListener('change', loadData));
  document.getElementById('btn-reset').addEventListener('click', () => {
    ['filter-work', 'filter-platform', 'filter-sentiment'].forEach(id => document.getElementById(id).value = '');
    loadData();
  });
  document.getElementById('btn-prev').addEventListener('click', () => {
    commentOffset = Math.max(0, commentOffset - LIMIT); loadComments();
  });
  document.getElementById('btn-next').addEventListener('click', () => {
    commentOffset += LIMIT; loadComments();
  });
}

window.addEventListener('resize', () => {
  Object.values(charts).forEach(c => c.resize());
});

init();
