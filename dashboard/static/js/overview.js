// overview.js —— 首页：拉取 KPI + 情感/平台分布并渲染
const SENT_CN = { positive: '正面', neutral: '中性', mixed: '混合', negative: '负面' };

// 缓存 ECharts 实例，供窗口缩放时统一 resize
const charts = {};
function getChart(id) {
  if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
  return charts[id];
}

async function fetchJSON(url) {
  const res = await fetch(url);
  return res.json();
}

// 1. KPI 卡片
function renderKpis(k) {
  const items = [
    ['总采集量', k.total],
    ['Series 主样本', k.series_main],
    ['Film 主样本', k.film_main],
    ['平台数', k.n_platforms],
    ['Series 作品', k.n_series_works],
    ['Film 作品', k.n_film_works],
  ];
  const row = document.getElementById('kpi-row');
  row.innerHTML = items.map(([label, value]) => `
    <div class="col-6 col-md-4 col-lg-2">
      <div class="card kpi-card">
        <div class="kpi-value">${value.toLocaleString()}</div>
        <div class="kpi-label">${label}</div>
      </div>
    </div>`).join('');
}

// 2. 情感概览图（platform_balanced 主口径）
function renderSentiment(data) {
  const chart = getChart('chart-sentiment');
  const order = ['positive', 'neutral', 'mixed', 'negative'];
  const series = order.map(k => +(data.series.platform_balanced[k] || 0));
  const film = order.map(k => +(data.film.platform_balanced[k] || 0));
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Series', 'Film'] },
    xAxis: { type: 'category', data: order.map(k => SENT_CN[k]) },
    yAxis: { type: 'value', name: '占比（%）', max: 80 },
    series: [
      { name: 'Series', type: 'bar', data: series, barGap: '10%' },
      { name: 'Film', type: 'bar', data: film },
    ],
  });
}

// 3. 平台样本量图（横向分组柱，按总量降序）
function renderPlatform(data) {
  const chart = getChart('chart-platform');
  const sMap = Object.fromEntries(data.series.map(d => [d.platform, d.count]));
  const fMap = Object.fromEntries(data.film.map(d => [d.platform, d.count]));
  const platforms = [...new Set([...Object.keys(sMap), ...Object.keys(fMap)])]
    .sort((a, b) => (sMap[b] + fMap[b]) - (sMap[a] + fMap[a]));
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['Series', 'Film'] },
    grid: { left: 100, right: 40, top: 30, bottom: 30 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: platforms, inverse: true },
    series: [
      { name: 'Series', type: 'bar', data: platforms.map(p => sMap[p] || 0) },
      { name: 'Film', type: 'bar', data: platforms.map(p => fMap[p] || 0) },
    ],
  });
}

async function init() {
  const [kpis, overview] = await Promise.all([
    fetchJSON('/api/kpis'),
    fetchJSON('/api/overview'),
  ]);
  renderKpis(kpis);
  renderSentiment(overview.sentiment);
  renderPlatform(overview.platform_dist);
}

window.addEventListener('resize', () => {
  Object.values(charts).forEach(c => c.resize());
});

init();
