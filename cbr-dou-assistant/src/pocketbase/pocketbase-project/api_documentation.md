## Эндпоинты для SvelteKit

| Действие | Метод | Эндпоинт API | Тело запроса / Фильтр |
| :--- | :--- | :--- | :--- |
| **Вход** | POST | `/api/collections/users/auth-with-password` | `{"identity": "employee@test", "password": "..."}` |
| **Список чатов** | GET | `/api/collections/chat_sessions/records` | `?filter=(user='<user_id>')&sort=-created` |
| **Создать диалог**| POST | `/api/collections/chat_sessions/records` | `{"user": "<id>", "title": "Новый вопрос", "status": "active"}`|
| **Сообщения** | GET | `/api/collections/messages/records` | `?filter=(session='<session_id>')&sort=created` |
| **Отправить msg** | POST | `/api/collections/messages/records` | `{"session": "<id>", "role": "user", "content": "Текст"}` |
| **Шаблоны** | GET | `/api/collections/module_templates/records` | `?filter=(is_active=true)` |
| **Черновики** | GET | `/api/collections/generated_drafts/records` | `?filter=(user='<user_id>')&expand=module` |
| **Фидбек** | POST | `/api/collections/feedback/records` | `{"message": "<msg_id>", "user": "<id>", "rating": "up"}` |
| **Логирование** | POST | `/api/collections/audit_log/records` | `{"user": "<id>", "action": "LOGIN", "ip": "127.0.0.1"}` |

## Схема связей
* `users` 1──∞ `chat_sessions`, `audit_log`, `generated_drafts`
* `chat_sessions` 1──∞ `messages`, `generated_drafts`
* `messages` 1──∞ `feedback`
* `documents` 1──∞ `document_versions`
* `documents` ◄── `current_version` ──1 `document_versions`
* `document_versions` 1──∞ `module_templates`
* `module_templates` 1──∞ `generated_drafts`