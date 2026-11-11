# Поэтапный план реализации Support Hub

Дата: 2026-11-09. Основа: `docs/10_IMPLEMENTATION_ROADMAP.md` (этапы 0–11), уточнено аудитом. Сетка из 10 этапов согласована со стартовым ТЗ; соответствие roadmap указано в каждом этапе. Общее правило (`10` §«Правило выполнения»): **не переходить к следующему этапу автоматически** — каждый этап требует плана, diff, тестов и отчёта владельцу. На текущем шаге (аудит) не написано ни строчки бизнес-кода и не создано ни одной миграции.

Этап 0 «Техническое обследование» из `docs/10` выполнен: результат — `REPOSITORY_AUDIT.md`, `ARCHITECTURE_GAPS.md`, `TECH_DECISIONS.md` и этот план. Критерий roadmap (согласование владельцем) — ожидается.

---

## Этап 1. Bootstrap репозитория и окружения

**Результат:**
- Git-репозиторий инициализирован; пакет перенесён в корень репозитория по решению владельца (Q-01 / P-01).
- Repo layout модульного монолита (P-02):

```
backend/            # FastAPI-приложение (api/, services/, repositories/, domain/, infra/)
frontend/           # React + TypeScript (опционально может быть пустым скелетом до этапа 8)
deploy/             # docker-compose.yml, nginx/
docs/               # существующая документация + implementation/
.env.example, .gitignore, README.md
```

- Backend skeleton: FastAPI app factory + lifespan, `/healthz` + `/readyz`, pyproject (uv или pip-tools), Ruff + mypy конфигурация, pytest c пустым smoke-тестом.
- Frontend skeleton: Vite + React + TS strict, lint/typecheck/test/build скрипты.
- `deploy/docker-compose.yml`: postgres, redis, minio (+ backend/frontend опционально), healthchecks, volumes; без секретов.
- Исправление ссылки `docs/DECISIONS.md` → `docs/12_DECISION_LOG.md` в `AGENTS.md` (G-01).
- README с точными командами локального запуска.

**Модули:** репозиторий целиком, `backend/app/main.py`, `frontend/`, `deploy/`.

**Зависимости:** решение владельца Q-01; установка Docker Desktop и Node.js в рабочее окружение (R-03).

**Тесты:** backend smoke `pytest`; `ruff check`, `mypy`; `docker compose config`; frontend `pnpm/npm run build` — по доступности инструментов.

**Критерии готовности:** чистый `git status` после коммита; `uvicorn` поднимается и отвечает на `/healthz`; перечисленные проверки либо пройдены, либо честно помечены невыполнимыми из-за отсутствия Docker/Node.

**Блокеры:** Q-01; отсутствие Docker/Node локально (частично проверяемые критерии).

## Этап 2. Конфигурация, логирование, health checks

**Результат:**
- Централизованные настройки Pydantic v2 (`pydantic-settings`) с валидацией при старте; секреты без значений по умолчанию, пригодных для production.
- Structured logging (JSON), correlation ID middleware, фильтрация секретов из логов (`08` §7).
- Единая error response schema (`13`).
- Клиенты PostgreSQL/Redis/MinIO с корректным shutdown (lifespan).
- Спайк-проверка ARQ: совместимость с asyncpg/event loop, краткий отчёт (D-030).

**Модули:** `backend/app/config.py`, `logging/`, `infra/{db,redis,minio}.py`.

**Зависимости:** этап 1; для живых проверок Redis/MinIO — Docker (R-03).

**Тесты:** unit-тесты конфигурации (невалидный env → отказ старта); тест error handler; smoke интеграционные тесты клиентов — при наличии Docker.

**Критерии готовности:** приложение стартует с валидным `.env` и падает с понятной ошибкой при невалидном; в логах нет секретов; correlation ID присутствует во всех записях.

**Блокеры:** нет функциональных; проверяемость ограничена окружением.

## Этап 3. PostgreSQL, SQLAlchemy, Alembic, первая группа моделей

