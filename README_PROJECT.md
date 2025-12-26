
сгенерировал робот

# kb-agent — технический README (архитектура проекта)

Этот документ дополняет основной `README.md` и объясняет **как устроен проект внутри**:
схемы данных, инструменты (tools), поток обработки и назначение каждого файла.

## Что делает проект

Проект синхронизирует базу знаний:

- **Вход**: документы-источники в `knowledge_base/origins/*.md` (markdown).
- **Выход**: набор **markdown‑карточек** в `knowledge_base/cards_md/*.md`.

Каждый документ из `origins/` должен иметь минимум одну карточку в `cards_md/`.
Если документ изменился — соответствующие карточки перегенерируются.

## Структура директорий

- `knowledge_base/`
  - `origins/` — исходники (markdown). Это **источник истины**.
  - `cards_md/` — сгенерированные карточки (markdown). Это **результат**.
  - `cards/` — зарезервировано под JSON‑карточки (в текущем пайплайне не является основным выходом).
- `src/kb_agent/` — код агента и инструментов.
- `main.py` — самый простой запуск “сделай синхронизацию”.
- `scripts/run_agent.py` — CLI‑пример запуска.

## Поток обработки (pipeline)

Реальный пайплайн находится в `src/kb_agent/tools.py`, функция `kb_upsert_cards_for_markdown()`:

1) Читаем исходный markdown из `knowledge_base/origins/<file>.md`.
2) Вызываем “писателя” (LLM) и получаем список карточек в структурированном виде (Pydantic).
3) Вызываем “судью” (LLM), который проверяет покрытие документа карточками.
4) Если судья говорит `ok=false`, выполняем **один** до‑прогон писателем с подсказкой “что не покрыто”.
5) Записываем итоговые карточки в `knowledge_base/cards_md/` в заданном формате.




## Формат markdown‑карточки (`knowledge_base/cards_md/*.md`)

Каждая карточка — обычный markdown файл:

- В начале идёт строка с кратким описанием в “рамке”:
  - `-- <description> --`
- Далее — тело карточки: `content_md` (markdown).
- В конце — HTML‑комментарий с метаданными источника и хэшом:
  - `<!-- source: origins/<path> source_sha256: <hex> -->`

Зачем `source_sha256`:

- Для проверки устаревания карточек: если sha в карточке не совпадает с sha текущего документа — карточка считается **stale** и должна быть обновлена.

## Инструменты агента (LangChain tools)

Инструменты объявлены в `src/kb_agent/tools.py` и регистрируются в `build_tools()`.

- **`kb_read_directory`**
  - Возвращает дерево/состояние `knowledge_base` (список документов в `origins` и карточек в `cards_md`).

- **`kb_read_markdown`**
  - Читает конкретный документ из `knowledge_base/origins` по относительному пути.

- **`kb_analyze_coverage`**
  - Проверяет покрытие:
    - `missing_cards_for_origins`: для каких `origins/*.md` нет карточек в `cards_md`.
    - `stale_cards_for_origins`: для каких документов карточки есть, но sha не совпадает / отсутствует.
    - `invalid_card_md_files`: ошибки чтения/формата карточек.

- **`kb_upsert_cards_for_markdown`**
  - Создаёт/обновляет карточки для одного документа.
  - Сначала удаляет старые карточки этого документа (по шаблону `card_*_<stem>.md`), затем пишет новые.

- **`kb_sync_all`**
  - Прогоняет `kb_upsert_cards_for_markdown` по всем документам в `origins/`.

- **`kb_set_role`**
  - Меняет “роль” агента (внутренняя инструкция), которая подставляется в промпты генерации.

## Схемы данных (Pydantic)

Проект принуждает LLM отвечать **строго JSON‑объектом** (не текстом) и валидирует его Pydantic’ом.
Это делает генерацию существенно стабильнее.

Схемы описаны в `src/kb_agent/tools.py`:

- **`CardDraft`**
  - `title`: заголовок карточки
  - `description`: 1–2 предложения (используется в строке `-- ... --`)
  - `content_md`: тело карточки в markdown
  - `key_terms`: термины
  - `entities`: сущности (люди/орг/продукты/сервисы)

- **`WriterResult`**
  - `cards: list[CardDraft]`

- **`JudgeResult`**
  - `ok: bool`
  - `missing: list[MissingItem]` где `MissingItem` содержит:
    - `what`: что отсутствует
    - `evidence`: **дословная цитата** из оригинального документа
  - `suggested_card_titles`: предлагаемые заголовки карточек

Технически разбор происходит через `PydanticOutputParser` и `_llm_parse_pydantic()`:
если модель ответила “не по схеме”, код делает репромпт и просит вернуть **только JSON со значениями**.

## Назначение файлов (по одному)

### Entrypoints

- `main.py`
  - Минимальный запуск: добавляет `src/` в `sys.path` (чтобы работало без `pip install -e .`),
    создаёт агента и даёт ему задачу “синхронизировать origins → cards_md”.

- `scripts/run_agent.py`
  - Пример CLI:
    - `sync`: просит агента сделать `kb_sync_all`
    - `coverage`: просит агента сделать `kb_analyze_coverage`
    - `chat`: произвольное сообщение

### `src/kb_agent/`

- `__init__.py`
  - Маркер пакета.

- `config.py`
  - Читает `.env`/env vars и формирует:
    - `KBPaths` (пути к `knowledge_base/*`)
    - `GigaChatSettings` (base_url/model/token/timeout и т.д.)

- `oauth.py`
  - Утилита для получения `access_token` через OAuth по `authorization_key` (Basic …).

- `gigachat_client.py`
  - Обёртка `GigaChat`, которая создаёт LangChain‑модель `langchain_gigachat.chat_models.GigaChat`
    с правильными параметрами (base_url/model/verify_ssl_certs/scope/timeout).

- `agent_init.py`
  - Создаёт LangChain‑агента через `initialize_agent(...)`:
    - подключает tools из `tools.py`
    - подключает память `ConversationBufferMemory`
    - настраивает `handle_parsing_errors` и `max_iterations`

- `tools.py`
  - Основная бизнес‑логика:
    - инструменты `kb_*`
    - промпты писателя/судьи
    - схемы Pydantic
    - генерация, проверка и запись карточек в `cards_md/`

- `cards.py`
  - Утилиты для работы с данными/текстом:
    - sha256 файла
    - извлечение заголовка из markdown
    - извлечение ссылок
    - (опционально) JSON‑формат карточек через `KnowledgeCard`/`write_card_file` (может быть использовано в будущем)

## Конфиг (env vars)

Список переменных и пример — см. `README.md` и `env.example.txt`.
Ключевые:

- `GIGACHAT_ACCESS_TOKEN` или `GIGACHAT_AUTHORIZATION_KEY`
- `GIGACHAT_MODEL`
- `KB_ROOT`, `KB_ORIGINS_DIR`, `KB_CARDS_MD_DIR`
