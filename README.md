# Ассистент по Инструкции по ДОУ: запуск

Всё работает локально (Windows, PowerShell). Нужно запустить **4 вещи** в таком порядке:

| № | Что | Где | Порт |
|---|---|---|---|
| 1 | LM Studio (модель) | приложение | 1234 |
| 2 | PocketBase (БД, пользователи) | `src\pocketbase\pocketbase-project` | 8090 |
| 3 | Бэкенд (поиск, ответы) | `src\backend\rag_service` | 8000 |
| 4 | Сайт | `src\frontend` | 5173 |

Пути ниже даны от корня репозитория (`hakatonai`). Если у вас папки лежат глубже (например, внутри `cbr-dou-assistant`), добавьте этот префикс.

---

## 0. Один раз при первой установке

**Программы:** Python 3.11+, Node.js 20+, LM Studio, PocketBase **0.22.x** (не новее: хуки и миграции написаны под 0.22).

**Модель:** в LM Studio скачать `qwen3.5-9b` (Q4_K_M). Настройки модели: GPU offload на максимум, Context Length 8192. Режим рассуждений (thinking) выключить: в настройках модели, Prompt Template, первой строкой добавить `{%- set enable_thinking = false %}`, затем Eject и Load.

**Бэкенд:**
```powershell
cd src\backend\rag_service
pip install -r requirements.txt
```
Первый запуск скачивает модель эмбеддингов `BAAI/bge-m3` (~2 ГБ, нужен интернет). Дальше работает без интернета.

**Индекс** (один раз и после любой смены данных; 2-5 минут на CPU):
```powershell
cd src\backend\rag_service
$env:PYTHONUTF8="1"
python -m app.ingest --file data/corpus_chunks.json
```
Ожидаемый итог: `indexed ОД-184: {'total': 361, 'indexed': 360, ... 'dense': True}`.

**Сайт:**
```powershell
cd src\frontend
npm install
```
Создайте файл `.env` рядом с `package.json`:
```
VITE_BACKEND_URL=http://127.0.0.1:8000
VITE_PB_URL=http://127.0.0.1:8090
```
Именно `127.0.0.1`, не `localhost` (на Windows `localhost` может уходить на IPv6, и соединение не проходит).

**PocketBase:** скопируйте `.env.example` в `.env` (папка `src\pocketbase\pocketbase-project`) и задайте пароли пользователей:
```
SEED_EMPLOYEE_PASSWORD=...
SEED_METHODOLOGIST_PASSWORD=...
SEED_ADMIN_PASSWORD=...
SEED_BACKEND_PASSWORD=...
```
Пароли применяются только при первом создании пользователей. После смены пароля старые токены перестают действовать.

---

## 1. Каждый запуск

### Окно 1. LM Studio
1. Открыть LM Studio, загрузить `qwen3.5-9b`.
2. Вкладка **Developer → Start Server**. Проверка: http://localhost:1234/v1/models показывает модель.
3. Закрыть программы, занимающие видеопамять (модель использует ~7,5 из 8 ГБ).

### Окно 2. PocketBase
```powershell
cd src\pocketbase\pocketbase-project
powershell -ExecutionPolicy Bypass -File .\run_pb.ps1
```
Файл `run_pb.ps1`:
```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[A-Za-z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process')
}
$env:BACKEND_URL = "http://127.0.0.1:8000"
./pocketbase.exe serve
```
Проверка: http://127.0.0.1:8090/_/ открывается (при первом входе создайте админа панели).

### Окно 3. Бэкенд
```powershell
cd src\backend\rag_service
powershell -ExecutionPolicy Bypass -File .\run_backend.ps1
```
Файл `run_backend.ps1`:
```powershell
$env:PYTHONUTF8     = "1"
$env:HF_HUB_OFFLINE = "1"
$env:PB_URL         = "http://127.0.0.1:8090"
$env:AUTH_MODE      = "dev"      # без проверки токена (для записи видео); на защите: "pocketbase"
$env:LLM_BASE_URL   = "http://localhost:1234/v1"
$env:LLM_MODEL      = "qwen3.5-9b"
uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```
Дождитесь строки `Application startup complete`. Проверка: http://127.0.0.1:8000/health должен показать `"ok": true`, `"chunks": 360`, `"dense": true`.

### Окно 4. Сайт
```powershell
cd src\frontend
npm run dev
```
Адрес из строки `Local:` (обычно http://localhost:5173).

---

## 2. Проверка после запуска

1. Открыть сайт **без входа** (гостевой режим работает при `AUTH_MODE=dev`).
2. Задать **два прогревочных** вопроса (первый ответ после старта идёт до 30 с):
   - «Какой срок рассмотрения приказа по основной деятельности?» → 10 рабочих дней, п. 10.3
   - «командировочные» → вежливый отказ
3. Дальше можно записывать.

## 3. Остановка
Ctrl+C в каждом окне; LM Studio: Stop Server.

---

## 4. Если что-то не работает

| Симптом | Причина | Что сделать |
|---|---|---|
| `/chat` отвечает 503, `/health`: `chunks: 0` | индекс пуст | выполнить `python -m app.ingest --file data/corpus_chunks.json`, перезапустить бэкенд |
| `/chat` 401 | бэкенд не в режиме `dev`, либо токен устарел | `echo $env:AUTH_MODE` в окне бэкенда должен вывести `dev`; на сайте очистить `pb_token` в Local Storage (F12 → Application) |
| Сайт: «Нет связи с AI-сервисом» | CORS или неверный адрес | в `.env` сайта `127.0.0.1`; проверить `CORSMiddleware` в `app\api\main.py` (разрешён порт сайта); перезапустить `npm run dev` после правки `.env` |
| Первый ответ 30+ с | холодный старт эмбеддера и модели | сделать прогревочные вопросы |
| PocketBase: `onRecordAfterCreateRequest is not defined` или `no such column: key` | версия новее 0.22 | поставить PocketBase 0.22.x, папку `pb_data` переименовать, запустить заново |
| PocketBase: `SEED_..._PASSWORD обязательна` | не заданы переменные | запускать через `run_pb.ps1`, проверить `.env` |
| Русский текст «крякозябрами» в консоли | кодировка окна | `chcp 65001` и `$env:PYTHONUTF8="1"` |
| Ответы с жёстким «информации нет» на нормальные вопросы | порог отказа или поиск | пришлите вопрос и вывод `python scripts/chat_cli.py --debug` |
| Бэкенд падает при загрузке модели | не хватает видеопамяти | закрыть браузерные вкладки с видео и игры; контекст модели не выше 8192 |

## 5. Проверки

```powershell
cd src\backend\rag_service
python tests/check_chat.py --live          # три базовых вопроса с реальной моделью
python scripts/chat_cli.py --debug         # чат в консоли с отладкой
python -m pytest tests -q                  # автотесты
```

## 6. Известные ограничения прототипа
- Вход через PocketBase и проверка токена в разработке: для записи демо используется гостевой режим.
- Заполнение модулей документов и загрузка новых версий через интерфейс: в работе.
- Реранкер отключён (`rerank: false`): на текущем наборе не даёт выигрыша.