**Результат:**
- Канонический DDL-каталог, согласованный с `docs/03` (не эскизный SQL из обсуждений — `03` §5).
- SQLAlchemy 2.x typed models первой группы: `users`, `user_identities`, `corporate_accounts`, `channels`, `conversations`, `conversation_sessions`, `tickets`, `messages` (+ составные FK и UNIQUE из `03` §3: `tickets.conversation_id UNIQUE`, `(conversation_id, sequence_no)` и т. д.).
- Alembic init + первая миграция upgrade/downgrade.
- Реестр сверки с каталогом из 34 таблиц (R-06).

**Модули:** `backend/app/db/`, `backend/app/models/`, `alembic/`.

**Зависимости:** этап 2; **рабочая PostgreSQL** (Docker или локальная установка) — обязательна для тестов (R-03). Решения G-03, G-04, G-10 влияют на модель.

**Тесты:** интеграционные на настоящем PostgreSQL: upgrade/downgrade, UNIQUE/PARTIAL/CHECK ограничения, конкурентная вставка сообщений с аллокацией `sequence_no`.

**Критерии готовности:** миграции применяются и откатываются на чистой БД; нарушения ограничений дают ожидаемые ошибки; SQLite не используется (`09` §6).

**Блокеры:** отсутствие PostgreSQL в окружении; открытые G-03/G-04 (модель можно писать, финализировать переходы — нет).

## Этап 4. Доменные сервисы и жизненный цикл обращения (+ Outbox) — **РЕАЛИЗОВАН 2026-11-09**

**Что сделано (факт):**
- Модели `outbox.py` (`OutboxEvent`: lease/attempts/backoff/`uq_outbox_idempotency_key`), `audit.py` (`AuditLog`, `IntegrationEvent` с `uq_integration_event(source, external_event_id)`), миграции `0001_first_group`, `0002_outbox_integration_audit`, `0003_ticket_ai_processing` (D-039: `AI_PROCESSING` + именованный CHECK `ck_ticket_status`).
- Чистые FSM-функции домена: `app/domain/state_machines.py` (тикет/диалог/сессия, `app/domain/exceptions.py`: `TransitionNotAllowed`, `StateConflict`). Матрица тикета — P-14 (детали PROPOSED), статус AI_PROCESSING — CONFIRMED (D-039).
- Репозитории: `users` (race-safe get_or_create через `begin_nested`, P-06), `conversations` (`allocate_sequence` — row lock, G-10; `change_mode` — optimistic), `tickets` (`change_status` — optimistic по `state_version`, G-11), `messages`, `outbox` (lease `FOR UPDATE SKIP LOCKED`, `mark_processed/__failed`), `audit`.
- Сервисы: `sessions` (lazy-expiry + 3ч константа, D-006…D-008), `tickets` (`route_incoming` по P-04 PROPOSED, `resolve`/`close`), `messages` (ingress с дедупликацией по `external_post_id`, AI reply, operator reply — каждый входной метод коммитит через `unit_of_work`, хелперы живут в транзакции вызывающего; retry-on-conflict переходов — P-15), `outbox` (LoggingOutboxHandler).
- Worker: `app/worker/tasks.py` (`process_outbox` — lease + retry/backoff, `expire_sessions` — cron) + `main.py` (`WorkerSettings`); ARQ подтверждён round-trip'ом на этапе 3.
- Аудит: ключевые действия (`ticket.created`, `ticket.reopened`, `message.created`, `ticket.resolved`, `ticket.closed`) пишутся в `audit_logs`.
- Тесты: 90 passed — матрица FSM (`test_state_machines.py`, полная), интеграционные lifecycle (`test_lifecycle.py`: полная цепочка первого сообщения, дедуп по `post_id`, AI/operator ответы, reopen одного тикета, CLOSED → новый тикет+диалог, гонка двух сообщений с retry-on-conflict, оптимистичный конфликт resolve), Outbox (`test_outbox.py`: lease-дискретность при параллельных воркерах, идемпотентность, backoff) — всё на реальном PostgreSQL (AGENTS §6).
- Проверки: `ruff check` — 0 замечаний; `mypy app` — 43 файла, 0 ошибок; `pytest -q --timeout=60` — 90 passed; `alembic upgrade head` применён к dev-БД.

