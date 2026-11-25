# ТЕХДОК: Сбор оценок через интерактивные кнопки в Tag (Mattermost)

> Как реализовано в RAG-пилоте (test_orchestrator_bot) — работает в проде.
> Назначение: повторить в Support Hub + варианты передачи оценок.

## 1. Архитектура

```
[Бот постит карточку с кнопками]
        │  POST /api/v4/posts + props.attachments[].actions
        ▼
[Пользователь в Tag нажимает кнопку]
        │  Mattermost-сервер сам POSTит на integration.url кнопки
        ▼
[Наш эндпоинт /api/tag/rating]
        │  пишет оценку в БД, отвечает JSON
        ▼
[Ответ сервера заменяет карточку]  ← кнопки исчезают, спам невозможен
```

Важно понимать: **кнопки шлёт не браузер пользователя, а сервер Mattermost**.
Поэтому integration.url должен быть доступен С СЕРВЕРА Tag, а не с машины юзера.

## 2. Карточка с кнопками (как создаётся пост)

```python
import json, httpx

TAG_BOT_API = "https://tag.magnit.ru/api/v4"
TOKEN = "..."  # токен бота (файл с правами 600, не хардкод!)

url = "https://<публичный-адрес-сервиса>/api/rating?secret=<секрет>"

payload = {
    "channel_id": channel_id,
    "message": "",   # пусто — весь контент в attachment
    "props": {"attachments": [{
        "color": "#2EB886",                    # цветная полоса слева
        "title": "Как всё прошло? Оцените работу бота ⭐",
        "text": "Диалог завершен — спасибо за обращение! 🙌",
        "actions": [
            {
                "id": "rate_5",
                "name": "⭐⭐⭐⭐⭐",
                "integration": {
                    "url": url,
                    "context": {               # произвольный JSON — вернётся нам при клике
                        "rating": 5,
                        "channel_id": channel_id,
                    },
                },
            },
            # ... 4, 3, 2, 1
        ],
    }]},
}

r = httpx.post(f"{TAG_BOT_API}/posts",
               headers={"Authorization": f"Bearer {TOKEN}"},
               json=payload)
post_id = r.json()["id"]   # сохраняем — пригодится, чтобы убрать кнопки
```

## 3. Приём клика: эндпоинт

При клике Mattermost POSTит на integration.url JSON примерно вида:

```json
{
  "team_id": "...", "channel_id": "...", "user_id": "...",
  "post_id": "id поста с кнопками",       // ← им же потом редактируем карточку
  "trigger_id": "...",
  "context": { "rating": 5, "channel_id": "..." }   // то, что вложили в кнопку
}
```

Эндпоинт (FastAPI):

```python
@app.post("/api/rating")
async def rating(request: Request):
    # 1. Секрет: проверяем ?secret= (проверка логина/пароля тут невозможна)
    if SECRET and request.query_params.get("secret") != SECRET:
        return JSONResponse({"status": "forbidden"}, status_code=403)

    body = await request.json()
    ctx = body.get("context") or {}
    rating = int(ctx.get("rating") or 0)
    channel_id = ctx.get("channel_id") or ""
    card_post_id = body.get("post_id") or ""      # пост с кнопками
    if not rating or not channel_id:
        return JSONResponse({"status": "bad request"}, status_code=400)

    # 2. Сохранить оценку (одна на диалог — защита от спама кликами)
    save_rating(user_id=body.get("user_id"), rating=rating, channel_id=channel_id)

    # 3. Убрать кнопки: редактируем пост с карточкой.
    #    ВАЖНО: Mattermost требует id поста В ТЕЛЕ запроса, не только в URL!
    if card_post_id:
        await httpx.put(
            f"{TAG_BOT_API}/posts/{card_post_id}",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"id": card_post_id,
                  "message": f"Спасибо за оценку {rating}/5! 🙌",
                  "props": {}})                   # пустые props = кнопки исчезли

    # 4. Ответ Mattermost (<= 5 секунд, иначе покажет «ошибка интеграции»)
    return JSONResponse({})
```

