# PocketBase 0.40.x — справка для backend и фронта

Структура:

```
pocketbase/
├── Dockerfile                      # версия закреплена (ARG PB_VERSION=0.40.4)
├── docker-compose.pocketbase.yml   # фрагмент для основного compose
├── .env.example
├── pb_migrations/1700000001_schema.js, 1700000002_seed.js
├── pb_hooks/ingest.pb.js
└── smoke_test.sh
```

## Запуск

```bash
cp .env.example .env            # заполнить SEED_*_PASSWORD (>= 8 символов)
docker compose up -d --build pocketbase
./smoke_test.sh
# (необязательно) superuser для админки /_/ :
docker compose exec pocketbase /pb/pocketbase admin create you@example.com 'StrongPass123' --dir=/pb/pb_data
```

Миграции применяются один раз. Если старая схема/seed уже применены, пересоздайте volume
(`docker compose down -v`) либо добавьте отдельную миграцию с изменениями.
Seed завершится ошибкой, если не задана любая из `SEED_*_PASSWORD`.

## Текстовая схема связей

```
users (auth: role, access_level, department)
 ├─1──* document_versions.uploaded_by
 ├─1──* chat_sessions.user
 ├─1──* generated_drafts.user
 ├─1──* feedback.user
 └─1──* audit_log.user

documents
 ├─1──* document_versions.document
 └─0..1─ documents.current_version ──> document_versions   (циклическая связь; ставится хуком/seed'ом)

document_versions
 └─1──* module_templates.version                 (какая версия методики породила шаблон)

module_templates
 └─1──* generated_drafts.module

chat_sessions
 ├─1──* messages.session
 └─1──* generated_drafts.session

messages
 └─1──* feedback.message

Жизненный цикл version.status:
 draft ─(hook: POST /ingest 2xx)─> indexing ─(backend PATCH)─> active ─(активация новой)─> archived
   └──(hook: ошибка/не-2xx)──────────────────> failed <──(backend PATCH при ошибке)────┘
```

## Как FastAPI авторизуется в PocketBase

Сервисный пользователь создаётся seed'ом: `SEED_BACKEND_EMAIL` / `SEED_BACKEND_PASSWORD`,
`role=admin`, `access_level=3`. Правила коллекций написаны под `role=admin`, поэтому он может
PATCH-ить `document_versions`, писать `messages` и т.д. Токен действует ~14 дней: кэшируем и
перелогиниваемся при 401.

```python
import os, httpx
from datetime import datetime, timezone

class PB:
    def __init__(self):
        self.url = os.environ["PB_URL"]                       # http://pocketbase:8090
        self.email = os.environ["PB_SERVICE_EMAIL"]
        self.password = os.environ["PB_SERVICE_PASSWORD"]
        self.token: str | None = None
        self.http = httpx.AsyncClient(timeout=30)

    async def _login(self):
        r = await self.http.post(
            f"{self.url}/api/collections/users/auth-with-password",
            json={"identity": self.email, "password": self.password})
        r.raise_for_status()
        self.token = r.json()["token"]

    async def request(self, method, path, **kw):
        if not self.token:
            await self._login()
        for attempt in (1, 2):
            r = await self.http.request(method, f"{self.url}{path}",
                                        headers={"Authorization": self.token}, **kw)
            if r.status_code != 401 or attempt == 2:
                return r
            await self._login()

    async def finish_ingest(self, version_id, chunks, error=None):
        body = ({"status": "failed", "comment": error[:1000]} if error else
                {"status": "active", "chunks_count": chunks, "comment": "",
                 "indexed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000Z")})
        r = await self.request("PATCH", f"/api/collections/document_versions/records/{version_id}", json=body)
        r.raise_for_status()
```

Поток индексации:
1. Методолог загружает файл: `POST /api/collections/document_versions/records` (multipart, `status=draft`).
2. Хук `ingest.pb.js` шлёт `POST {BACKEND_URL}/ingest {"version_id": "..."}` с таймаутом 10 с.
   **FastAPI должен ответить 202 сразу** и индексировать в фоне (BackgroundTasks/очередь) —
   хук синхронный и держит HTTP-ответ загрузки. Не-2xx/таймаут → версия `failed`, причина в `comment`.
3. Backend читает запись и файл: `GET /api/collections/document_versions/records/{id}`,
   `GET /api/files/document_versions/{id}/{filename}` (заголовок `Authorization` тоже передавать).
4. По завершении — PATCH (`finish_ingest` выше). Переход в `active` запускает хук архивации:
   старая `current_version` → `archived`, `documents.current_version` → новая.

## Эндпоинты для SvelteKit

База: `{PB_URL}/api`. Токен — в заголовке `Authorization: <token>` (SDK делает это сам).
Фильтры передавать URL-кодированными (`curl -G --data-urlencode`).
Admin видит все записи в `chat_sessions` и т.п., поэтому в UI всегда добавляйте `user="{id}"`.

