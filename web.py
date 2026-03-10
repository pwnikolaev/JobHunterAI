"""
JobHunter AI — Web Dashboard
Run: python web.py
Open: http://localhost:5000
"""
import threading
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

import db
from main import run_scrapers, is_acceptable_location, is_acceptable_language
from ai_scorer import score_vacancy

app = Flask(__name__)

# ── Scan state (shared between threads) ──────────────────────────────────────
_scan_lock = threading.Lock()
_scan_state = {
    "running": False,
    "log": [],
    "stats": {},
}


def _log(msg: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    with _scan_lock:
        _scan_state["log"].append(f"[{ts}] {msg}")


def _run_scan():
    with _scan_lock:
        _scan_state["running"] = True
        _scan_state["log"] = []
        _scan_state["stats"] = {}

    try:
        _log("Запуск скраперов...")
        vacancies = run_scrapers()
        _log(f"Найдено всего: {len(vacancies)}")

        new = skipped_geo = skipped_lang = skipped_dup = 0

        for v in vacancies:
            db.log_vacancy(
                source=v.get("source", ""),
                title=v.get("title", ""),
                url=v.get("url", ""),
                salary=v.get("salary", ""),
            )

            if not is_acceptable_location(v):
                skipped_geo += 1
                continue

            if not is_acceptable_language(v):
                skipped_lang += 1
                continue

            vid = db.insert_vacancy(
                title=v.get("title", ""),
                company=v.get("company", ""),
                url=v.get("url", ""),
                source=v.get("source", ""),
                salary=v.get("salary", ""),
                location=v.get("location", ""),
                description=v.get("description", ""),
            )

            if vid is None:
                skipped_dup += 1
                continue

            _log(f"Новая: [{v.get('source')}] {v.get('title', '')[:50]}")

            score, comment = score_vacancy(
                title=v.get("title", ""),
                company=v.get("company", ""),
                description=v.get("description", ""),
                location=v.get("location", ""),
                salary=v.get("salary", ""),
            )
            db.update_score(vid, score, comment)
            new += 1

        stats = {
            "scraped": len(vacancies),
            "new": new,
            "skipped_geo": skipped_geo,
            "skipped_lang": skipped_lang,
            "skipped_dup": skipped_dup,
        }
        _log(f"Готово. Новых: {new} | Гео: {skipped_geo} | Язык: {skipped_lang} | Дубли: {skipped_dup}")

        with _scan_lock:
            _scan_state["stats"] = stats

    except Exception as exc:
        _log(f"Ошибка: {exc}")

    finally:
        with _scan_lock:
            _scan_state["running"] = False


# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>JobHunter AI</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <script>
  var _pollTimer = null;
  var _lastLogLen = 0;
  function startScan() {
    fetch('/api/scan/start', {method: 'POST'})
      .then(function(r){ return r.json(); })
      .then(function(data) {
        if (data.error) { alert(data.error); return; }
        document.getElementById('scan-log-wrap').classList.remove('d-none');
        document.getElementById('scan-log').textContent = '';
        document.getElementById('scan-result').textContent = '';
        document.getElementById('btn-scan').disabled = true;
        document.getElementById('btn-scan').textContent = 'Парсинг...';
        _lastLogLen = 0;
        _pollTimer = setInterval(pollStatus, 1500);
      });
  }
  function pollStatus() {
    fetch('/api/scan/status')
      .then(function(r){ return r.json(); })
      .then(function(data) {
        var logEl = document.getElementById('scan-log');
        var newLines = data.log.slice(_lastLogLen);
        if (newLines.length) {
          logEl.textContent += newLines.join('\\n') + '\\n';
          logEl.scrollTop = logEl.scrollHeight;
          _lastLogLen = data.log.length;
        }
        document.getElementById('scan-status').textContent = data.running ? 'Выполняется...' : '';
        if (!data.running) {
          clearInterval(_pollTimer);
          document.getElementById('btn-scan').disabled = false;
          document.getElementById('btn-scan').textContent = 'Запустить парсер';
          if (data.stats && data.stats.new !== undefined) {
            document.getElementById('scan-result').textContent =
              'Найдено: ' + data.stats.scraped + ' | Новых: ' + data.stats.new +
              ' | Дублей: ' + data.stats.skipped_dup +
              ' | Гео: ' + data.stats.skipped_geo +
              ' | Язык: ' + data.stats.skipped_lang;
          }
          setTimeout(function(){ location.reload(); }, 2000);
        }
      });
  }
  </script>
  <style>
    body { background: #f0f2f5; }
    .navbar { background: #1a1a2e !important; }
    .navbar-brand { color: #e94560 !important; font-weight: 700; letter-spacing: 1px; }
    .stat-card { border: none; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
    .stat-card .card-body { padding: 1.2rem 1.5rem; }
    .stat-value { font-size: 2rem; font-weight: 700; color: #1a1a2e; }
    .stat-label { font-size: .8rem; color: #888; text-transform: uppercase; letter-spacing: .5px; }
    .table-card { border: none; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
    .table th { background: #1a1a2e; color: #fff; font-weight: 500; border: none; }
    .table td { vertical-align: middle; }
    .score-pill { display: inline-block; min-width: 44px; text-align: center;
                  border-radius: 20px; padding: 2px 10px; font-weight: 600; font-size: .85rem; }
    .score-high  { background: #d1fae5; color: #065f46; }
    .score-mid   { background: #fef9c3; color: #713f12; }
    .score-low   { background: #fee2e2; color: #991b1b; }
    .status-badge { font-size: .75rem; }
    .filter-bar input, .filter-bar select { border-radius: 8px; }
    nav.tabs .nav-link { color: #555; border-radius: 8px 8px 0 0; }
    nav.tabs .nav-link.active { background: #1a1a2e; color: #fff; }
    a.vacancy-link { color: #0d6efd; text-decoration: none; }
    a.vacancy-link:hover { text-decoration: underline; }
    .salary-text { color: #198754; font-weight: 500; white-space: nowrap; }
    .no-salary { color: #bbb; font-size: .85rem; }
    #scan-log { background:#1a1a2e; color:#a8ff78; font-family:monospace;
                font-size:.8rem; height:200px; overflow-y:auto; border-radius:8px;
                padding:12px; white-space:pre-wrap; }
    #scan-panel { border: none; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
  </style>
</head>
<body>

<nav class="navbar navbar-dark mb-4">
  <div class="container-fluid px-4">
    <span class="navbar-brand">⚡ JobHunter AI</span>
    <span class="text-white-50 small">Dashboard</span>
  </div>
</nav>

<div class="container-fluid px-4">

  <!-- Stats -->
  <div class="row g-3 mb-4">
    {% for s in stats_cards %}
    <div class="col-6 col-md-2">
      <div class="card stat-card">
        <div class="card-body">
          <div class="stat-value" id="stat-{{ loop.index }}">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </div>
    {% endfor %}
  </div>

  <!-- Scan panel -->
  <div class="card mb-4" id="scan-panel">
    <div class="card-body">
      <div class="d-flex align-items-center gap-3 mb-3">
        <button id="btn-scan" class="btn btn-danger px-4 fw-bold" onclick="startScan()">
          ▶ Запустить парсер
        </button>
        <div id="scan-status" class="text-muted small"></div>
      </div>
      <div id="scan-log-wrap" class="d-none">
        <div id="scan-log"></div>
        <div id="scan-result" class="mt-2 small text-muted"></div>
      </div>
    </div>
  </div>

  <!-- Tabs -->
  <ul class="nav nav-tabs tabs mb-0" id="mainTabs">
    <li class="nav-item">
      <a class="nav-link {% if tab == 'log' %}active{% endif %}" href="/?tab=log">
        Лог вакансий <span class="badge bg-secondary ms-1">{{ log_total }}</span>
      </a>
    </li>
    <li class="nav-item">
      <a class="nav-link {% if tab == 'scored' %}active{% endif %}" href="/?tab=scored">
        Обработанные AI <span class="badge bg-secondary ms-1">{{ scored_total }}</span>
      </a>
    </li>
  </ul>

  <div class="card table-card rounded-top-0">
    <div class="card-body p-0">

      <!-- Filter bar -->
      <form method="get" class="filter-bar d-flex flex-wrap gap-2 p-3 border-bottom bg-white">
        <input type="hidden" name="tab" value="{{ tab }}">
        <input name="q" value="{{ q }}" class="form-control form-control-sm" style="max-width:220px" placeholder="Поиск по названию...">
        <select name="source" class="form-select form-select-sm" style="max-width:160px">
          <option value="">Все сервисы</option>
          {% for s in sources %}
          <option {% if source_filter == s %}selected{% endif %}>{{ s }}</option>
          {% endfor %}
        </select>
        {% if tab == 'scored' %}
        <select name="status" class="form-select form-select-sm" style="max-width:140px">
          <option value="">Все статусы</option>
          {% for st in statuses %}
          <option {% if status_filter == st %}selected{% endif %}>{{ st }}</option>
          {% endfor %}
        </select>
        {% endif %}
        <button class="btn btn-sm btn-primary">Применить</button>
        <a href="/?tab={{ tab }}" class="btn btn-sm btn-outline-secondary">Сбросить</a>
      </form>

      <!-- TABLE: vacancy_log -->
      {% if tab == 'log' %}
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead>
            <tr>
              <th>#</th><th>Сервис</th><th>Название</th><th>Вилка зарплаты</th><th>Найдено</th>
            </tr>
          </thead>
          <tbody>
            {% for r in rows %}
            <tr>
              <td class="text-muted small">{{ r.id }}</td>
              <td><span class="badge bg-primary">{{ r.source }}</span></td>
              <td><a class="vacancy-link" href="{{ r.url }}" target="_blank">{{ r.title }}</a></td>
              <td>{% if r.salary %}<span class="salary-text">{{ r.salary }}</span>{% else %}<span class="no-salary">—</span>{% endif %}</td>
              <td class="text-muted small">{{ r.scraped_at[:16].replace('T', ' ') }}</td>
            </tr>
            {% else %}
            <tr><td colspan="5" class="text-center text-muted py-4">Нет данных</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <!-- TABLE: vacancies (scored) -->
      {% else %}
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead>
            <tr>
              <th>#</th><th>Сервис</th><th>Название</th><th>Компания</th>
              <th>Локация</th><th>Remote</th>
              <th>Вилка зарплаты</th><th>Оценка AI</th><th>Статус</th><th>Найдено</th>
            </tr>
          </thead>
          <tbody>
            {% for r in rows %}
            {% set loc = (r.location or '') %}
            {% set desc = (r.description or '') %}
            {% set loc_l = loc.lower() %}
            {% set desc_l = desc.lower() %}
            {% set is_remote = ('remote' in loc_l or 'remote' in desc_l or 'дистанційно' in loc_l or 'удалённо' in loc_l or 'віддалено' in loc_l) %}
            {% set clean_loc = loc.replace('Remote / ', '').replace('/ Remote', '').replace('Remote', '').strip(' /,') %}
            <tr>
              <td class="text-muted small">{{ r.id }}</td>
              <td><span class="badge bg-primary">{{ r.source }}</span></td>
              <td><a class="vacancy-link" href="{{ r.url }}" target="_blank">{{ r.title }}</a></td>
              <td class="text-muted small">{{ r.company or '—' }}</td>
              <td class="text-muted small">{{ clean_loc or '—' }}</td>
              <td>
                {% if is_remote %}
                  <span class="badge bg-success">Remote</span>
                {% else %}
                  <span class="text-muted small">—</span>
                {% endif %}
              </td>
              <td>{% if r.salary %}<span class="salary-text">{{ r.salary }}</span>{% else %}<span class="no-salary">—</span>{% endif %}</td>
              <td>
                {% set sc = r.match_score %}
                <span class="score-pill {% if sc >= 75 %}score-high{% elif sc >= 50 %}score-mid{% else %}score-low{% endif %}">{{ sc }}%</span>
              </td>
              <td>
                {% set colors = {'new':'secondary','sent':'primary','applied':'success','saved':'info','skipped':'danger'} %}
                <span class="badge status-badge bg-{{ colors.get(r.status, 'secondary') }}">{{ r.status }}</span>
              </td>
              <td class="text-muted small">{{ r.found_at[:16].replace('T', ' ') if r.found_at else '—' }}</td>
            </tr>
            {% else %}
            <tr><td colspan="10" class="text-center text-muted py-4">Нет данных</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% endif %}

      <!-- Pagination -->
      {% if total_pages > 1 %}
      <nav class="d-flex justify-content-between align-items-center px-3 py-2 border-top">
        <span class="text-muted small">Страница {{ page }} из {{ total_pages }} ({{ row_count }} записей)</span>
        <ul class="pagination pagination-sm mb-0">
          {% if page > 1 %}
          <li class="page-item"><a class="page-link" href="?tab={{ tab }}&page={{ page-1 }}&q={{ q }}&source={{ source_filter }}&status={{ status_filter }}">‹</a></li>
          {% endif %}
          {% for p in range([1, page-2]|max, [total_pages+1, page+3]|min) %}
          <li class="page-item {% if p == page %}active{% endif %}">
            <a class="page-link" href="?tab={{ tab }}&page={{ p }}&q={{ q }}&source={{ source_filter }}&status={{ status_filter }}">{{ p }}</a>
          </li>
          {% endfor %}
          {% if page < total_pages %}
          <li class="page-item"><a class="page-link" href="?tab={{ tab }}&page={{ page+1 }}&q={{ q }}&source={{ source_filter }}&status={{ status_filter }}">›</a></li>
          {% endif %}
        </ul>
      </nav>
      {% else %}
      <div class="px-3 py-2 border-top text-muted small">{{ row_count }} записей</div>
      {% endif %}

    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

PAGE_SIZE = 50


def paginate(query, params, page, page_size=PAGE_SIZE):
    with db.get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
        rows = conn.execute(
            f"{query} LIMIT ? OFFSET ?", params + [page_size, (page - 1) * page_size]
        ).fetchall()
    return rows, total


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    with _scan_lock:
        if _scan_state["running"]:
            return jsonify({"error": "Парсер уже запущен"}), 409
    threading.Thread(target=_run_scan, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/scan/status")
def api_scan_status():
    with _scan_lock:
        return jsonify({
            "running": _scan_state["running"],
            "log": list(_scan_state["log"]),
            "stats": dict(_scan_state["stats"]),
        })


# ── Main page ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    tab = request.args.get("tab", "log")
    page = max(1, int(request.args.get("page", 1)))
    q = request.args.get("q", "").strip()
    source_filter = request.args.get("source", "").strip()
    status_filter = request.args.get("status", "").strip()

    stats = db.get_stats()
    with db.get_connection() as conn:
        log_total = conn.execute("SELECT COUNT(*) FROM vacancy_log").fetchone()[0]
        scored_total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        sources = [r[0] for r in conn.execute(
            "SELECT DISTINCT source FROM vacancy_log ORDER BY source"
        ).fetchall()]
        statuses = [r[0] for r in conn.execute(
            "SELECT DISTINCT status FROM vacancies ORDER BY status"
        ).fetchall()]

    stats_cards = [
        {"label": "Всего в логе",  "value": log_total},
        {"label": "Обработано",    "value": stats["total"]},
        {"label": "Отправлено",    "value": stats["sent"]},
        {"label": "Откликнулся",   "value": stats["applied"]},
        {"label": "Сохранено",     "value": stats["saved"]},
        {"label": "Средний скор",  "value": f"{stats['avg_score']}%"},
    ]

    filters = []
    params = []
    if q:
        filters.append("title LIKE ?")
        params.append(f"%{q}%")
    if source_filter:
        filters.append("source = ?")
        params.append(source_filter)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    if tab == "log":
        query = f"SELECT * FROM vacancy_log {where} ORDER BY scraped_at DESC"
        rows, row_count = paginate(query, params, page)
    else:
        if status_filter:
            filters.append("status = ?")
            params.append(status_filter)
            where = "WHERE " + " AND ".join(filters)
        query = f"SELECT * FROM vacancies {where} ORDER BY match_score DESC, found_at DESC"
        rows, row_count = paginate(query, params, page)

    total_pages = max(1, (row_count + PAGE_SIZE - 1) // PAGE_SIZE)

    return render_template_string(
        HTML,
        tab=tab, page=page, total_pages=total_pages,
        row_count=row_count, rows=rows, q=q,
        source_filter=source_filter, status_filter=status_filter,
        sources=sources, statuses=statuses,
        stats_cards=stats_cards, log_total=log_total, scored_total=scored_total,
    )


if __name__ == "__main__":
    db.init_db()
    print("Dashboard: http://localhost:5000")
    app.run(debug=False, port=5000, threaded=True)