Замечания:
- `PUT /posts/{id}` — обновить можно и без `props`, но тогда кнопки останутся.
- Если правка карточки не сработала — кнопки остаются, но повторный клик просто
  перезаписывает оценку (у нас `DELETE ... WHERE chat_id=?` перед INSERT).
- НИКОГДА не кладите секрет/токен бота в `context` кнопки — context виден всем.

## 4. Чек-лист «оценки не доходят» — искать здесь

| # | Проверка | Как |
|---|---|---|
| 1 | Эндпоинт вообще отвечает? | `curl -X POST http://127.0.0.1:8000/api/rating -H 'Content-Type: application/json' -d '{"context":{"rating":5,"channel_id":"x"}}' -v` локально на сервере |
| 2 | Доступен ли он С СЕРВЕРА Tag? | С сервера Mattermost: `curl -k https://<адрес>/api/rating?secret=... -d '{}' -v`. Нет — DNS/файрвол/порт |
| 3 | Сертификат доверенный для Tag? | Tag-сервер валидирует HTTPS. Самоподписанный/внутренний ЦС → Mattermost молча не шлёт. У нас работает домен с корпоративным сертом |
| 4 | Приходит ли запрос вообще? | Лог nginx/access-лог в момент клика + `journalctl -f \| grep rating` |
| 5 | Секрет совпадает? | 403 в нашем логе = URL кнопки с другим secret, чем в конфиге |
| 6 | Структура props правильная? | `actions` должны быть ВНУТРИ `props.attachments[0]`, а не в корне props |
| 7 | Ответ укладывается в 5 сек? | Долгая запись в БД до ответа → Mattermost покажет ошибку (но оценка может уже дойти) |
| 8 | Логи сервера Mattermost | `docker logs mattermost` / journalctl на сервере Tag: строки `post.action.integration...` покажут ошибку соединения |

Порядок обычно такой: п.4 показывает, дошёл ли клик; если не дошёл — п.2 и п.3.

## 5. Вариант «Поддержка Hub»: собирать оценки в Tag и передавать

### Вариант A — всё напрямую в Support Hub (самостоятельно)

Support Hub сам постит карточку с кнопками (у него есть свой бот в Tag?) и сам
принимает клики на своём публичном HTTPS-эндпоинте.

- Плюсы: без посредников, очередь/логика у вендора.
- Минусы: вендору нужен публичный адрес с доверенным сертом (см. п.4 чек-листа —
  именно здесь у всех ломается) + бот с правами постинга в DM.

### Вариант B — оркестратор как прокси (рекомендую, уже работает)

Оценки приходят на наш работающий `/api/tag/rating`, а мы пересылаем их
в Support Hub по его API/webhook (HTTP POST на адрес вендора):

```python
# в tag_rating() после save_rating():
await httpx.post(SUPPORT_HUB_RATING_URL,   # адрес вендора (внутренний — ок)
                 json={"chat_id": chat_id, "rating": rating,
                       "ts": now, "source": "tag"},
                 timeout=5)
```

- Плюсы: не надо открывать Support Hub наружу и решать вопрос с сертом;
  весь Tag-секрет остаётся у нас; при недоступности вендора оценка всё равно
  сохранена у нас (догоним ретраем).
- Минусы: зависимости от двух систем; нужна ссылка «оценка → диалог в Support Hub»
  (как сопоставить оценку с их диалогом — надо спросить у вендора, есть ли у них
  id диалога, который можно передать в context кнопки).

### Что нужно уточнить у вендора (Support Hub)

1. Есть ли API/webhook «принять оценку диалога» (формат, auth)?
2. Как идентифицировать диалог (их chat_id) — чтобы вложить его в `context` кнопки?
3. Кто владеет ботом в Tag, которым постится карточка — их или наш?

### Минимальный MVP (если вендорного API пока нет)

Собирать оценки у нас (уже работает), отдавать вендору выгрузкой — у нас есть
готовый механизм Excel/CSV-выгрузки (см. ТЕХДОК_ВЫГРУЗКА_EXCEL.md): та же
схема, лист «Оценки». Синхронизацию в реальном времени можно подключить позже,
когда вендор даст webhook.