**Найденный баг (исправлен):** тест конкурентного resolve падал из-за слабой identity map SQLAlchemy: отброшенный без сильной ссылки ORM-объект собирался GC, `session.get` перечитывал свежее состояние (RESOLVED) вместо устаревшего, и FSM падал `TransitionNotAllowed` вместо `StateConflict` — тест не проверял задуманный путь. Исправлен удержанием strong reference; фикстура очистки таблиц теперь термирует «утёкшие» idle-in-transaction соединения перед TRUNCATE (`lock_timeout 5s`).

**Ожидают подтверждения владельца (не блокируют код):** P-14 (детали матрицы, включая reopen через AI_PROCESSING), P-06, P-04, P-15; контракты бота/Orchestrator — этапы 5–6 (Q-06…Q-08).

## Этап 4 (исходный план)

**Результат:**
- `TicketService`, `ConversationService`, `MessageService`, `SessionService` — конечные автоматы переходов (`01` §2–4, `03` §4), проверки в сервисах, а не в route handlers.
- Аллокация `sequence_no` в транзакции (G-10).
- Механизм истечения сессий по выбранному P-05.
- Транзакционный Outbox: `outbox_events`, `integration_events` (идемпотентность по `(source, external_event_id)`), worker с lease/retry/backoff.
- Foundation аудита: сервис записи `audit_logs` для всех ключевых действий (заполняется по мере появления действий).
- Реализация маршрутизации входящего сообщения в тикет по P-04 (после подтверждения).

**Модули:** `backend/app/domain/`, `backend/app/services/`, `backend/app/repositories/`, `backend/app/worker/`.

**Зависимости:** этап 3. Подтверждения владельца: P-04 (маршрутизация), G-03 (статус после AI-ответа), P-06 (автосоздание пользователя).

**Тесты:** unit — все допустимые/запрещённые переходы статусов тикета/диалога/сессии; интеграционные — Outbox worker crash при PROCESSING, дубликат webhook не создаёт второго сообщения, две одновременные отправки в один диалог; конкурентный claim тикета двумя операторами (упрощённо, полное API — этап 7).

**Критерии готовности:** сохранение сообщения + регистрация Outbox-события атомарны; повторная доставка события идемпотентна; аудит записывается.

**Блокеры:** G-03, G-06 (P-04), G-13 — без решений переходы тикета и маршрутизация не финализируются.

## Этап 5. Bot/Tag ingress и outbound — **ПРОПУСК 1 РЕАЛИЗОВАН 2026-11-09 (на PROPOSED-контрактах)**

**Что сделано (факт):**
- `POST /api/v1/integrations/tag/messages` — приём callback бота (`app/api/tag_ingress.py`): без бизнес-логики, одна транзакция — `MessageService`.
- Схема payload по описанию владельца (D-027): `team_id/team_domain/channel_id/channel_name/timestamp/user_id/user_name/post_id/text/file_ids` (`app/integrations/tag/schemas.py`); `timestamp` — ISO-8601 или epoch-автодетект (D-041). `file_ids` пишутся в аудит (P-18: хранение вложений — следующий проход).
- Сервисная авторизация бота: `Authorization: Bearer <BOT_TO_SUPPORT_HUB_TOKEN>` (D-040, PROPOSED; констан-time сравнение, 401 в едином конверте).
- Идемпотентность по `post_id` — уже в `MessageService` (этап 4), подтверждена тестом на уровне API.
- Регистрация канала: `(channel_type='tag', external_channel_id)` race-safe get_or_create (P-16).
- Outbound: адаптер бота `app/integrations/tag/bot_client.py` (`POST /internal/v1/tag/messages`, D-042 PROPOSED) + диспетчер `message.outbound` → бот, остальное → log (этап 6); retry/backoff через Outbox.
- Тесты: 106 passed — 401/422/happy path/dedup/timestamp-форматы на API-уровне (реальный PostgreSQL), юниты клиента (2xx/5xx/timeout/заголовок токена via MockTransport), интеграционные диспетчера (PROCESSED / retry-scheduled на реальном outbox).
- Проверки: `ruff` чисто, `mypy app` — 50 файлов, 0 ошибок, `pytest -q --timeout=60` — 106 passed.