| Что | Метод и путь | Фильтры / тело | Кто |
|---|---|---|---|
| Логин | `POST /collections/users/auth-with-password` | `{"identity":"email","password":"..."}` → `token`, `record` (там `role`, `access_level`) | все |
| Обновить токен | `POST /collections/users/auth-refresh` | заголовок Authorization | auth |
| Свой профиль | `GET /collections/users/records/{id}` | — | auth (себя) |
| Правка профиля | `PATCH /collections/users/records/{id}` | `{"name":..,"department":..}`; `role`/`access_level` → отказ | employee/methodologist: себя; admin: любого |
| Список документов | `GET /collections/documents/records` | `expand=current_version&sort=-updated`; `filter=status="active"`; `filter=doc_type="instruction"` | auth (employee — по access_level и active) |
| Версии документа | `GET /collections/document_versions/records` | `filter=document="ID"&sort=-created`; `filter=status="failed"` | employee — только active своего уровня; methodologist/admin — все |
| Загрузка версии | `POST /collections/document_versions/records` | multipart: `document, version_label, file, status=draft, access_level, uploaded_by` | methodologist/admin |
| Активировать/архивировать | `PATCH /collections/document_versions/records/{id}` | `{"status":"active"}` | methodologist/admin, backend |
| Шаблоны модулей | `GET /collections/module_templates/records` | `filter=is_active=true&sort=title`; `filter=code="order_handover"`; `filter=doc_kind="приказ"` | auth |
| Мои сессии | `GET /collections/chat_sessions/records` | `filter=user="ID" && status="active"&sort=-updated` | auth |
| Новая сессия | `POST /collections/chat_sessions/records` | `{"user":"<свой id>","title":"..","status":"active"}` | auth |
| Закрыть сессию | `PATCH /collections/chat_sessions/records/{id}` | `{"status":"closed"}` | владелец/admin |
| Сообщения сессии | `GET /collections/messages/records` | `filter=session="SID"&sort=created&perPage=200` | владелец/admin |
| Сообщение пользователя | `POST /collections/messages/records` | `{"session":"SID","role":"user","content":".."}` | владелец сессии/admin |
| Realtime | SDK `pb.collection('messages').subscribe('*', cb, {filter:'session="SID"'})` | SSE `/realtime` | владелец/admin |
| Черновики | `GET/POST /collections/generated_drafts/records` | `filter=session="SID"`; POST: `{"session","user":"<свой id>","module","status":"filling","fields_values":{}}` | владелец |
| Обновить черновик | `PATCH /collections/generated_drafts/records/{id}` | `{"fields_values":{..},"status":"ready"}` | владелец/admin |
| Оценка ответа | `POST /collections/feedback/records` | `{"message":"MID","user":"<свой id>","rating":"up","comment":".."}` | автор сессии сообщения |
| Журнал аудита | `GET /collections/audit_log/records` | `sort=-created&expand=user&filter=action="login"` | admin |
| Запись аудита | `POST /collections/audit_log/records` | `{"user":"<свой id>","action":"..","entity":"..","entity_id":"..","meta":{}}` | auth (только от своего имени) |
| Файлы | `GET /files/{collection}/{recordId}/{filename}` | `?thumb=` для картинок | по правилам view записи |

Примеры:

```bash
PB=http://localhost:8090/api
TOKEN=$(curl -s $PB/collections/users/auth-with-password \
  -H 'Content-Type: application/json' \
  -d '{"identity":"employee@test.local","password":"..."}' | jq -r .token)

# сообщения сессии
curl -sG $PB/collections/messages/records -H "Authorization: $TOKEN" \
  --data-urlencode 'filter=session="SESSION_ID"' --data-urlencode 'sort=created'

# активные шаблоны-приказы
curl -sG $PB/collections/module_templates/records -H "Authorization: $TOKEN" \
  --data-urlencode 'filter=is_active=true && doc_kind="приказ"'
```

SvelteKit (`hooks.server.ts`):

```ts
import PocketBase from 'pocketbase';
export const handle = async ({ event, resolve }) => {
  event.locals.pb = new PocketBase(env.PB_URL);
  event.locals.pb.authStore.loadFromCookie(event.request.headers.get('cookie') ?? '');
  try {
    if (event.locals.pb.authStore.isValid) await event.locals.pb.collection('users').authRefresh();
  } catch { event.locals.pb.authStore.clear(); }
  const res = await resolve(event);
  res.headers.append('set-cookie', event.locals.pb.authStore.exportToCookie({ httpOnly: true, secure: true }));
  return res;
};
```

Коды ошибок: при отказе правил `create` PocketBase отвечает 400, `view/update/delete` — 404 (запись «не найдена»),
`list` просто отфильтровывает записи.

