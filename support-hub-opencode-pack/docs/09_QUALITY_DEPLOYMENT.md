# 09. Качество, тестирование и развёртывание

## 1. Технические требования

- Модульный монолит.
- Docker Compose для MVP on-prem.
- Nginx reverse proxy.
- PostgreSQL, Redis, MinIO.
- Backend API и worker процессы.
- Frontend web application.
- Keycloak/LDAP и AI Orchestrator могут быть существующими внешними сервисами.

## 2. Качество кода

Backend:
- Python typing;
- SQLAlchemy 2 typed mappings;
- Pydantic v2;
- Ruff;
- mypy или Pyright;
- Pytest.

Frontend:
- TypeScript strict mode;
- единая стратегия lint/typecheck/test/build;
- React components по функциональным областям.

Не фиксировать конкретный frontend package manager до осмотра репозитория и решения команды.

## 3. Тестирование

### Unit

- domain services;
- status transitions;
- permission checks;
- SLA calculations;
- payload normalization.

### Integration

- PostgreSQL constraints и migrations;
- Redis presence/locks;
- MinIO file lifecycle;
- Outbox worker;
- Tag Bot adapter с mock HTTP;
- AI adapter с mock callback.

### Concurrency

- два оператора одновременно claim один тикет;
- два одинаковых входящих webhook;
- несколько сообщений в один диалог;
- AI response одновременно с Handoff;
- worker crash при PROCESSING Outbox event.

### Security

- unauthorized/forbidden endpoints;
- cross-ticket data leakage;
- internal notes leakage;
- file access control;
- secret leakage in logs.

## 4. Производительность

Ориентиры, которые обсуждались, являются предварительными и должны подтверждаться измерениями:
- список тикетов и карточка — комфортно, ориентир до 1 секунды при обычной нагрузке;
- сохранение сообщения — ориентир до 500 мс без ожидания внешней доставки;
- realtime update — ориентир до 1 секунды после публикации события.

Время выполнения RAG/AI не входит в latency сохранения сообщения.

## 5. Надёжность

- PostgreSQL backup и проверка restore.
- Резервирование MinIO.
- Health/readiness checks.
- Worker recovery.
- Retry policies с backoff.
- Отслеживание FAILED и UNKNOWN integrations.
- RPO/RTO согласовать с инфраструктурной командой.

## 6. Не делать без обоснования

- Не вводить Kubernetes на MVP.
- Не использовать SQLite для замены PostgreSQL в тестах целостности/конкурентности.
- Не ставить брокер сообщений сверх Redis без измеренной необходимости.
- Не логировать всё тело каждого запроса без фильтрации.

## 7. Чек-лист развертывания (заполнить при внедрении)

Секреты в хранилище, не в репозитории (D-046). Владелец + агент сверяются
по этому списку на каждом развертывании:

1. \AUTH_LOCAL_PASS\ — пароль аварийного аккаунта \reakglass\ (D-047):
   задать в vault/ENV вне git; проверить вход при выключенном AD.
2. \LDAP_ENABLED=true\ + \LDAP_HOST/PORT/DOMAIN/BASE_DN\ + DN групп
   (\support_hub_operator\/\support_hub_admin\/\support_hub_supervisor\;
   несколько DN — через \;\). После включения LDAP dev-токен отключается.
3. \LDAP_SERVICE_USER_DN\/\LDAP_SERVICE_PASSWORD\ — сервисная учётка
   только на чтение AD для карточки «Сотрудник» (P-29): группы, дата смены
   пароля, фото. Без неё блок скрывается сам (деградация штатная).
4. \BOT_WEBHOOK_TOKEN\ и URL вебхука бота Tag: \POST /api/v4/bots/me/
   webhook_url\ в Tag с \callback_url\ = адрес
   \/api/v1/integrations/tag/messages\ нашего сервера (дока владельца
   2026-11-11); callback шлёт payload OutgoingWebhook (user_id — id Tag,
   не доменный логин; сопоставление с AD — по \user_name\).
5. \AI_GATEWAY\ ключи/URL (D-043): \X-API-Key\, \X-User-Id\.
6. TLS/сертификаты: corp root CA в \LDAP_CA_CERT_FILE\ + включить
   \LDAP_TLS_VERIFY=true\, когда цепочка доступна.
7. Прогнать миграции (\lembic upgrade head\), smoke: \/healthz\,
   \/readyz\, вход оператора, вебхук бота, карточка AD.