**Исходный план**
- `POST /api/v1/integrations/tag/messages` — приём нормализованных событий от бота: валидация схемы, сервисная авторизация Bot → Support Hub, идемпотентность по `post_id` (`04` §4).
- Outbound: worker читает Outbox, вызывает внутренний API бота (предложен `POST /internal/v1/tag/messages` — сверить с фактическим ботом), обрабатывает результаты `SENT/FAILED/UNKNOWN` + reconciliation (R-04).
- Вложения: получение file_ids через бота, сохранение в MinIO, защищённый endpoint выдачи файлов боту (`04` §6, `08` §4).
- Delivery journal / запрос статуса по delivery ID — по возможностям фактического бота.

**Модули:** `backend/app/integrations/tag/`, `backend/app/worker/`, `frontend/` — нет.

**Зависимости:** этап 4; **фактический код/контракт существующего бота** (D-028, 11.A.5/8); ответы 11.A.1–2 (аутентификация callback, retry) либо утверждённые компенсирующие меры (R-02).

**Тесты:** mock HTTP бота: успешная отправка, timeout → UNKNOWN, 5xx → retry с backoff; дубликат callback; вложения: неподдерживаемый MIME, превышение размера; self-message фильтрация (по известным полям payload).

**Критерии готовности:** сквозной тест «webhook → тикет/сообщение → ответ в тестовый DM» (критерий этапа 5 из `docs/10`); ни одно сообщение не теряется между приёмом и persist.

**Блокеры:** доступ к коду бота и среде Tag; ответы 11.A.1–8 — без них ingress считается не production-ready.

## Этап 6. AI Orchestrator adapter — **РЕАЛИЗОВАН 2026-11-10 (реальный контракт D-043)**

