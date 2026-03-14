"""
JobHunter AI — Web Dashboard
Run: python web.py
Open: http://localhost:5000
"""
import threading
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

import db
from main import run_scrapers, is_relevant_title, is_salary_acceptable, is_acceptable_work_location, is_acceptable_language
from ai_scorer import score_vacancy, score_candidate
from scrapers.candidates_robota import fetch_candidates as fetch_candidates_robota
from scrapers.candidates_work import fetch_candidates as fetch_candidates_work

app = Flask(__name__)

# ── Vacancy scan state ────────────────────────────────────────────────────────
_scan_lock = threading.Lock()
_scan_state = {
    "running": False,
    "log": [],
    "stats": {},
}

# ── Candidate scan state ──────────────────────────────────────────────────────
_cscan_lock = threading.Lock()
_cscan_state = {
    "running": False,
    "log": [],
    "stats": {},
}


def _log(msg: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    with _scan_lock:
        _scan_state["log"].append(f"[{ts}] {msg}")


def _clog(msg: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    with _cscan_lock:
        _cscan_state["log"].append(f"[{ts}] {msg}")


def _run_scan():
    with _scan_lock:
        _scan_state["running"] = True
        _scan_state["log"] = []
        _scan_state["stats"] = {}

    try:
        _log("Запуск скраперов...")
        vacancies = run_scrapers()
        _log(f"Найдено всего: {len(vacancies)}")

        new = skipped_title = skipped_salary = skipped_loc = skipped_lang = skipped_dup = 0

        for v in vacancies:
            db.log_vacancy(
                source=v.get("source", ""),
                title=v.get("title", ""),
                url=v.get("url", ""),
                salary=v.get("salary", ""),
            )

            if not is_relevant_title(v):
                skipped_title += 1
                continue

            if not is_salary_acceptable(v):
                skipped_salary += 1
                continue

            if not is_acceptable_work_location(v):
                skipped_loc += 1
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
            "skipped_title": skipped_title,
            "skipped_salary": skipped_salary,
            "skipped_loc": skipped_loc,
            "skipped_lang": skipped_lang,
            "skipped_dup": skipped_dup,
        }
        _log(f"Готово. Новых: {new} | Не по темі: {skipped_title} | Зарплата: {skipped_salary} | Локація: {skipped_loc} | Мова/Англ.: {skipped_lang} | Дубли: {skipped_dup}")

        with _scan_lock:
            _scan_state["stats"] = stats

    except Exception as exc:
        _log(f"Ошибка: {exc}")
    finally:
        with _scan_lock:
            _scan_state["running"] = False


def _run_candidate_scan():
    with _cscan_lock:
        _cscan_state["running"] = True
        _cscan_state["log"] = []
        _cscan_state["stats"] = {}

    try:
        _clog("Запуск пошуку кандидатів...")

        all_candidates = []
        _clog("Scraping Robota.ua resumes...")
        try:
            robota = fetch_candidates_robota()
            _clog(f"Robota.ua: {len(robota)} кандидатів")
            all_candidates.extend(robota)
        except Exception as exc:
            _clog(f"Robota.ua помилка: {exc}")

        _clog("Scraping Work.ua resumes...")
        try:
            workua = fetch_candidates_work()
            _clog(f"Work.ua: {len(workua)} кандидатів")
            all_candidates.extend(workua)
        except Exception as exc:
            _clog(f"Work.ua помилка: {exc}")

        _clog(f"Всього знайдено: {len(all_candidates)}")

        new = skipped_dup = 0

        for c in all_candidates:
            cid = db.insert_candidate(
                name=c.get("name", "Анонім"),
                position=c.get("position", ""),
                url=c.get("url", ""),
                source=c.get("source", ""),
                location=c.get("location", ""),
                salary=c.get("salary", ""),
                experience=c.get("experience", ""),
                description=c.get("description", ""),
            )

            if cid is None:
                skipped_dup += 1
                continue

            _clog(f"Новий: [{c.get('source')}] {c.get('position', '')[:50]}")

            score, comment = score_candidate(
                position=c.get("position", ""),
                name=c.get("name", ""),
                description=c.get("description", ""),
                location=c.get("location", ""),
                salary=c.get("salary", ""),
                experience=c.get("experience", ""),
            )
            db.update_candidate_score(cid, score, comment)
            new += 1

        stats = {
            "scraped": len(all_candidates),
            "new": new,
            "skipped_dup": skipped_dup,
        }
        _clog(f"Готово. Нових: {new} | Дублів: {skipped_dup}")

        with _cscan_lock:
            _cscan_state["stats"] = stats

    except Exception as exc:
        _clog(f"Помилка: {exc}")
    finally:
        with _cscan_lock:
            _cscan_state["running"] = False


# ── HTML ───────────────────────────────────────────────────────────────────────
HTML = """
<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>JobHunter AI</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <script>
  // ── Vacancy scan ──────────────────────────────────────────────────────────
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
        document.getElementById('scan-status').textContent = data.running ? 'Виконується...' : '';
        if (!data.running) {
          clearInterval(_pollTimer);
          document.getElementById('btn-scan').disabled = false;
          document.getElementById('btn-scan').textContent = 'Запустити парсер';
          if (data.stats && data.stats.new !== undefined) {
            document.getElementById('scan-result').textContent =
              'Знайдено: ' + data.stats.scraped + ' | Нових: ' + data.stats.new +
              ' | Не по темі: ' + data.stats.skipped_title +
              ' | Зарплата: ' + data.stats.skipped_salary +
              ' | Локація: ' + data.stats.skipped_loc +
              ' | Мова/Англ.: ' + data.stats.skipped_lang +
              ' | Дублів: ' + data.stats.skipped_dup;
          }
          setTimeout(function(){ location.reload(); }, 2000);
        }
      });
  }

  // ── Candidate scan ────────────────────────────────────────────────────────
  var _cpollTimer = null;
  var _clastLogLen = 0;
  function startCandidateScan() {
    fetch('/api/candidates/scan/start', {method: 'POST'})
      .then(function(r){ return r.json(); })
      .then(function(data) {
        if (data.error) { alert(data.error); return; }
        document.getElementById('cscan-log-wrap').classList.remove('d-none');
        document.getElementById('cscan-log').textContent = '';
        document.getElementById('cscan-result').textContent = '';
        document.getElementById('btn-cscan').disabled = true;
        document.getElementById('btn-cscan').textContent = 'Пошук...';
        _clastLogLen = 0;
        _cpollTimer = setInterval(pollCandidateStatus, 1500);
      });
  }
  function pollCandidateStatus() {
    fetch('/api/candidates/scan/status')
      .then(function(r){ return r.json(); })
      .then(function(data) {
        var logEl = document.getElementById('cscan-log');
        var newLines = data.log.slice(_clastLogLen);
        if (newLines.length) {
          logEl.textContent += newLines.join('\\n') + '\\n';
          logEl.scrollTop = logEl.scrollHeight;
          _clastLogLen = data.log.length;
        }
        document.getElementById('cscan-status').textContent = data.running ? 'Виконується...' : '';
        if (!data.running) {
          clearInterval(_cpollTimer);
          document.getElementById('btn-cscan').disabled = false;
          document.getElementById('btn-cscan').textContent = 'Знайти кандидатів';
          if (data.stats && data.stats.new !== undefined) {
            document.getElementById('cscan-result').textContent =
              'Знайдено: ' + data.stats.scraped + ' | Нових: ' + data.stats.new +
              ' | Дублів: ' + data.stats.skipped_dup;
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
    .score-pill.clickable { cursor: pointer; border: 1px solid transparent; transition: opacity .15s; }
    .score-pill.clickable:hover { opacity: .75; }
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
    #scan-log, #cscan-log {
      background:#1a1a2e; color:#a8ff78; font-family:monospace;
      font-size:.8rem; height:200px; overflow-y:auto; border-radius:8px;
      padding:12px; white-space:pre-wrap;
    }
    #scan-panel, #cscan-panel { border: none; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
    .ai-comment { font-size: .8rem; color: #555; max-width: 260px; white-space: normal; }
    .candidate-name { font-size: .85rem; color: #333; }
    .status-select { font-size: .75rem; border-radius: 6px; padding: 2px 6px; border: 1px solid #dee2e6; background: #fff; cursor: pointer; }
    .status-select.s-new      { color: #6c757d; border-color: #adb5bd; }
    .status-select.s-applied  { color: #0a6640; background: #d1fae5; border-color: #6ee7b7; font-weight: 600; }
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

  <!-- Stats row -->
  <div class="row g-3 mb-4">
    {% for s in stats_cards %}
    <div class="col-6 col-md-2">
      <div class="card stat-card">
        <div class="card-body">
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </div>
    {% endfor %}
  </div>

  <!-- Vacancy scan panel (hidden on candidates tab) -->
  {% if tab != 'candidates' %}
  <div class="card mb-4" id="scan-panel">
    <div class="card-body">
      <div class="d-flex align-items-center gap-3 mb-3">
        <button id="btn-scan" class="btn btn-danger px-4 fw-bold" onclick="startScan()">
          ▶ Запустити парсер
        </button>
        <div id="scan-status" class="text-muted small"></div>
      </div>
      <div id="scan-log-wrap" class="d-none">
        <div id="scan-log"></div>
        <div id="scan-result" class="mt-2 small text-muted"></div>
      </div>
    </div>
  </div>
  {% endif %}

  <!-- Candidate scan panel (only on candidates tab) -->
  {% if tab == 'candidates' %}
  <div class="card mb-4" id="cscan-panel">
    <div class="card-body">
      <div class="d-flex align-items-center gap-3 mb-3">
        <button id="btn-cscan" class="btn btn-success px-4 fw-bold" onclick="startCandidateScan()">
          🔍 Знайти кандидатів
        </button>
        <span class="text-muted small">Пошук на Robota.ua та Work.ua за вакансією: <strong>Керівник відділу продажів (JAMM School)</strong></span>
        <div id="cscan-status" class="text-muted small"></div>
      </div>
      <div id="cscan-log-wrap" class="d-none">
        <div id="cscan-log"></div>
        <div id="cscan-result" class="mt-2 small text-muted"></div>
      </div>
    </div>
  </div>
  {% endif %}

  <!-- Tabs -->
  <ul class="nav nav-tabs tabs mb-0" id="mainTabs">
    <li class="nav-item">
      <a class="nav-link {% if tab == 'log' %}active{% endif %}" href="/?tab=log">
        Лог вакансій <span class="badge bg-secondary ms-1">{{ log_total }}</span>
      </a>
    </li>
    <li class="nav-item">
      <a class="nav-link {% if tab == 'scored' %}active{% endif %}" href="/?tab=scored">
        Оброблені AI <span class="badge bg-secondary ms-1">{{ scored_total }}</span>
      </a>
    </li>
    <li class="nav-item">
      <a class="nav-link {% if tab == 'candidates' %}active{% endif %}" href="/?tab=candidates">
        👥 Кандидати <span class="badge bg-success ms-1">{{ candidates_total }}</span>
      </a>
    </li>
  </ul>

  <div class="card table-card rounded-top-0">
    <div class="card-body p-0">

      <!-- Filter bar -->
      <form method="get" class="filter-bar d-flex flex-wrap gap-2 p-3 border-bottom bg-white">
        <input type="hidden" name="tab" value="{{ tab }}">
        <input name="q" value="{{ q }}" class="form-control form-control-sm" style="max-width:220px"
               placeholder="{% if tab == 'candidates' %}Пошук за посадою...{% else %}Пошук за назвою...{% endif %}">
        <select name="source" class="form-select form-select-sm" style="max-width:160px">
          <option value="">Всі джерела</option>
          {% for s in sources %}
          <option {% if source_filter == s %}selected{% endif %}>{{ s }}</option>
          {% endfor %}
        </select>
        {% if tab == 'scored' %}
        <select name="status" class="form-select form-select-sm" style="max-width:140px">
          <option value="">Всі статуси</option>
          {% for st in statuses %}
          <option {% if status_filter == st %}selected{% endif %}>{{ st }}</option>
          {% endfor %}
        </select>
        {% endif %}
        {% if tab == 'candidates' %}
        <select name="status" class="form-select form-select-sm" style="max-width:160px">
          <option value="">Всі статуси</option>
          {% for st in candidate_statuses %}
          <option {% if status_filter == st %}selected{% endif %}>{{ st }}</option>
          {% endfor %}
        </select>
        <select name="min_score" class="form-select form-select-sm" style="max-width:160px">
          <option value="">Будь-яка оцінка</option>
          <option value="80" {% if min_score_filter == '80' %}selected{% endif %}>≥ 80%</option>
          <option value="65" {% if min_score_filter == '65' %}selected{% endif %}>≥ 65%</option>
          <option value="50" {% if min_score_filter == '50' %}selected{% endif %}>≥ 50%</option>
        </select>
        {% endif %}
        <button class="btn btn-sm btn-primary">Застосувати</button>
        <a href="/?tab={{ tab }}" class="btn btn-sm btn-outline-secondary">Скинути</a>
      </form>

      <!-- TABLE: vacancy_log -->
      {% if tab == 'log' %}
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead>
            <tr><th>#</th><th>Сервіс</th><th>Назва</th><th>Зарплата</th><th>Знайдено</th></tr>
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
            <tr><td colspan="5" class="text-center text-muted py-4">Немає даних</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <!-- TABLE: vacancies (scored) -->
      {% elif tab == 'scored' %}
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead>
            <tr>
              <th>#</th><th>Сервіс</th><th>Назва</th><th>Компанія</th>
              <th>Локація</th><th>Remote</th><th>Зарплата</th>
              <th>Оцінка AI</th><th>Статус</th><th>Знайдено</th>
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
              <td>{% if is_remote %}<span class="badge bg-success">Remote</span>{% else %}<span class="text-muted small">—</span>{% endif %}</td>
              <td>{% if r.salary %}<span class="salary-text">{{ r.salary }}</span>{% else %}<span class="no-salary">—</span>{% endif %}</td>
              <td>
                {% set sc = r.match_score %}
                <span class="score-pill clickable {% if sc >= 75 %}score-high{% elif sc >= 50 %}score-mid{% else %}score-low{% endif %}"
                      onclick="showAiComment(this)"
                      data-score="{{ sc }}"
                      data-title="{{ r.title | e }}"
                      data-comment="{{ r.ai_comment | e }}">{{ sc }}%</span>
              </td>
              <td>
                {% set sc = r.status %}
                <select class="status-select s-{{ sc }}"
                        data-id="{{ r.id }}" data-prev="{{ sc }}"
                        onchange="this.className='status-select s-'+this.value; updateStatus(this)">
                  <option value="new"     {% if sc == 'new'     %}selected{% endif %}>Нове</option>
                  <option value="applied" {% if sc == 'applied' %}selected{% endif %}>Відправлено відгук</option>
                </select>
              </td>
              <td class="text-muted small">{{ r.found_at[:16].replace('T', ' ') if r.found_at else '—' }}</td>
            </tr>
            {% else %}
            <tr><td colspan="10" class="text-center text-muted py-4">Немає даних</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <!-- TABLE: candidates -->
      {% else %}
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead>
            <tr>
              <th>#</th><th>Джерело</th><th>Посада</th><th>Ім'я</th>
              <th>Локація</th><th>Досвід</th><th>Зарплата</th>
              <th>Оцінка AI</th><th>Коментар AI</th><th>Статус</th><th>Знайдено</th>
            </tr>
          </thead>
          <tbody>
            {% for r in rows %}
            <tr>
              <td class="text-muted small">{{ r.id }}</td>
              <td><span class="badge bg-success">{{ r.source }}</span></td>
              <td><a class="vacancy-link" href="{{ r.url }}" target="_blank">{{ r.position }}</a></td>
              <td class="candidate-name">{{ r.name or '—' }}</td>
              <td class="text-muted small">{{ r.location or '—' }}</td>
              <td class="text-muted small">{{ r.experience or '—' }}</td>
              <td>{% if r.salary %}<span class="salary-text">{{ r.salary }}</span>{% else %}<span class="no-salary">—</span>{% endif %}</td>
              <td>
                {% set sc = r.match_score %}
                <span class="score-pill clickable {% if sc >= 75 %}score-high{% elif sc >= 50 %}score-mid{% else %}score-low{% endif %}"
                      onclick="showAiComment(this)"
                      data-score="{{ sc }}"
                      data-title="{{ r.position | e }}"
                      data-comment="{{ r.ai_comment | e }}">{{ sc }}%</span>
              </td>
              <td><div class="ai-comment">{{ r.ai_comment or '—' }}</div></td>
              <td>
                {% set ccolors = {'new':'secondary','viewed':'primary','contacted':'success','rejected':'danger'} %}
                <span class="badge status-badge bg-{{ ccolors.get(r.status, 'secondary') }}">{{ r.status }}</span>
              </td>
              <td class="text-muted small">{{ r.found_at[:16].replace('T', ' ') if r.found_at else '—' }}</td>
            </tr>
            {% else %}
            <tr><td colspan="11" class="text-center text-muted py-4">Немає кандидатів. Натисніть «Знайти кандидатів» щоб запустити пошук.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% endif %}

      <!-- Pagination -->
      {% if total_pages > 1 %}
      <nav class="d-flex justify-content-between align-items-center px-3 py-2 border-top">
        <span class="text-muted small">Сторінка {{ page }} з {{ total_pages }} ({{ row_count }} записів)</span>
        <ul class="pagination pagination-sm mb-0">
          {% if page > 1 %}
          <li class="page-item"><a class="page-link" href="?tab={{ tab }}&page={{ page-1 }}&q={{ q }}&source={{ source_filter }}&status={{ status_filter }}&min_score={{ min_score_filter }}">‹</a></li>
          {% endif %}
          {% for p in range([1, page-2]|max, [total_pages+1, page+3]|min) %}
          <li class="page-item {% if p == page %}active{% endif %}">
            <a class="page-link" href="?tab={{ tab }}&page={{ p }}&q={{ q }}&source={{ source_filter }}&status={{ status_filter }}&min_score={{ min_score_filter }}">{{ p }}</a>
          </li>
          {% endfor %}
          {% if page < total_pages %}
          <li class="page-item"><a class="page-link" href="?tab={{ tab }}&page={{ page+1 }}&q={{ q }}&source={{ source_filter }}&status={{ status_filter }}&min_score={{ min_score_filter }}">›</a></li>
          {% endif %}
        </ul>
      </nav>
      {% else %}
      <div class="px-3 py-2 border-top text-muted small">{{ row_count }} записів</div>
      {% endif %}

    </div>
  </div>
</div>

<!-- AI Score Modal -->
<div class="modal fade" id="aiModal" tabindex="-1">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content" style="border-radius:14px; border:none; box-shadow:0 8px 32px rgba(0,0,0,.18);">
      <div class="modal-header" style="background:#1a1a2e; border-radius:14px 14px 0 0; border:none;">
        <div>
          <div class="text-white-50 small mb-1">Оцінка AI</div>
          <h5 class="modal-title text-white mb-0" id="aiModalTitle"></h5>
        </div>
        <span id="aiModalScore" class="score-pill ms-3" style="font-size:1.1rem; padding: 4px 16px;"></span>
        <button type="button" class="btn-close btn-close-white ms-3" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body p-4" id="aiModalBody" style="font-size:.9rem; line-height:1.8; white-space:pre-wrap; font-family: inherit;"></div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
function showAiComment(pill) {
  var score   = parseInt(pill.dataset.score);
  var title   = pill.dataset.title   || '—';
  var comment = pill.dataset.comment || 'Коментар відсутній';

  document.getElementById('aiModalTitle').textContent = title;
  document.getElementById('aiModalBody').textContent  = comment;

  var scorePill = document.getElementById('aiModalScore');
  scorePill.textContent = score + '%';
  scorePill.className = 'score-pill ' + (score >= 75 ? 'score-high' : score >= 50 ? 'score-mid' : 'score-low');

  new bootstrap.Modal(document.getElementById('aiModal')).show();
}

function updateStatus(select) {
  var id  = select.dataset.id;
  var val = select.value;
  fetch('/api/vacancy/' + id + '/status', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({status: val})
  }).then(function(r) {
    if (!r.ok) { alert('Помилка збереження статусу'); select.value = select.dataset.prev; }
    else { select.dataset.prev = val; }
  });
}
</script>
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


# ── API endpoints ──────────────────────────────────────────────────────────────

ALLOWED_STATUSES = {"new", "applied"}

@app.route("/api/vacancy/<int:vacancy_id>/status", methods=["POST"])
def api_vacancy_status(vacancy_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status", "")
    if status not in ALLOWED_STATUSES:
        return jsonify({"error": "Invalid status"}), 400
    db.update_status(vacancy_id, status)
    return jsonify({"ok": True})


@app.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    with _scan_lock:
        if _scan_state["running"]:
            return jsonify({"error": "Парсер вже запущено"}), 409
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


@app.route("/api/candidates/scan/start", methods=["POST"])
def api_candidates_scan_start():
    with _cscan_lock:
        if _cscan_state["running"]:
            return jsonify({"error": "Пошук кандидатів вже запущено"}), 409
    threading.Thread(target=_run_candidate_scan, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/candidates/scan/status")
def api_candidates_scan_status():
    with _cscan_lock:
        return jsonify({
            "running": _cscan_state["running"],
            "log": list(_cscan_state["log"]),
            "stats": dict(_cscan_state["stats"]),
        })


# ── Main page ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    tab = request.args.get("tab", "log")
    page = max(1, int(request.args.get("page", 1)))
    q = request.args.get("q", "").strip()
    source_filter = request.args.get("source", "").strip()
    status_filter = request.args.get("status", "").strip()
    min_score_filter = request.args.get("min_score", "").strip()

    stats = db.get_stats()
    cstats = db.get_candidate_stats()

    with db.get_connection() as conn:
        log_total = conn.execute("SELECT COUNT(*) FROM vacancy_log").fetchone()[0]
        scored_total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        candidates_total = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]

        if tab == "candidates":
            sources = [r[0] for r in conn.execute(
                "SELECT DISTINCT source FROM candidates ORDER BY source"
            ).fetchall()]
        else:
            sources = [r[0] for r in conn.execute(
                "SELECT DISTINCT source FROM vacancy_log ORDER BY source"
            ).fetchall()]

        statuses = [r[0] for r in conn.execute(
            "SELECT DISTINCT status FROM vacancies ORDER BY status"
        ).fetchall()]
        candidate_statuses = [r[0] for r in conn.execute(
            "SELECT DISTINCT status FROM candidates ORDER BY status"
        ).fetchall()]

    if tab == "candidates":
        stats_cards = [
            {"label": "Всього кандидатів", "value": cstats["total"]},
            {"label": "Переглянуто",       "value": cstats["viewed"]},
            {"label": "Зв'язались",        "value": cstats["contacted"]},
            {"label": "Відхилено",         "value": cstats["rejected"]},
            {"label": "Ср. оцінка AI",     "value": f"{cstats['avg_score']}%"},
            {"label": "Вакансій у логу",   "value": log_total},
        ]
    else:
        stats_cards = [
            {"label": "Всього в логу",  "value": log_total},
            {"label": "Оброблено",      "value": stats["total"]},
            {"label": "Відправлено",    "value": stats["sent"]},
            {"label": "Відгукнувся",    "value": stats["applied"]},
            {"label": "Збережено",      "value": stats["saved"]},
            {"label": "Середній скор",  "value": f"{stats['avg_score']}%"},
        ]

    filters = []
    params = []

    if q:
        filters.append("title LIKE ?" if tab != "candidates" else "position LIKE ?")
        params.append(f"%{q}%")
    if source_filter:
        filters.append("source = ?")
        params.append(source_filter)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    if tab == "log":
        query = f"SELECT * FROM vacancy_log {where} ORDER BY scraped_at DESC"
        rows, row_count = paginate(query, params, page)

    elif tab == "scored":
        if status_filter:
            filters.append("status = ?")
            params.append(status_filter)
            where = "WHERE " + " AND ".join(filters)
        query = f"SELECT * FROM vacancies {where} ORDER BY match_score DESC, found_at DESC"
        rows, row_count = paginate(query, params, page)

    else:  # candidates
        if status_filter:
            filters.append("status = ?")
            params.append(status_filter)
        if min_score_filter:
            filters.append("match_score >= ?")
            params.append(int(min_score_filter))
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        query = f"SELECT * FROM candidates {where} ORDER BY match_score DESC, found_at DESC"
        rows, row_count = paginate(query, params, page)

    total_pages = max(1, (row_count + PAGE_SIZE - 1) // PAGE_SIZE)

    return render_template_string(
        HTML,
        tab=tab, page=page, total_pages=total_pages,
        row_count=row_count, rows=rows, q=q,
        source_filter=source_filter, status_filter=status_filter,
        min_score_filter=min_score_filter,
        sources=sources, statuses=statuses,
        candidate_statuses=candidate_statuses,
        stats_cards=stats_cards,
        log_total=log_total, scored_total=scored_total, candidates_total=candidates_total,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    db.init_db()
    print(f"Dashboard: http://localhost:{args.port}")
    app.run(debug=False, port=args.port, threaded=True)
