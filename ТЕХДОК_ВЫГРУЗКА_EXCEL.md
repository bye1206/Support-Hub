# ТЕХДОК: Выгрузка в Excel (XLSX) — как реализовано в RAG Orchestrator

> Назначение: повторить механизм выгрузки данных в Excel в проекте Support Hub.
> Вся реализация — стандартная библиотека + openpyxl, без внешних сервисов.

## 1. Архитектура (общая схема)

```
[Браузер: кнопка "Экспорт"]
      │  GET /api/export/...?range=2026-11-01,2026-11-24
      ▼
[Backend-эндпоинт (FastAPI)]
      │  1. читает данные за период
      │  2. готовит строки
      │  3. openpyxl → Workbook → io.BytesIO (файл в памяти, НА ДИСК НЕ ПИШЕМ)
      │  4. Response с правильным media_type + Content-Disposition
      ▼
[Браузер: fetch → blob → a.download]  ← файл сохраняется у юзера
```

Ключевые принципы:
- **Файл генерируется в памяти** (`io.BytesIO`), никогда не пишется на диск — нет
  мусора, нет гонок при параллельных выгрузках.
- **openpyxl опционален**: если библиотека не установлена, отдаём CSV (graceful
  degradation — выгрузка не ломается от отсутствия зависимости).
- **Даты периода берутся из той же строки запроса, что и у дашборда** — выгрузка
  всегда показывает то же, что юзер видит на экране.

## 2. Backend: эндпоинт XLSX (шаблон для копирования)

Зависимости: `pip install openpyxl` (единственная внешняя).

```python
import io
from fastapi import Response

@app.get("/api/export/sessions")
def api_export_sessions(range: str = ""):
    """XLSX-выгрузка диалогов за период. Без openpyxl — CSV."""
    date_from, date_to = _split_range(range)          # 'от,до' или 'дата'
    entries = _read_data(date_from=date_from, date_to=date_to)   # ваши данные

    # --- подготовка строк (у нас: группировка по диалогу + текст переписки) ---
    rows = []
    for e in entries:
        rows.append([e["chat_id"], e["user_id"], e["question"], e["answer"], ...])

    filename_dates = f"{date_from}_{date_to}" if (date_from and date_from != date_to) else (date_from or "all")

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Диалоги"
        ws.append(["chat_id", "user_id", "вопрос", "ответ", "статус"])   # заголовки
        for r in rows:
            ws.append(r)
        # Ширина колонки + перенос текста для «длинных» ячеек:
        ws.column_dimensions["D"].width = 120
        for row in ws.iter_rows(min_row=2):
            row[3].alignment = Alignment(wrap_text=True, vertical="top")
        buf = io.BytesIO()
        wb.save(buf)
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="sessions_{filename_dates}.xlsx"'},
        )
    except ImportError:
        # CSV-фолбэк: utf-8-sig (BOM!) иначе кириллица в Excel — кракозябры
        import csv
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["chat_id", "user_id", "вопрос", "ответ", "статус"])
        for r in rows:
            w.writerow([str(x).replace("\n", " | ") for x in r])   # \n ломает CSV-строку
        return Response(
            content=buf.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="sessions_{filename_dates}.csv"'},
        )
```

### Обязательные детали (без них будет боль)

| Момент | Почему |
|---|---|
| `media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"` | Иначе браузер не поймёт, что это Excel |
| `Content-Disposition: attachment; filename="..."` | Имя файла при сохранении. Кириллица в имени — только через `filename*=UTF-8''...`, проще латиница |
| CSV: `utf-8-sig`, НЕ `utf-8` | Excel без BOM открывает кириллицу как кракозябры |
| CSV: `delimiter=";"` | В русской локале Excel разделитель — `;`, запятую он не поймёт |
| `\n` внутри ячеек CSV заменять на `" \| "` | Перевод строки ломает csv-строку (в XLSX это ок) |
| Формат периода `range=от,до` (ISO `YYYY-MM-DD`) | Тот же парсер, что у дашборда: выгрузка = то, что на экране |

### Второй вариант у нас: сводный отчёт (лист со стилями)

Для отчёта «статистика по неделям» используется тот же механизм + оформление
(см. `api_report_export`): жирный заголовок, серая заливка шапки, строка «ИТОГО»:

