# 13. Статус API-проектирования

## Общий принцип

Ранее обсуждались API-группы:
- Bot/Tag Integration;
- AI Orchestrator Integration;
- Operator API;
- Admin API;
- Operator WebSocket.

Эти документы — проектные эскизы, не фактические OpenAPI-контракты.

## Известно по Tag

Пользователь предоставил описание Bot Webhook API:
- регистрация: `POST /api/v4/bots/me/webhook_url` с `callback_url`;
- удаление: `DELETE /api/v4/bots/me/webhook_url`;
- callback payload с team/channel/user/post/text/file_ids;
- исходящие посты через Mattermost REST API v4.

См. `04_TAG_AND_BOT_INTEGRATION.md`.

## Внутренние API Support Hub

Предложенные группы маршрутов:
- `/api/v1/integrations/tag/*`;
- `/api/v1/integrations/ai/*`;
- `/api/v1/operator/*`;
- `/api/v1/admin/*`;
- `/api/v1/operator/ws`.

Маршруты нужно унифицировать, проверить владельца каждого endpoint, схемы Pydantic, RBAC и error response.

## Не создавать OpenAPI автоматически из непроверенных примеров

Перед генерацией `openapi.yaml`:
1. утвердить ресурсы и действия;
2. согласовать idempotency и concurrency;
3. определить auth schemes;
4. описать error model;
5. проверить pagination;
6. проверить upload/download semantics;
7. согласовать реальный Bot contract и AI contract;
8. только после этого сформировать канонический OpenAPI документ.