**Что сделано (факт):**
- Контракт от команды интеграции разобран (`КОНТРАКТ_ИНТЕГРАЦИИ_ВНЕШНЯЯ_ВЕРСИЯ.md` v1.0): синхронный HTTP, без callback'ов; D-043 CONFIRMED, Q-08 закрыт, Q-04 закрыт без нового статуса тикета (P-19).
- Модели: `ai_processing_runs` (UNIQUE `input_message_id+attempt_no`, статусы NEW/RUNNING/SUCCEEDED/FAILED/CANCELLED, request_id, trigger_code, error), `ai_handoffs` (reason, is_accepted, partial unique «не более одной принятой на диалог»), `conversations.ai_chat_id`; миграция `0004_ai_runs_handoffs` (применена, alembic upgrade head).
- FSM: триггеры `AI_RESOLVED` (→ RESOLVED) и `AI_REQUESTED_HANDOFF` (→ OPEN) только из AI_PROCESSING (D-043 §7).
- Клиент шлюза `app/integrations/ai/gateway_client.py`: `POST /api/v1/chat`, `POST /api/v1/message/{chat_id}`, заголовки `X-API-Key`+`X-User-Id` на каждый запрос, таймаут 130 с (контракт §5: ответ 30–60 с), ошибки → AuthError/NotFound/Rejected/Unavailable.
- Детектор триггер-кодов `app/integrations/ai/triggers.py`: точное совпадение с конфигом → действие; **неизвестный кодо-подобный ответ рендерится текстом + warning** (P-21 PROPOSED: иначе «abc123» от пользователя перехватил бы диалог).
- Сервис `app/services/ai_runs.py`: `ensure_run_for_message` (дедуп) + `process_pending` — claim `FOR UPDATE SKIP LOCKED` (≤1 run на диалог, G-11), HTTP-вызов **вне транзакции**, применение ответа одной транзакцией: обычный ответ → AI-сообщение (переиспользует MessageService, FSM AI_REPLY → OPEN) + outbox `message.outbound` + аудит (actor=AI); `resolved` → тикет RESOLVED без публикации; `operator` → диалог HUMAN_PENDING + handoff (is_accepted=false) + тикет OPEN; диалог ушёл из AI mode → run CANCELLED (D-014).
- Chat-маппинг (P-20): 1 диалог = 1 чат шлюза, id кэшируется в `conversations.ai_chat_id`, история в шлюз не пересылается.
- Worker: задача `process_ai_runs` (ARQ, timeout 1800 с, max_tries=1 — без авторетраев), фолбэк-обработчик `message.user_received` → enqueue через Redis (повторный enqueue безопасен — дедуп run'ов).
- Провал шлюза (503/сеть): run → FAILED, тикет остаётся AI_PROCESSING, **авторетраев нет** (у шлюза нет идемпотентности) — Q-04 закрыт (P-19).
- Конфиг: `AI_ORCHESTRATOR_BASE_URL`/`SUPPORT_HUB_TO_AI_TOKEN` (alias'ы `ai_gateway_*`), таймаут, коды триггеров.
- Тесты: 142 passed — клиент (заголовки, 201/401/403/404/422/503/таймаут), триггеры (детект, неизвестные коды), интеграционные на реальном PostgreSQL (happy path, operator/resolved триггеры, 503 → FAILED + AI_PROCESSING, дедуп run'а, CANCELLED, worker-фолбэк, end-to-end задача, переиспользование chat_id); FSM-матрица расширена (18 кейсов).
- Проверки: `ruff` чисто, `mypy app` — 57 файлов, 0 ошибок, `pytest -q --timeout=60` — 142 passed.

**Исходный план (пересмотрен по D-043):**
- Anti-corruption adapter: реальный контракт запроса/callback (получить у владельца системы, D-029) ↔ внутренние модели.
- Формирование контекста из собственной БД (`messages`, без внутренних заметок — D-025), текущее сообщение отдельно от контекста (`05` §4).
- `ai_processing_runs`: последовательная обработка, ≤1 активного run на диалог (G-11), `state_version`.
- Приём callback: публикация только при совпадении режима и версии; иначе `STALE` (R-05). Обработка `HUMAN_HANDOFF` — транзакционный перевод диалога в `HUMAN_PENDING` + тикет в очередь. Доменное поведение при `AI_PROCESSING_FAILED` — по решению G-07.

**Модули:** `backend/app/integrations/ai/`, `backend/app/domain/`.

**Зависимости:** этап 4; **реальные контракты Orchestrator** (11.B.1–9) — до этого этап строится на фейках и mock callback.

**Тесты:** mock callback: успешный ответ; поздний callback после Handoff → STALE без публикации; два callback на один run; Handoff одновременно с ответом ИИ (конкурентный сценарий `09` §3); лимит размера контекста.

**Критерии готовности:** тестовый end-to-end обмен с существующим Orchestrator (критерий этапа 6 из `docs/10`) — только после получения реального контракта.

**Блокеры:** D-029 OPEN; решение G-07.

## Этап 7. Operator API и WebSocket — **ПРОПУСКИ 1–3 РЕАЛИЗОВАНЫ 2026-11-10**

**Что сделано (факт):**
- Пропуск 1 (коммит `af2e6de`): dev-авторизация (P-22 PROPOSED) — Bearer `OPERATOR_DEV_TOKEN` + заголовки `X-Operator-Email`/`X-Operator-Name`, автопроvisioning профиля, `is_active` на каждый запрос; задан `keycloak_issuer_url` → dev-токен отклоняется (fail-closed). API: очередь (фильтры status/assignee `me`/`unassigned`, пагинация), карточка с полной историей, публичный ответ (message + PENDING_USER + Outbox одной транзакцией), resolve/close, ручное назначение/снятие, приём handoff (HUMAN_PENDING → HUMAN_ACTIVE, повторный accept → 409). WebSocket: `/ws?token=`, авторизация, `ready`, доставка опубликованных событий (тест — реальный uvicorn + Redis pub/sub; keepalive по времени, фикс ложных ping).
- Пропуск 2 (коммит `8dfb7a4`): внутренние заметки (миграция `0006_internal_notes`, D-025: не сообщения — в историю/ИИ/Outbox не попадают, статус не меняют, аудит `note.created`); категории и теги (миграция `0007_categories_tags`, D-026: `ticket_categories`-дерево, `tags` case-insensitive unique по `lower(name)` (P-23), `ticket_tags`, `tickets.category_id`); API: `POST/GET /conversations/{id}/notes`, `PATCH /tickets/{id}/category`, `POST /tickets/{id}/tags` (get_or_create), `DELETE /tickets/{id}/tags/{tag_id}`; фильтры очереди `?category`/`?tag`; `category_id` + `tags` в карточке и очереди; аудит `ticket.category_changed`/`ticket.tag_added`/`ticket.tag_removed`.
- Пропуск 3: критерий этапа «оператор отвечает → PENDING_USER → Outbox → бот (mock) → PROCESSED» на уровне API (`RoutingOutboxHandler` + мок-бот); пагинация очереди; security-тест «карточка тикета несёт только историю своего диалога» (09 §3, cross-ticket leakage). Конкурентный claim тикета покрыт тестами этапа 4 (оптимистичный конфликт resolve).
- Пропуск 4 (LDAP-авторизация, D-047): прямая LDAP/AD вместо Keycloak (модуль владельца, проверен в проде) — `app/auth/ldap.py` (bind под UPN → self-read → группа «от группы»; ldap3 в worker-потоке — event loop не блокируется; кэш sha256, rate-limit по логину, аварийный локальный аккаунт, fail-closed), `app/auth/sessions.py` (токены в Redis, TTL 12 ч), `POST /api/v1/operator/auth/session` (HTTP Basic только здесь, аудит `operator.signed_in`), `require_operator`/WS принимают сессионные токены; роли из групп `support_hub_operator`/`support_hub_admin` (P-26), email из `mail` AD (P-27); UI — форма «доменный логин + пароль» (Basic UTF-8, пароль не хранится); dev-режим: пароль = dev-токен создаёт сессию (единый путь входа UI). ldap3 в зависимостях.
- Тесты: 182 passed на реальном PostgreSQL/Redis (WS — реальный uvicorn + Redis pub/sub; LDAP — fake через DI); `ruff` чисто; `mypy app` — 73 файла, 0 ошибок; frontend: vitest 8 passed, typecheck/lint/build чисто.
- Ожидают владельца (не блокируют код): DN групп `support_hub_operator`/`support_hub_admin` от админов AD (env `LDAP_GROUP_OPERATOR_DN`/`LDAP_GROUP_ADMIN_DN`); CLI-самопроверка LDAP с целевой ВМ (порт 636); D-046 — URL/API-ключи MinIO (вложения). RBAC-матрица закрыта D-048 (2026-11-11), внедряется на этапе 9.

**Исходный план**
- Keycloak OIDC (Authorization Code + PKCE), проверка подписи/issuer/audience, маппинг `sub` → `operators`, отказ деактивированным (`08` §1).
- Очереди, список/фильтры тикетов, карточка, переписка, публичный ответ (транзакция: message + PENDING_USER + Outbox — `06` §4), внутренние заметки отдельным ресурсом, назначения (ручные; автоматические по D-031/P-07 за флагом), статусы, приоритеты, категории, теги, uploads.
- WebSocket с авторизацией, события новых тикетов/сообщений/назначений/доставки; reconnect — синхронизация по REST (`06` §7).
- RBAC по матрице прав (решение G-08).

**Модули:** `backend/app/api/operator/`, `backend/app/api/ws/`, `backend/app/services/`.

**Зависимости:** этапы 4–6 (частично — можно параллелить за mock-ами AI); матрица прав G-08; SSO-параметры Keycloak (realm/client).

**Тесты:** security: unauthorized/forbidden, cross-ticket data leakage, notes leakage (`09` §3); конкурентный claim тикета; pagination; WS авторизация.

**Критерии готовности:** каждый endpoint проверяет права на backend; полный контур «оператор отвечает → PENDING_USER → Outbox → бот (mock)».

**Блокеры:** G-08 (матрица прав); параметры Keycloak-инсталляции.

## Этап 8. Operator UI

**Результат:**
- Трёхколоночное рабочее место по `docs/06`: очередь/фильтры, переписка с раздельными режимами «публичный ответ / внутренняя заметка» (безопасность — не полагаться на UI, но UI обязан различать режимы), карточка тикета, SLA-индикатор, история назначений и прошлых обращений.
- Realtime обновления без насильственного переключения открытого тикета; reconnect-синхронизация.

**Модули:** `frontend/src/` (features: queue, conversation, ticket-card, composer).

**Зависимости:** этап 7 (API); решение о package manager (P-08).

**Тесты:** lint/typecheck/build; компонентные тесты композера (разделение режимов); интеграция с mock-WS.

**Критерии готовности:** все обязательные элементы MVP из `06` §8 работоспособны против локального backend.
**Реализация UI (2026-11-10, частично):**
- Собран адаптивный трёхколоночный интерфейс: очередь/фильтры/поиск, история сообщений по `sequence_no`, отдельные композеры публичного ответа и внутренней заметки, карточка обращения, история назначений и прошлых тикетов, редактирование тегов/категорий и действия resolve/close.
- Подключены реальные endpoints этапа 7; авторизация dev-оператора вводится в UI и хранится в `sessionStorage`. Добавлен `GET /api/v1/operator/me`, чтобы UI мог назначать обращение текущему оператору через существующий endpoint.
- WebSocket `/ws` обновляет очередь и открытую карточку; после disconnect выполняется REST-синхронизация, текущий тикет не переключается.
- Проверки frontend: typecheck, lint и production build прошли.
- MVP остаётся частичным: метрики SLA относятся к этапу 10, а upload/download вложений ожидают D-046. Реальное подключение к dev backend не проверялось.


**Ограничения:** SLA API относится к этапу 10; вложения ожидают решения D-046; R-03 снят.

## Этап 9. Admin API/UI — **В РАБОТЕ**

**Срез (2026-11-11, D-047):** добавлена роль SUPERVISOR отдельной миграцией; API обзора (агрегированные счётчики), списка операторов (ADMIN), метаданных аудита (SUPERVISOR/ADMIN), смены ролей с защитой от самопонижения последнего администратора и деактивации с атомарным переназначением активных тикетов. Добавлены основы управления категориями и тегами (дерево, мягкая деактивация/повторная активация); неактивные категории недоступны операторам, неактивные теги нельзя назначить новым тикетам. Добавлена офлайн-команда безопасного bootstrap первого ADMIN по проверенным email + Keycloak subject. Frontend содержит обзор, роли/статусы операторов, аудит, категории и теги. Доступ проверяется backend на каждом endpoint. Остаются: переименование справочников в UI, команды/очереди, шаблоны, SLA, диагностика интеграций, безопасные настройки и полные backend-проверки.

**Результат:**
- Разделы по `docs/07`: операторы и роли (регистрация по Keycloak identity, деактивация с процедурой переназначения), команды/очереди, категории (дерево без циклов) и теги, шаблоны ответов, состояние интеграций и ошибки, аудит, безопасные `system_settings` (D-034, без секретов).
- Повтор FAILED Outbox — только после проверки безопасности повтора.

**Модули:** `backend/app/api/admin/`, `frontend/src/features/admin/`.

**Зависимости:** этап 7 (auth/RBAC); матрица прав G-08.

**Тесты:** RBAC admin-эндпоинтов; деактивация оператора с активными назначениями; audit log append-only (роль приложения без UPDATE/DELETE — `08` §6).

**Критерии готовности:** все 13 разделов `docs/07` доступны функционально (для MVP-объёма), секреты нигде не отображаются.

**Блокеры:** G-08.

## Этап 10. SLA, аудит, hardening, тестирование, deployment

Подфазы (соответствует этапам 10–11 из `docs/10`):

**10a. SLA.** Календари (4 таблицы), политики с snapshot, расчёт first response (ответ оператора, не ИИ — `01` §5) и resolution, циклы `cycle_no` при reopen (P-09), breach events, индикаторы в UI. Блокер: неутверждённые нормативы (11.D.5–6) — инфраструктуру можно строить, нормативы вносятся администратором.

**10b. Аудит — завершение.** Покрытие всех значимых действий, проверка неизменяемости.

**10c. Hardening.** Security review по `docs/08`: webhook, файлы (MIME по факту, права), логи без секретов, rate limiting.

**10d. Нагрузочное/конкурентное тестирование.** Полный набор сценариев `09` §3–4 с измерениями против ориентиров.

**10e. Deployment.** Nginx, Docker Compose prod-профиля, backup/restore PostgreSQL и MinIO, health/readiness, worker recovery, monitoring, deployment runbook, пилот параллельно с CraftTalk (`10` этап 11). RPO/RTO — согласовать с инфраструктурной командой.

**Зависимости:** все предыдущие этапы; нормативы SLA (11.D.5); требования инфраструктурной команды.

**Критерии готовности:** backup восстанавливается на чистой среде; security-чеклист закрыт; все тесты `09` зелёные на реальном PostgreSQL; runbook проверен выполнением.

---

## Текущий статус

| Этап | Статус |
|---|---|
| 0. Обследование | Выполнено, согласовано владельцем |
| 1. Bootstrap | **Выполнен** 2026-11-09 (D-035/D-036/D-037: без Git, корень — рабочий каталог); ограничения по окружению см. отчёт этапа |
| 2. Конфигурация, логирование, health checks | **Выполнен** 2026-11-09 (+ доверка 2b: `docker compose config` ✓, живые postgres/redis/minio-проверки `/readyz` ✓, ARQ round-trip на живом Redis ✓, frontend lint/typecheck/test/build ✓). Блокер MinIO: публичные образы недоступны (Docker Hub удалён, quay приватен, dl.min.io недоступен) — нужен `docker login quay.io` или внутренний mirror |
| 3. PostgreSQL, SQLAlchemy, Alembic, первая группа моделей | **Выполнен** 2026-11-09: 8 таблиц, миграция `0001_first_group`, 27 integration-тестов (включая конкурентную аллокацию sequence_no) |
| 4. Доменные сервисы + Outbox | **Выполнен** 2026-11-09: FSM, Outbox + worker, аудит, 90 passed; ожидают подтверждения P-14/P-06/P-04/P-15 |
| 5. Tag ingress/outbound | **Пропуск 1 выполнен** 2026-11-09 (PROPOSED-контракты D-040/D-042): webhook + дедуп + dispatch в бот, 106 passed; production-ready ждёт ответы 11.A и сверки с реальным ботом |
| 6. AI Orchestrator | **Выполнен** 2026-11-10 по реальному контракту (D-043): runs/handoffs, gateway client, триггер-коды (P-21), worker, 142 passed |
| 7. Operator API + WebSocket | **Пропуски 1–4 выполнены** 2026-11-10 (`af2e6de`, `8dfb7a4`, пропуск 3, LDAP D-047): очередь/карточка/ответ/статусы/назначение/handoff, WS-события, заметки (D-025), категории/теги (D-026), E2E «ответ → Outbox → бот (mock)», LDAP-сессии + роли из групп AD, UI-форма доменного входа, 182 passed (frontend: 8 vitest + typecheck/lint/build). Ожидают владельца: DN групп AD, CLI-проверка с ВМ, G-08 (RBAC), D-046 (MinIO, вложения) |
| 8. Operator UI | Частично реализован 2026-11-10: адаптивный queue/conversation/composer UI, REST/WS, dev-auth, self-assignment, категории/теги и история; typecheck/lint/build ✓. Остались SLA (этап 10) и вложения (D-046: решение по файлам) |
| 9. Admin API/UI | Частично реализован 2026-11-11: G-08 закрыт D-047; роли SUPERVISOR + миграция 0008, категории/теги + миграция 0009, защищённые обзор/операторы/audit endpoints, UI для ролей/деактивации/справочников, офлайн-bootstrap ADMIN. Команды/очереди, шаблоны, SLA, диагностика, настройки и backend-проверки остаются |
| 10. SLA, hardening, deployment | Не начат; ждёт нормативов SLA (11.D.5) и требований инфраструктурной команды |
