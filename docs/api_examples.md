# API curl examples

Примеры предполагают, что сервис запущен на `http://localhost:8000`.
Для защищённых маршрутов укажите действующий PocketBase JWT вместо `$TOKEN`.
Для POSIX shell задайте его так:

```sh
export TOKEN="your-pocketbase-jwt"
```

## Health

```sh
curl -i http://localhost:8000/health
```

## Обычный чат

```sh
curl -i http://localhost:8000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Какой срок рассмотрения приказа?",
    "history": [],
    "conversation_id": "curl-chat-example"
  }'
```

## Потоковый чат

`-N` отключает буферизацию curl, чтобы SSE-события отображались по мере поступления.

```sh
curl -i -N http://localhost:8000/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "message": "Перескажи п. 10.2",
    "history": [],
    "conversation_id": "curl-stream-example"
  }'
```

Поток содержит события `sources`, `delta` и `done`; при ошибке — событие `error`.
Ответ имеет тип `text/event-stream`.

## Валидация DOCX для базы знаний

```sh
curl -i http://localhost:8000/kb/validate \
  -F "file=@./document.docx"
```
