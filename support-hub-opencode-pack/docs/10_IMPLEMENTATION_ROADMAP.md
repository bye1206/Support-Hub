# 10. План реализации

План предварительный. OpenCode должен уточнить его после аудита репозитория и фактических внешних API.

## Этап 0. Техническое обследование

Результат:
- аудит репозитория;
- перечень пробелов/противоречий;
- план работ;
- реестр решений и открытых вопросов.

Критерий готовности: владелец проекта согласовал этапы и блокеры.

## Этап 1. Bootstrap

Результат:
- структура монорепозитория или согласованного repo layout;
- backend skeleton;
- frontend skeleton;
- Docker Compose для локальной разработки;
- `.env.example`;
- базовые health endpoints;
- форматирование/lint/typecheck/test commands;
- CI, если доступно.

Не включать реальные секреты.

## Этап 2. Базовая инфраструктура Backend

- settings/config;
- structured logging и correlation ID;
- PostgreSQL connection/session management;
- Redis client;
- MinIO client;
- FastAPI app factory/lifespan;
- базовые тесты и error response schema.

## Этап 3. Домен и база данных

- каноническая ER-модель;
- SQLAlchemy models;
- Alembic migrations;
- пользователь/идентичность/канал;
- conversation/session/ticket/message;
- status transitions;
- sequence number и транзакционные гарантии.

Критерий: интеграционные тесты на настоящем PostgreSQL.

## Этап 4. Domain services и Outbox foundation

- TicketService;
- ConversationService;
- MessageService;
- AttachmentService;
- idempotent integration event persistence;
- Outbox event creation/worker/lease/retry.

## Этап 5. Tag + существующий Bot

- получить фактический код/контракт Bot;
- webhook callback normalization;
- Bot → Support Hub API;
- исходящие команды;
- сохранение delivery journal;
- вложения;
- reconciliation UNKNOWN outcomes.

Критерий: сквозной тест Tag webhook → тикет/сообщение → ответ в тестовый DM.

## Этап 6. AI Orchestrator

- изучить реальные API и JSON примеры;
- написать anti-corruption adapter;
- контекст из Support Hub messages;
- callbacks;
- последовательные AI runs;
- Handoff и stale response protection.

Критерий: тестовый end-to-end обмен с существующим Orchestrator.

## Этап 7. Operator API и realtime

- Keycloak OIDC;
- очереди и ticket list;
- ticket detail/messages;
- answer/notes/assignment/status;
- uploads;
- WebSocket authorization and events.

## Этап 8. Operator UI

- трёхколоночное рабочее место;
- очередь и фильтры;
- переписка и composer;
- notes mode;
- ticket details;
- SLA/assignment/user history;
- realtime reconnect.

## Этап 9. Admin API/UI

- operators/roles;
- teams/queues;
- categories/tags;
- canned responses;
- system settings;
- audit;
- integration diagnostics.

## Этап 10. SLA

- календарь;
- политика;
- расчёт first operator response/resolution;
- SLA cycles;
- breach events;
- UI indicators.

## Этап 11. Hardening и пилот

- security review;
- load/concurrency tests;
- backup/restore;
- monitoring;
- deployment runbook;
- pilot migration process;
- run in parallel with legacy CraftTalk where needed.

## Правило выполнения

Не переходить автоматически от этапа к этапу, создавая всё сразу. Каждый этап должен иметь план, diff, тесты и краткий отчёт владельцу проекта.
