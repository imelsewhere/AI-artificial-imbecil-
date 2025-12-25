# kb-agent (LangChain + GigaChat)

Цель: агент читает `knowledge_base/origins` (markdown) и создаёт/обновляет markdown‑карточки в `knowledge_base/cards_md`.

## Структура

- `knowledge_base/`
  - `origins/` — источники в `.md`
  - `cards_md/` — карточки знаний в `.md` (основной формат)
- `src/kb_agent/agent_init.py` — **инициализация агента** (отдельно)
- `src/kb_agent/tools.py` — **инструменты агента** (отдельно)
- `src/kb_agent/gigachat_client.py` — класс `GigaChat` (обёртка над `langchain-gigachat`)
- `scripts/run_agent.py` — пример запуска (CLI)
- `main.py` — самый простой запуск (без аргументов)

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Конфиг

Скопируйте `env.example.txt` в `.env` и заполните (локально у себя).

```bash
copy env.example.txt .env
```

Переменные:

- **`GIGACHAT_ACCESS_TOKEN`**: если у вас уже есть access token.
- **`GIGACHAT_AUTHORIZATION_KEY`**: если есть только Authorization key (Basic …) — токен будет запрошен автоматически через OAuth.
- **`GIGACHAT_SCOPE`**: обычно `GIGACHAT_API_PERS`.
- **`KB_CARDS_MD_DIR`**: папка для markdown-карточек (по умолчанию `knowledge_base/cards_md`).
- **`GIGACHAT_REQUEST_DELAY_S`**: пауза между запросами к модели (секунды). Полезно, если появляются сетевые ошибки/“битые” ответы.

Важно про безопасность:

- **Не храните ключи в коде/репозитории**.
- Если вы уже публиковали Authorization key/токен в чате или где-то ещё — **считайте его скомпрометированным и перевыпустите**.

## Быстрый старт

1) Положите markdown в `knowledge_base/origins/`.

2) Самый простой запуск:

```bash
python main.py
```

или через CLI-скрипт:

```bash
python scripts\run_agent.py sync
```

Это создаст/обновит markdown‑карточки в `knowledge_base/cards_md/`.
