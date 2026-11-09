# 04. Tag и существующий Mattermost Bot

## 1. Контекст

Tag — корпоративный мессенджер на базе Mattermost. Существующий Mattermost Bot сохраняется и адаптируется как транспортный мост между Tag и Support Hub.

Предоставлена внутренняя документация Tag Bot Webhook API:
- владелец бота может настроить callback URL;
- при новом сообщении в Direct Message с ботом Tag отправляет HTTP POST на callback;
- webhook можно удалить.

Это корпоративная возможность Tag. Не утверждать, что такой endpoint есть в стандартном Mattermost.

## 2. Регистрация callback

Из предоставленного описания:

`POST https://tag.magnit.ru/api/v4/bots/me/webhook_url`

Тело:

```json
{"callback_url":"https://your-server.example/webhook"}
```

Удаление:

`DELETE https://tag.magnit.ru/api/v4/bots/me/webhook_url`

Авторизация — Bearer bot token. Реальный токен хранится только в защищённой конфигурации.

## 3. Известный payload webhook

```json
{
  "team_id": "team_id",
  "team_domain": "team_name",
  "channel_id": "channel_id",
  "channel_name": "channel_name",
  "timestamp": 1234567890,
  "user_id": "user_id",
  "user_name": "username",
  "post_id": "post_id",
  "text": "message text",
  "file_ids": "file1,file2"
}
```

Известные поля:
- `team_id`, `team_domain`;
- `channel_id`, `channel_name`;
- `timestamp`;
- `user_id`, `user_name`;
- `post_id`;
- `text`;
- `file_ids` — строка с разделёнными запятыми ID файлов.

`post_id` использовать как основной внешний идентификатор сообщения при обработке webhook.

`user_id`, а не `user_name`, является первичным внешним идентификатором пользователя.

## 4. Входящий поток

`Tag → callback существующего Bot → Bot normalizes payload → Support Hub ingress API → durable persistence → processing`.

Внутренний endpoint Support Hub, предложенный для проектирования:

`POST /api/v1/integrations/tag/messages`

Предлагаемый контракт — нормализованный JSON с event ID, channel ID, sender ID, source timestamp, текстом и массивом вложений. Это ещё не существующая реализация, а контракт между двумя нашими компонентами.

Support Hub подтверждает событие только после устойчивого сохранения в PostgreSQL. Дубликат по `(source='TAG', external_event_id=post_id)` не должен создавать повторное сообщение или повторную бизнес-обработку.

## 5. Исходящий поток

`Support Hub Outbox → existing Bot internal API → Tag`.

Support Hub передаёт команду существующему боту. Бот использует уже имеющуюся в его коде реализацию отправки сообщений в Tag. Если потребуется доработка, сверить конкретный endpoint, права и формат с официальной документацией Mattermost API v4 и особенностями корпоративной инсталляции Tag.

Первый пример с `POST /api/v4/posts`, `PUT /api/v4/posts/{post_id}`, алертным текстом, `@all`, timeout 5 секунд и fire-and-forget был предоставлен пользователем как пример из другого проекта. **Эти алертные настройки и поведение не являются требованиями Support Hub и не должны переноситься автоматически.**

Токен Tag хранится и используется на стороне существующего Mattermost Bot. Не помещать токен Tag в конфигурацию Support Hub, если архитектурно не будет отдельно согласовано обратное.

Внутренний endpoint Bot, предложенный в проектной спецификации:

`POST /internal/v1/tag/messages`

Он принимает delivery ID, внутренний message ID, внешний Tag channel ID, текст и attachment references. Бот возвращает внешний post ID и результат.

## 6. Вложения

Входящий payload содержит file IDs. Требуется выяснить, может ли текущий бот получить файл по стандартному endpoint Mattermost и какие права ему нужны. Предполагаемый стандартный endpoint:

`GET /api/v4/files/{file_id}`

Это нужно проверить на Tag deployment. После получения бинарного файла он передаётся Support Hub, проходит проверки и сохраняется в MinIO.

Для исходящего вложения Support Hub предоставляет боту защищённый endpoint получения файла; бот загружает файл в Tag и публикует пост с `file_ids`.

## 7. Надёжность

- Не терять webhook между приёмом Tag и передачей в Support Hub.
- Проверить, делает ли Tag retry при HTTP 5xx/timeout.
- Если бот подтверждает webhook до передачи в Support Hub, ему нужен durable inbox/очередь.
- Исходящие ответы должны иметь устойчивый delivery journal в боте либо поддерживать запрос статуса по delivery ID.
- Сетевой timeout после запроса POST может означать, что пост создан, но ответ не получен. Нужны состояние `UNKNOWN` и reconciliation; безусловный повтор может создать дубликат.
- Не публиковать внутренние заметки.

## 8. Неизвестные детали — не додумывать

- Callback authentication/signature/secret header.
- Повторяет ли Tag callback, сколько раз и с каким интервалом.
- Единицы `timestamp` (секунды или миллисекунды).
- Получает ли Bot callbacks на собственные сообщения/бот-события.
- Как исключить self-message loop на реальных payload.
- Права Bot на получение файлов и публикацию в DM.
- Точные лимиты файла и rate limits Tag.
- Текущий внутренний API и персистентность существующего бота.

До подтверждения этих пунктов не считать интеграцию production-ready.
