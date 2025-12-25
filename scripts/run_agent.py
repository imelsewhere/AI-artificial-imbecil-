from __future__ import annotations

import sys
from pathlib import Path

# Allow running without `pip install -e .`
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kb_agent.agent_init import create_agent  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python scripts\\run_agent.py sync|coverage|chat \"your message\"")
        return 2

    cmd = argv[1].lower()
    agent, _ctx = create_agent(verbose=True, max_iterations=20)

    if cmd == "sync":
        res = agent.invoke(
            {
                "input": "Синхронизируй все markdown из knowledge_base/origins в JSON карточки в knowledge_base/cards. "
                "Используй kb_sync_all. Если JSON битый — перезапиши файл."
            }
        )
        print(res["output"] if isinstance(res, dict) and "output" in res else res)
        return 0

    if cmd == "coverage":
        res = agent.invoke(
            {
                "input": "Проверь покрытие: на каждый markdown должна быть минимум 1 JSON карточка. "
                "Используй kb_analyze_coverage и выведи missing/stale/invalid."
            }
        )
        print(res["output"] if isinstance(res, dict) and "output" in res else res)
        return 0

    if cmd == "chat":
        if len(argv) < 3:
            print('Usage: python scripts\\run_agent.py chat "your message"')
            return 2
        res = agent.invoke({"input": argv[2]})
        print(res["output"] if isinstance(res, dict) and "output" in res else res)
        return 0

    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))


