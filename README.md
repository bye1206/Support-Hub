# Support Hub

Внутренняя on-premise платформа технической поддержки (замена CraftTalk): приём сообщений из корпоративного мессенджера Tag через существующего Mattermost-бота, хранение полной истории обращений, интеграция с AI Orchestrator, рабочее место оператора.

Проектная документация: `support-hub-opencode-pack/docs/` (обязательный контекст — см. `support-hub-opencode-pack/AGENTS.md`).

**Важно:** проект под Git (D-038, решение владельца 2026-11-09, пересматривает D-035): репозиторий инициализирован в корне рабочего каталога, `.gitignore` исключает `.env*`, `.venv`, кэши и локальные данные. Развёртывание — в другой корпоративной сети; production-окружение и runbook — этап 10 плана (`docs/implementation/IMPLEMENTATION_PLAN.md`).

## Структура

```
backend/    FastAPI (модульный монолит): app/ — config, api, models, infra; migrations/ — Alembic
frontend/   React + TypeScript (Vite)
deploy/     docker-compose.yml (PostgreSQL, Redis)
support-hub-opencode-pack/   проектный пакет контекста (не менять без необходимости)
```

## Предпосылки

- Python 3.11+ (проверено на 3.11.9)
- Node.js 18+ — только для frontend
- Docker — для локальной инфраструктуры (PostgreSQL, Redis)

## Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# запуск дев-сервера (http://localhost:8000, docs: /docs)
uvicorn app.main:app --reload --port 8000

# проверки
pytest
ruff check .
mypy app
```

Конфигурация читается из `.env` (см. корневой `.env.example`) и валидируется при старте: невалидное значение уровня логирования или окружения не даст приложению подняться.

Миграции (Alembic, каталог `backend/migrations/`):

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m alembic upgrade head      # применить
.\.venv\Scripts\python.exe -m alembic downgrade -1      # откатить последнюю
.\.venv\Scripts\python.exe -m alembic current           # текущая ревизия
```

Для миграций URL берётся из переменной `DATABASE_URL` (env) или из `backend/.env`. Тесты создают отдельную БД `support_hub_test`, гоняют upgrade → проверки → downgrade.

Эндпоинты:
- `GET /healthz` — liveness: процесс жив;
- `GET /readyz` — readiness: живые проверки PostgreSQL и Redis (таймаут настраивается); при недоступности зависимостей — `503` со статусом `degraded`;
- `POST /api/v1/integrations/tag/messages` — входящий callback бота Tag (авторизация `Authorization: Bearer <BOT_TO_SUPPORT_HUB_TOKEN>`); идемпотентно по `post_id`.

AI-обработка (этап 6, D-043): сообщение пользователя в ИИ-диалоге → тикет `AI_PROCESSING`, worker синхронно вызывает RAG Assistant Gateway (`POST /api/v1/chat` + `POST /api/v1/message/{chat_id}`, заголовки `X-API-Key`/`X-User-Id`) и публикует ответ как AI-сообщение (тикет → `OPEN`). Триггер-коды шлюза: `resolved` → тикет RESOLVED, `operator` → диалог передаётся оператору (HUMAN_PENDING). Ошибки шлюза не ретраятся (нет идемпотентности на их стороне): run → FAILED, тикет остаётся в AI_PROCESSING до ответа оператора или следующего сообщения пользователя.

Каждый ответ содержит `X-Request-ID`; все ошибки возвращают единый конверт `{"error": {"code", "message", "details"}, "correlation_id"}`.

## Frontend

```powershell
cd frontend
npm install
npm run dev        # дев-сервер Vite с прокси /healthz и /readyz на backend
npm run build      # typecheck + production build
npm run typecheck  # tsc --noEmit
npm run lint       # eslint
npm run test       # vitest run
```

## Локальная инфраструктура (Docker)

```powershell
# из корня проекта; --env-file обязателен, т.к. compose-файл лежит в deploy/
Copy-Item .env.example .env   # затем заполнить пароли локальными значениями
docker compose --env-file .env -f deploy/docker-compose.yml up -d

# сервис приложения (опционально):
docker compose --env-file .env -f deploy/docker-compose.yml --profile app up --build

# остановка
docker compose --env-file .env -f deploy/docker-compose.yml down
```

Порты: PostgreSQL 5432, Redis 6379 — привязаны только к `127.0.0.1`. Пароли в `deploy/docker-compose.yml` обязательны (`${VAR:?...}` — compose упадёт без `.env`).

**Object storage (этап 5):** MinIO не входит в локальный стек — вложения реализуются на этапе 5, а хранилище для развёртывания предоставит корпоративная сеть. Клиент-заготовка сохранена (`backend/app/infra/minio_client.py`).

## Статус

- Этапы 1–3 — выполнены (bootstrap: health endpoints, correlation ID, единый формат ошибок; инфраструктура: ORM-клиенты PG/Redis, readiness-проверки, спайк ARQ; БД: 8 таблиц + очередь/аудит, миграции 0001–0002, тесты на реальном PostgreSQL).
- Этап 4 — выполнен: доменные сервисы и FSM жизненного цикла (тикет/диалог/сессия, статус «Обработка ИИ» = `AI_PROCESSING` по D-039), маршрутизация входящих (P-04, PROPOSED), сервисы `sessions`/`tickets`/`messages`/`outbox`/`audit`, транзакционный Outbox с lease/retry/backoff, ARQ-worker (`process_outbox`, cron `expire_sessions`), миграция 0003.
- Этап 5 — первый пропуск выполнен на PROPOSED-контрактах: ingress API (`/api/v1/integrations/tag/messages`, авторизация токеном, дедуп `post_id`, timestamp ISO/epoch), outbound-адаптер бота (`message.outbound` → `POST /internal/v1/tag/messages`, PUB-контракт на сверку), диспетчер Outbox. Ожидает сверки с реальным ботом (D-028) и решения по вложениям (P-18).
- Этап 6 — выполнен по реальному контракту (D-043): синхронная интеграция с RAG Assistant Gateway, run'ы на каждое входящее сообщение (без авторетраев — у шлюза нет идемпотентности), триггер-коды `resolved`/`operator`, handoff на оператора (`ai_handoffs`), кэш chat_id шлюза на диалоге, ARQ-задача `process_ai_runs` с enqueue-фолбэком. Детализация и открытые пункты — `support-hub-opencode-pack/docs/implementation/IMPLEMENTATION_PLAN.md` (этап 4).

Запуск worker (обычно в отдельном терминале поверх запущенных PostgreSQL/Redis):

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.worker.main
```

Бизнес-логика (миграция к API-эндпоинтам, Tag/AI-интеграции, рабочее место оператора) — этапы 5–7 (`IMPLEMENTATION_PLAN.md`).
