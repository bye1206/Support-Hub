# 03. Модель данных — канонический каталог

## 1. Правила моделирования

- Один запрос/обращение пользователя = один тикет = один логический диалог.
- Внутри диалога несколько сессий.
- `tickets.conversation_id` — обязательный уникальный FK на `conversations.id`.
- Не создавать таблицу `ticket_conversations`.
- Support Hub — владелец полной истории `messages`.
- Внутренние заметки — отдельная таблица, не публичные сообщения.
- Не дублировать полную историю в `ai_processing_runs`.
- Файлы физически находятся в MinIO, метаданные — в БД.
- Основные FK обычно `ON DELETE RESTRICT`; историю не каскадно удалять.

## 2. Бизнес-таблицы (34)

### Пользователи и диалоги
1. `users` — внутренний профиль конечного пользователя.
2. `user_identities` — внешние ID по каналам, уникальность `(channel_type, external_user_id)`.
3. `corporate_accounts` — подтверждённая связь с корпоративной учётной записью; уникальность `(provider, external_subject)`.
4. `channels` — внешний канал/endpoint Tag или будущего канала.
5. `conversations` — логический диалог, режим, `state_version`, `last_message_sequence`.
6. `conversation_sessions` — сессии по 3 часа, не более одной ACTIVE на диалог.

### Тикеты и переписка
7. `tickets` — тикет, `conversation_id UNIQUE`, статус, приоритет, очередь, исполнитель, категория, временные поля, `state_version`.
8. `messages` — публичные сообщения USER/AI/OPERATOR/SYSTEM, `sequence_no`, `source_created_at`, delivery state.
9. `attachments` — метаданные файла, MinIO location, checksum, MIME, size, uploader, внешний file ID при необходимости.
10. `message_attachments` — связь сообщений и файлов.
11. `ai_processing_runs` — отдельные попытки обработки AI, входное сообщение, response message, request ID, версия состояния, статус и технические метаданные.
12. `ai_handoffs` — события передачи ИИ оператору, причина, summary, состояние.

### Интеграции
13. `integration_events` — входящие события, уникальность `(source, external_event_id)`, статус обработки.
14. `outbox_events` — надёжные исходящие события, idempotency key, попытки, lease/lock, ошибка, время следующей попытки.

### Операторы и маршрутизация
15. `operators` — локальный профиль оператора, `keycloak_sub`, роль, активность.
16. `teams` — команды поддержки.
17. `team_memberships` — связь команд и операторов.
18. `queues` — очереди, режим назначения, default flag.
19. `queue_memberships` — участники очередей.
20. `ticket_assignment_history` — история назначений; не более одной активной записи на тикет.

### Работа с тикетами
21. `internal_notes` — приватные заметки сотрудников.
22. `ticket_categories` — дерево категорий.
23. `tags` — справочник тегов.
24. `ticket_tags` — связь тикетов и тегов.
25. `canned_responses` — глобальные/командные шаблоны.

### SLA и аудит
26. `sla_policies` — нормы первого ответа и решения, календарь, приоритет/категория, версия и default.
27. `business_calendars` — календарь и IANA timezone.
28. `business_calendar_intervals` — типовые интервалы по дням недели.
29. `business_calendar_exceptions` — особые даты.
30. `business_calendar_exception_intervals` — интервалы особых дат.
31. `ticket_sla_instances` — циклы SLA, `cycle_no`, `is_current`, policy snapshot.
32. `ticket_sla_events` — события для расчёта/аудита SLA.
33. `audit_logs` — неизменяемый журнал действий.
34. `system_settings` — безопасные нетайные настройки приложения.

## 3. Важные ограничения и индексы

- `user_identities`: UNIQUE `(channel_type, external_user_id)`.
- `corporate_accounts`: UNIQUE `(provider, external_subject)`.
- `channels`: UNIQUE `(channel_type, external_channel_id)`.
- `conversations`: `state_version > 0`, `last_message_sequence >= 0`.
- `conversation_sessions`: `expires_at = started_at + interval '3 hours'`; partial unique `(conversation_id) WHERE status='ACTIVE'`.
- `tickets`: UNIQUE `conversation_id`; составной FK `(conversation_id, user_id)` → `conversations(id, user_id)`.
- `messages`: UNIQUE `(conversation_id, sequence_no)`; составной FK для автора-пользователя; ответ на сообщение только в том же диалоге.
- Внешний ID сообщения — уникален в области, согласованной с реальным Tag event model; не полагаться только на непроверенную область уникальности.
- `ticket_assignment_history`: partial unique `ticket_id WHERE ended_at IS NULL`; CHECK зависимости `assignment_type` от наличия оператора.
- `ai_processing_runs`: UNIQUE `(input_message_id, attempt_no)`; активный AI run на диалог ограничивается политикой последовательной обработки.
- `ai_handoffs`: составной FK AI run + conversation, не более одной принятой передачи в MVP.
- `integration_events`: UNIQUE `(source, external_event_id)`.
- `outbox_events`: UNIQUE `idempotency_key`; корректные ограничения состояния блокировки.
- `ticket_sla_instances`: UNIQUE `(ticket_id, cycle_no)`; partial unique текущего цикла на тикет.
- `tags`: case-insensitive unique name.
- `system_settings`: UNIQUE `key`; не хранить секреты.

## 4. Временные поля и статусы

Время — `TIMESTAMPTZ`; хранение UTC, отображение в локальной зоне интерфейса.

Тикет: `NEW`, `OPEN`, `PENDING_USER`, `RESOLVED`, `CLOSED`.

Диалог: `AI_ACTIVE`, `HUMAN_PENDING`, `HUMAN_ACTIVE`, `CLOSED`.

Сессия: `ACTIVE`, `EXPIRED`, `ENDED`.

AI run: `QUEUED`, `SENT`, `PROCESSING`, `SUCCEEDED`, `FAILED`, `STALE`, `CANCELLED`.

Проверки переходов статусов должны быть в доменном сервисе. CHECK-ограничения БД не заменяют конечный автомат.

## 5. Важные замечания перед реализацией

Предыдущие SQL-фрагменты из проектного обсуждения — эскизы, не канонический DDL. Перед миграциями инженер должен:

1. собрать один согласованный DDL;
2. проверить каждый FK, включая составные FK;
3. проверить области уникальности внешних ID;
4. пересмотреть ENUM и delivery states;
5. подтвердить типы и nullable-поля;
6. проверить индексы запросами и EXPLAIN на тестовых данных;
7. протестировать concurrent transactions на PostgreSQL;
8. проверить возможность безопасного downgrade миграций.

Не создавай миграции, пока не сформирована проверенная модель SQLAlchemy и понятны перечисленные ограничения.
