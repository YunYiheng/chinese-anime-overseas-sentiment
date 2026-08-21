// association.js —— 关联分析页：读 07 封版结果，四块展示，不重算
const SENT_CN = { positive: '正面', neutral: '中性', mixed: '混合', negative: '负面' };
const SENT_ORDER = ['positive', 'neutral', 'mixed', 'negative'];

const charts = {};
function getChart(id) {
  if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
  return charts[id];
}

async function fetchJSON(url) {
  const res = await fetch(url);
  return res.json();
}

function fmtP(p) { return p < 0.001 ? '< 0.001' : p.toFixed(3); }

function statCardHTML(label, s) {
  const sparse = s.sparse
    ? `<div class="text-danger small mt-2">⚠ 稀疏表：最小期望 ${s.min_expected.toFixed(2)} &lt; 5，p 值仅供参考</div>`
    : '';
  return `
    <div class="card border h-100">
      <div class="card-body p-3">
        <h6 class="text-muted mb-2">${label}</h6>
        <div class="d-flex flex-wrap gap-3 align-items-center">
          <div><div class="text-muted small">χ²</div><div class="fs-4 fw-bold">${s.chi2.toFixed(2)}</div></div>
          <div><div class="text-muted small">p</div><div class="fs-4 fw-bold">${fmtP(s.p)}</div></div>
          <div><div class="text-muted small">Cramér's V</div><div class="fs-4 fw-bold">${s.v.toFixed(3)}</div></div>
        </div>
        <div class="small text-muted mt-2">纳入平台：${s.included}</div>
        <div class="small text-muted">排除：${s.excluded}</div>
        <div class="small text-muted">最小期望频数：${s.min_expected.toFixed(2)}</div>
        ${sparse}
      </div>
    </div>`;
}

function renderResidual(data) {
  const chart = getChart('chart-resid');
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
  }, true);
}

function renderNezhaRates(rates) {
  const chart = getChart('chart-nezha');
  chart.setOption({
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: ps => {
        const d = rates[ps[0].dataIndex];
        return `${d.platform}<br/>正面率：${d.rate}%<br/>正面 ${d.positive} / 共 ${d.total}`;
      },
    },
    grid: { left: 50, right: 30, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: rates.map(d => d.platform) },
    yAxis: { type: 'value', name: '正面率（%）', max: 100 },
    series: [{
      type: 'bar', data: rates.map(d => d.rate),
      itemStyle: { color: '#2e7d32' },
      label: { show: true, position: 'top', formatter: p => p.value + '%' },
    }],
  });
}

function renderNezhaKPI(s, four) {
  document.getElementById('nezha-kpi').innerHTML = `
    <div class="text-muted small mb-1">Positive vs Non-positive（正面率二值检验）</div>
    <div class="d-flex flex-wrap gap-3 align-items-center">
      <div><div class="text-muted small">χ²</div><div class="fs-3 fw-bold">${s.chi2.toFixed(2)}</div></div>
      <div><div class="text-muted small">p</div><div class="fs-3 fw-bold">${fmtP(s.p)}</div></div>
      <div><div class="text-muted small">Cramér's V</div><div class="fs-3 fw-bold">${s.v.toFixed(3)}</div></div>
      <div><div class="text-muted small">最小期望</div><div class="fs-3 fw-bold">${s.min_expected.toFixed(2)}</div></div>
    </div>
    <div class="small text-muted mt-2">纳入平台：${s.included}</div>
    <div class="small text-muted mt-2">四分类检验同样显著（χ²=${four.chi2.toFixed(2)}, V=${four.v.toFixed(3)}），但存在稀疏格（min expected=${four.min_expected.toFixed(2)}），仅作辅助。</div>`;
}

function renderTopicSummary(el, label, topics) {
  const sig = topics.filter(t => t.significant).length;
  document.getElementById(el).innerHTML = `
    <div class="card border bg-light h-100">
      <div class="card-body p-3 text-center">
        <h6 class="text-muted mb-2">${label}</h6>
        <div class="fs-3 fw-bold">${sig}<span class="fs-6 text-muted"> / ${topics.length}</span></div>
        <div class="small text-muted">显著主题数（Bonferroni）</div>
      </div>
    </div>`;
}

function renderTopicTable(topics) {
  const rows = topicSigOnly ? topics.filter(t => t.significant) : topics;
  document.getElementById('topic-body').innerHTML = rows.map(t => `
    <tr>
      <td>${t.topic}</td>
      <td class="text-end">${t.hits}</td>
      <td class="text-end">${t.v.toFixed(3)}</td>
      <td>${t.hi}</td>
      <td>${t.lo}</td>
      <td>${t.significant
        ? '<span class="badge bg-success">显著</span>'
        : '<span class="badge bg-secondary">不显著</span>'}</td>
    </tr>`).join('');
}

let DATA = null;
let residForm = 'series';
let topicForm = 'series';
let topicSigOnly = true;

function renderResidByForm() { renderResidual(DATA.residual[residForm]); }
function renderTopicByForm() { renderTopicTable(DATA.topics[topicForm]); }

function wireToggle(groupId, onSwitch) {
  document.querySelectorAll(`#${groupId} button`).forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll(`#${groupId} button`).forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    onSwitch(b.dataset.form);
  }));
}

async function init() {
  DATA = await fetchJSON('/api/association');

  document.getElementById('psent-series').innerHTML =
    statCardHTML('Series 平台×情感', DATA.platform_sentiment.series);
  document.getElementById('psent-film').innerHTML =
    statCardHTML('Film 平台×情感', DATA.platform_sentiment.film);
  document.getElementById('sfilm-card').innerHTML =
    statCardHTML('Series vs Film', DATA.series_vs_film);

  renderResidual(DATA.residual.series);
  renderNezhaRates(DATA.nezha_rates);
  renderNezhaKPI(DATA.nezha, DATA.nezha_fourclass);

  renderTopicSummary('topic-summary-series', 'Series', DATA.topics.series);
  renderTopicSummary('topic-summary-film', 'Film', DATA.topics.film);
  renderTopicTable(DATA.topics.series);

  wireToggle('resid-toggle', f => { residForm = f; renderResidByForm(); });
  wireToggle('topic-toggle', f => { topicForm = f; renderTopicByForm(); });
  document.getElementById('topic-sig-only').addEventListener('change', e => {
    topicSigOnly = e.target.checked;
    renderTopicByForm();
  });
}

window.addEventListener('resize', () => {
  Object.values(charts).forEach(c => c.resize());
});

init();