```python
ws["A1"].font = Font(bold=True, size=13)                 # титул
for c in ws[2]:                                          # шапка
    c.font = Font(bold=True)
    c.fill = PatternFill("solid", fgColor="EEEEEE")
ws.append(["ИТОГО", "", t_total, t_ai, t_op, t_eff])
for c in ws[ws.max_row]:
    c.font = Font(bold=True)
# автоширина колонок по содержимому:
for col in ws.columns:
    width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
    ws.column_dimensions[col[0].column_letter].width = min(width + 2, 32)
```

## 3. Две выгрузки, которые у нас работают

| Эндпоинт | Что внутри | Лист(ы) |
|---|---|---|
| `/api/report/export` | Сводная статистика по неделям/месяцам: всего / решено ИИ / передано оператору / эффективность | 1 лист «Статистика» с ИТОГО |
| `/api/export/sessions` | Полная выгрузка диалогов: 1 строка = 1 диалог (chat_id) с текстом переписки | «Диалоги» + «Сообщения» (по-строчно) |

Во второй — важный приём: **текст переписки одной ячейкой**. История диалога
склеивается в многострочную строку с метками времени и ролями:

```python
def _dialog(msgs):
    lines = []
    for m in msgs:
        t = m["ts"][11:19]           # только время из ISO-строки
        if m.get("question"):
            lines.append(f"[{t}] ЮЗЕР: {m['question']}")
        if m.get("answer"):
            lines.append(f"[{t}] БОТ: {m['answer']}")
    return "\n".join(lines)          # в XLSX-ячейке с wrap_text выглядит отлично
```

Коды-триггеры («помогло» и т.п.) перед склейкой переводятся в человекочитаемый
текст по обратному словарю `{код: название}`.

## 4. Frontend: кнопка выгрузки (копипаст-ready)

Два способа. Простой — `window.location` (браузер сам скачает):

```javascript
function downloadSessReport() {
    var url = '/api/report/export?range=' + encodeURIComponent(getDateRange());
    window.location = url;   // минус: нельзя поймать ошибку и показать юзеру
}
```

Полный (наш основной) — fetch + blob + обработка ошибок и состояния кнопки:

```javascript
function downloadDialogs() {
    var url = '/api/export/sessions?range=' + encodeURIComponent(range);
    var btn = document.getElementById('btnExportDialogs');
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Готовим...';                       // выгрузка может идти 5-30 с
    var name = 'sessions_' + (range || 'all').replace(',', '_') + '.xlsx';
    fetch(url).then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.blob();
    }).then(function(blob) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = name;                                // имя файла для сохранения
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function() { URL.revokeObjectURL(a.href); }, 5000);
    }).catch(function(e) {
        alert('Ошибка выгрузки: ' + e.message);
    }).finally(function() {
        btn.disabled = false;
        btn.textContent = old;
    });
}
```

Обратите внимание: имя файла задаётся на фронте (`a.download`), поэтому бэкенд
может отдавать generic-имя — рассинхрона не будет, если формат одинаков.

## 5. Чек-лист внедрения в Support Hub

1. `pip install openpyxl` в окружение сервиса (если нет — фолбэк на CSV уже в шаблоне).
2. Определить формат периода: тот же `?range=YYYY-MM-DD,YYYY-MM-DD`, что и у
   фильтров вашего дашборда (пусто = всё время).
3. Эндпоинт по шаблону из п.2: один лист «Диалоги» (свиток переписки одной
   ячейкой, wrap_text) + по желанию лист «Сообщения» (по-строчно).
4. Эндпоинт включить в защиту (у нас — Basic-auth через `_dash_protected`,
   путь `/api/export`).
5. Кнопка на фронте по шаблону из п.4 с состояниями «Готовим...» / disabled.
6. Проверить на периоде с 1000+ диалогов: время генерации, размер файла.
   Если > 30-60 с — ограничить период или выгружать максимум N строк.
7. Если выгрузка дергается скриптами (не из браузера) — тот же эндпоинт
   годится для curl/wget: `curl -u user:pass -o file.xlsx "https://.../api/export/sessions?range=..."`.

## 6. Что НЕ делать (грабли, на которые мы не наступили случайно, а вы можете)

- Не генерировать XLSX строкой/CSV с расширением .xlsx — Excel ругается на битый формат.
- Не хранить временные файлы на диске сервиса — только `io.BytesIO` в памяти.
- Не забыть про таймаут прокси (nginx `proxy_read_timeout`) при больших выгрузках.
- Не отдавать CSV в `utf-8` без BOM и с `,`-разделителем — «всё сломано» в Excel RU.
