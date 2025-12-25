from __future__ import annotations

import sys
from pathlib import Path

# Allow running without `pip install -e .`
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kb_agent.agent_init import create_agent  # noqa: E402


def main() -> int:
    """
    Просто запускайте: `python main.py`

    По умолчанию агент синхронизирует `knowledge_base/origins` -> `knowledge_base/cards`.
    """
    # Чуть помогает Windows-консолям корректно печатать кириллицу
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    agent, _ctx = create_agent(verbose=True, max_iterations=6)

    # Сразу даём задачу агенту (без CLI/аргументов)
    res = agent.invoke(
        {
            "input": (
                "Ты агент по обслуживанию базы знаний.\n\n"
                "Идеальная структура директорий:\n"
                "- knowledge_base/origins: markdown источники (.md)\n"
                "- knowledge_base/cards_md: карточки знаний (.md)\n\n"
                "Цель: привести knowledge_base/cards_md в соответствие с knowledge_base/origins.\n"
                "Критерии готовности:\n"
                "- на каждый документ в origins должна существовать минимум 1 markdown-карточка в cards_md\n"
                "- если markdown изменился, карточка должна быть обновлена\n"
                "- карточка должна быть оформлена как markdown в формате примеров (-- описание -- + тело)\n\n"
                "Доступные инструменты: kb_read_directory, kb_read_markdown, kb_analyze_coverage, "
                "kb_upsert_cards_for_markdown, kb_sync_all, kb_set_role.\n\n"
                "Сам реши, какие инструменты и в каком порядке использовать, чтобы добиться цели.\n"
                "Важно: не делай двойную работу. Выбери ОДИН подход:\n"
                "- либо kb_sync_all (и не вызывай отдельно kb_upsert_cards_for_markdown),\n"
                "- либо kb_analyze_coverage -> kb_upsert_cards_for_markdown только для missing/stale (и не вызывай kb_sync_all).\n"
                "Не спрашивай подтверждений у пользователя — просто делай.\n"
                "В конце дай короткий итог (1–2 предложения): что сделал и есть ли проблемы.\n"
            )
        }
    )
    out = res["output"] if isinstance(res, dict) and "output" in res else res
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


