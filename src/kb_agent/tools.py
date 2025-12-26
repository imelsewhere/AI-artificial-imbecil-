from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from langchain.tools import StructuredTool
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser

from kb_agent.cards import extract_title, file_sha256, utc_now_iso
from kb_agent.config import KBPaths


@dataclass
class ToolContext:
    kb: KBPaths
    llm: Any  # LangChain chat model
    request_delay_s: float = 0.0
    role: str = (
        "Ты агент по обслуживанию базы знаний. "
        "Твоя задача: синхронизировать markdown из knowledge_base/origins с JSON карточками в knowledge_base/cards. "
        "Если полезно, можешь менять свою роль/фокус через инструмент kb_set_role."
    )


def _resolve_origin(ctx: ToolContext, rel_path: str) -> Path:
    p = (ctx.kb.origins_dir / rel_path).resolve()
    if not str(p).startswith(str(ctx.kb.origins_dir.resolve())):
        raise ValueError("Path escapes origins_dir")
    return p


def _origin_rel(ctx: ToolContext, path: Path) -> str:
    return path.resolve().relative_to(ctx.kb.origins_dir.resolve()).as_posix()


def _card_path_for_origin(ctx: ToolContext, origin_rel_path: str) -> Path:
    # сохраняем структуру подпапок + меняем расширение на .json
    rel = Path(origin_rel_path)
    return (ctx.kb.cards_dir / rel).with_suffix(".json")


def _list_markdown_files(ctx: ToolContext) -> list[Path]:
    if not ctx.kb.origins_dir.exists():
        return []
    exts = {".md", ".yml", ".yaml"}
    return sorted([p for p in ctx.kb.origins_dir.rglob("*") if p.is_file() and p.suffix.lower() in exts])


def _list_card_files(ctx: ToolContext) -> list[Path]:
    if not ctx.kb.cards_md_dir.exists():
        return []
    return sorted([p for p in ctx.kb.cards_md_dir.rglob("*.md") if p.is_file() and p.name != ".gitkeep"])


def kb_read_directory(ctx: ToolContext, relative_to_kb_root: bool = True) -> dict[str, Any]:
    """
    Возвращает дерево `knowledge_base` и краткие списки origins/cards.
    """
    root = ctx.kb.root
    origins = _list_markdown_files(ctx)
    cards = _list_card_files(ctx)

    def _fmt(p: Path) -> str:
        if relative_to_kb_root:
            return p.resolve().relative_to(root.resolve()).as_posix()
        return str(p)

    return {
        "kb_root": str(root),
        "origins_dir": str(ctx.kb.origins_dir),
        "cards_md_dir": str(ctx.kb.cards_md_dir),
        "markdown_files": [_fmt(p) for p in origins],
        "card_md_files": [_fmt(p) for p in cards],
        "counts": {"origins": len(origins), "cards_md": len(cards)},
    }


def kb_read_markdown(ctx: ToolContext, origin_rel_path: str, max_chars: int = 12000) -> dict[str, Any]:
    if not origin_rel_path:
        raise ValueError("origin_rel_path is required")
    path = _resolve_origin(ctx, origin_rel_path)
    text = path.read_text(encoding="utf-8")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[TRUNCATED]"
    stat = path.stat()
    return {
        "path": origin_rel_path,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "content": text,
    }


def kb_analyze_coverage(ctx: ToolContext, include_stale: bool = True) -> dict[str, Any]:
    md_files = _list_markdown_files(ctx)
    missing: list[str] = []
    stale: list[str] = []
    invalid: list[str] = []

    def _extract_sha_from_md_card(text: str) -> str | None:
        # ожидаем HTML-комментарий в конце: <!-- source_sha256: <hex> -->
        marker = "source_sha256:"
        idx = text.rfind(marker)
        if idx == -1:
            return None
        tail = text[idx + len(marker) :].strip()
        sha = tail.split()[0].strip()
        return sha if len(sha) >= 32 else None

    for md in md_files:
        rel = _origin_rel(ctx, md)
        stem = Path(rel).stem
        card_files = list(ctx.kb.cards_md_dir.glob(f"card_*_{stem}.md")) if ctx.kb.cards_md_dir.exists() else []
        if not card_files:
            missing.append(rel)
            continue

        if include_stale:
            current_hash = file_sha256(md)
            # stale если хотя бы одна карточка не содержит sha или sha не совпадает
            bad = False
            for cf in card_files:
                try:
                    txt = cf.read_text(encoding="utf-8")
                    sha = _extract_sha_from_md_card(txt)
                    if not sha or sha != current_hash:
                        bad = True
                        break
                except Exception as e:
                    invalid.append(f"{rel}: {cf.name}: {type(e).__name__}: {e}")
                    bad = True
                    break
            if bad:
                stale.append(rel)

    return {
        "origins_total": len(md_files),
        "missing_cards_for_origins": missing,
        "stale_cards_for_origins": stale,
        "invalid_card_md_files": invalid,
    }


def kb_set_role(ctx: ToolContext, role: str) -> dict[str, Any]:
    before = ctx.role
    role = (role or "").strip()
    if not role:
        raise ValueError("role is empty")
    ctx.role = role
    return {"ok": True, "before": before, "after": ctx.role}


def _invoke_llm_text(ctx: ToolContext, prompt: str) -> str:
    if ctx.request_delay_s and ctx.request_delay_s > 0:
        time.sleep(float(ctx.request_delay_s))
    msg = ctx.llm.invoke(prompt)
    content = getattr(msg, "content", msg)
    if isinstance(content, list):
        content = "".join(str(x) for x in content)
    return str(content).strip()


def _llm_parse_pydantic(ctx: ToolContext, *, prompt: str, model: type[BaseModel], attempts: int = 3) -> BaseModel:
    """
    Надёжный разбор ответа через PydanticOutputParser + репромпт при ошибках.
    """
    parser = PydanticOutputParser(pydantic_object=model)
    fmt = parser.get_format_instructions()
    full_prompt = f"{prompt}\n\n{fmt}\n"

    last_text = ""
    for i in range(attempts):
        last_text = _invoke_llm_text(ctx, full_prompt)
        try:
            # Иногда модель возвращает JSON Schema вместо объекта значений.
            try:
                obj = json.loads(last_text)
                if isinstance(obj, dict) and ("properties" in obj and ("required" in obj or "$defs" in obj)):
                    raise ValueError("Model returned JSON schema, not values")
            except json.JSONDecodeError:
                pass
            return parser.parse(last_text)
        except Exception:
            # Репромпт: попросить исправить строго под формат
            full_prompt = (
                f"{prompt}\n\n{fmt}\n\n"
                "Ответ выше не соответствует формату. Верни ТОЛЬКО JSON-ОБЪЕКТ со ЗНАЧЕНИЯМИ полей, НЕ JSON Schema.\n"
                f"Предыдущий ответ:\n{last_text}\n"
            )
            if i == attempts - 1:
                raise
    raise RuntimeError("unreachable")


class CardDraft(BaseModel):
    title: str = Field(description="Заголовок карточки")
    description: str = Field(description="Короткое описание карточки (1-2 предложения) — пойдет в блок между -- --")
    content_md: str = Field(
        description="Основное содержимое карточки в markdown (заголовки/пункты/кодовые фрагменты при необходимости)"
    )
    key_terms: list[str] = Field(default_factory=list, description="Ключевые термины")
    entities: list[str] = Field(default_factory=list, description="Сущности (люди/орг/продукты/сервисы)")


class WriterResult(BaseModel):
    cards: list[CardDraft] = Field(description="Список карточек (1..20)")


class JudgeResult(BaseModel):
    ok: bool = Field(description="Покрывает ли набор карточек документ")
    class MissingItem(BaseModel):
        what: str = Field(description="Что именно отсутствует/потерялось в карточках")
        evidence: str = Field(
            description="Дословная цитата/фрагмент из ОРИГИНАЛЬНОГО документа, который подтверждает, что это знание там есть"
        )

    missing: list[MissingItem] = Field(default_factory=list, description="Что не покрыто (с доказательством из оригинала)")
    suggested_card_titles: list[str] = Field(default_factory=list, description="Какие карточки добавить (заголовки)")


def _writer_prompt(
    ctx: ToolContext,
    *,
    origin_rel_path: str,
    doc_text: str,
    guidance: str | None = None,
    existing_cards_json: str | None = None,
) -> str:
    """
    "Агент-писатель": предлагает разбиение документа на несколько карточек.
    """
    return (
        f"РОЛЬ: {ctx.role}\n\n"
        f"Вот название документа (имя файла): {origin_rel_path}\n"
        "Это имя относится к текущему документу-источнику и задаёт контекст (о каком конкретно инструменте/системе/теме документ).\n\n"
        "Ты создаёшь карточки знаний по одному документу.\n"
        "ВАЖНО: НЕЛЬЗЯ добавлять/додумывать информацию, которой нет в документе.\n"
        "Разрешено только: извлекать и структурировать. НЕ сжимай смысл: сохраняй все существенные детали.\n"
        "Не переписывай документ целиком, но сохраняй семантические блоки (разделы/подразделы/списки/инструкции) и порядок внутри блока.\n"
        "В заголовках и описании карточек обязательно отражай конкретный объект/инструмент из документа/имени файла (например SmartView), не пиши общие формулировки.\n"
        "Важно: карточек может быть МНОГО, если документ большой и содержит разные смысловые блоки.\n"
        "Ключевое правило: НЕ повторяй одну и ту же информацию в разных карточках. Каждый факт/инструкция/список должен жить в ОДНОЙ, "
        "самой подходящей карточке. Если нужно упомянуть связь — сделай короткую ссылку 'см. карточку <название>' вместо копипаста.\n"
        "Рекомендация по СМЫСЛОВЫМ типам информации (это не шаблон и не обязательные названия секций, а ориентир что покрывать):\n"
        "- инструкции/процедуры/шаги\n"
        "- инструменты/утилиты/сервисы\n"
        "- модели/алгоритмы (если есть)\n"
        "- цели и задачи (если есть)\n"
        "- люди/контакты/ответственные (если есть)\n"
        "- ограничения/условия доступа/сегменты сети/окружение\n"
        "- сущности и ссылки (репозитории/отчеты/страницы)\n\n"
        "Запрещено писать в карточке мета-текст и оценку качества, например: "
        "'требует дополнительного пояснения', 'нужно подробнее описать', 'недостаточно информации'. "
        "Если в документе деталей нет — просто НЕ добавляй их.\n"
        "Важно: карточек может быть несколько или много.\n"
        "Ключевое правило: НЕ делай по одной карточке на каждый пункт списка/каждый инструмент, если их много.\n"
        "Если документ — это обзор/перечень однотипных сущностей (инструменты, библиотеки, участники, ссылки) — сделай 1 карточку-обзор,\n"
        "где внутри будут подпункты по всем элементам (очень кратко), и при необходимости вторую карточку (например, 'Инструкция').\n"
        "Обычно достаточно 1-6 карточек на документ, но делай больше, если информации реально много и она распадается на разные темы.\n"
        "Карточка должна быть самодостаточной.\n\n"
        "Верни результат СТРОГО в JSON формате.\n\n"
        "Правила:\n"
        "- cards: 1..20 элементов.\n"
        "- title: короткий заголовок карточки.\n"
        "- description: 1–2 предложения, ОБЯЗАТЕЛЬНО начинай с фразы 'Документ содержит информацию о ...' и упомяни конкретный объект (например SmartView).\n"
        "- content_md: markdown с фактами/инструкциями/списками. Включай ТОЛЬКО то, что есть в документе.\n"
        "- key_terms: 5–25 терминов.\n"
        "- entities: люди/организации/продукты/библиотеки/сервисы/репозитории.\n\n"
        + (f"Уточнения/что НЕ хватает по мнению судьи:\n{guidance}\n\n" if guidance else "")
        + (f"Текущие карточки (если нужно — дополни, не дублируй):\n{existing_cards_json}\n\n" if existing_cards_json else "")
        + "Документ (если длинный — работай по главному, но сохрани все важные сущности/ссылки/инструкции):\n\n"
        f"{doc_text[:15000]}\n"
    )


def _judge_prompt(*, origin_rel_path: str, doc_text: str, cards_json: str) -> str:
    """
    "Агент-судья": проверяет, покрывают ли карточки весь документ.
    """
    return (
        "Ты судья качества разбиения документа на карточки знаний.\n"
        f"Название документа (имя файла): {origin_rel_path}\n\n"
        "У тебя есть ДВА входа:\n"
        "- ORIGINAL DOCUMENT: исходный текст. Это ЕДИНСТВЕННЫЙ источник истины.\n"
        "- CARDS_JSON: сгенерированные карточки, которые надо проверить.\n\n"
        "Проверь: отражены ли ВСЕ важные знания из ORIGINAL DOCUMENT в CARDS_JSON.\n"
        "Важно: карточки должны быть по смыслу (атомарные знания), не обязаны повторять структуру документа.\n"
        "Также проверь, что карточки НЕ слишком раздроблены: если много однотипных мелких карточек, предложи объединить в 1–2 обзорные.\n\n"
        "КРИТИЧЕСКОЕ ПРАВИЛО ПРО missing:\n"
        "- Ты имеешь право добавить пункт в missing ТОЛЬКО если можешь привести ДОСЛОВНУЮ цитату из ORIGINAL DOCUMENT.\n"
        "- Поле missing[].evidence должно быть точной подстрокой из ORIGINAL DOCUMENT (не пересказом).\n"
        "- Если ты не можешь привести дословную цитату — НЕ добавляй этот пункт в missing.\n"
        "- Запрещено требовать информацию, которой нет в ORIGINAL DOCUMENT.\n\n"
        "Верни результат СТРОГО в JSON формате.\n\n"
        "=== ORIGINAL DOCUMENT (source of truth) ===\n"
        f"{doc_text[:15000]}\n"
        "=== END ORIGINAL DOCUMENT ===\n\n"
        "=== CARDS_JSON (to evaluate) ===\n"
        f"{cards_json}\n"
        "=== END CARDS_JSON ===\n"
    )


def _normalize_ws(s: str) -> str:
    return " ".join((s or "").split())


def _sanitize_judge_meta(*, doc_text: str, judge_meta: dict[str, Any]) -> dict[str, Any]:
    """
    Защита от галлюцинаций судьи:
    - оставляем missing только если evidence действительно встречается в doc_text (после нормализации пробелов)
    - если судья сказал ok=false, но после фильтрации missing пустой — считаем ok=true
    """
    if not isinstance(judge_meta, dict):
        return {"ok": False, "missing": ["judge_meta_not_a_dict"], "suggested_card_titles": []}

    missing_in = judge_meta.get("missing") or []
    if not isinstance(missing_in, list):
        missing_in = []

    doc_norm = _normalize_ws(doc_text)

    kept: list[Any] = []
    removed_count = 0
    for item in missing_in:
        if isinstance(item, dict):
            ev = str(item.get("evidence", "") or "").strip()
            if ev and _normalize_ws(ev) in doc_norm:
                kept.append(item)
            else:
                removed_count += 1
        else:
            # строковые missing (например при parse_error) оставляем как есть
            kept.append(item)

    out = dict(judge_meta)
    out["missing"] = kept
    if removed_count:
        out["missing_sanitized_removed"] = removed_count

    # Если судья ругался только "без цитаты" — после фильтрации считаем, что всё ок.
    ok_val = bool(out.get("ok", False))
    if not ok_val and (not kept) and isinstance(judge_meta.get("missing"), list):
        out["ok"] = True
        out["ok_sanitized_overridden"] = True

    return out


def _generate_cards_once(
    ctx: ToolContext,
    *,
    origin_rel_path: str,
    doc_text: str,
    guidance: str | None = None,
    existing_cards: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    existing_json = json.dumps({"cards": existing_cards or []}, ensure_ascii=False) if existing_cards else None
    writer = _writer_prompt(
        ctx,
        origin_rel_path=origin_rel_path,
        doc_text=doc_text,
        guidance=guidance,
        existing_cards_json=existing_json,
    )
    writer_out = _llm_parse_pydantic(ctx, prompt=writer, model=WriterResult, attempts=3)
    return [c.model_dump() for c in writer_out.cards]


def _judge_once(ctx: ToolContext, *, origin_rel_path: str, doc_text: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Судья вызывается ОДИН раз на документ и получает все карточки документа.
    """
    judge_in = json.dumps({"cards": cards}, ensure_ascii=False)
    try:
        judge_out = _llm_parse_pydantic(
            ctx,
            prompt=_judge_prompt(origin_rel_path=origin_rel_path, doc_text=doc_text, cards_json=judge_in),
            model=JudgeResult,
            attempts=3,
        )
        return judge_out.model_dump()
    except Exception as e:
        # Не валим весь sync из-за судьи: считаем не-ок и пишем причину в missing.
        return {"ok": False, "missing": [f"judge_parse_error: {type(e).__name__}"], "suggested_card_titles": []}


_FALLBACK_MARKER = "Краткое описание не сгенерировано"


def _cards_have_generation_error(cards: list[dict[str, Any]]) -> bool:
    for c in cards:
        if _FALLBACK_MARKER in str(c.get("description", "")) or _FALLBACK_MARKER in str(c.get("content_md", "")):
            return True
        # Запрещённые мета-комментарии (карточка должна содержать факты, а не "нужно подробнее")
        bad_phrases = [
            "требует дополнительного пояснения",
            "требуют дополнительного пояснения",
            "необходимо подробнее описать",
            "нужно подробнее описать",
            "представлены кратко и требуют",
            "требует доработки",
            "нуждается в доработке",
            "недостаточно информации",
            "требует дополнительного уточнения",
        ]
        text = (str(c.get("description", "")) + "\n" + str(c.get("content_md", ""))).lower()
        if any(p in text for p in bad_phrases):
            return True
    return False

def kb_upsert_cards_for_markdown(ctx: ToolContext, origin_rel_path: str, force: bool = False) -> dict[str, Any]:
    if not origin_rel_path:
        raise ValueError("origin_rel_path is required")
    md_path = _resolve_origin(ctx, origin_rel_path)
    md_text = md_path.read_text(encoding="utf-8")
    md_hash = file_sha256(md_path)
    md_stat = md_path.stat()
    md_mtime = datetime.fromtimestamp(md_stat.st_mtime, tz=timezone.utc).isoformat()

    # Очистка старых markdown-карточек по этому документу
    stem = Path(origin_rel_path).stem
    ctx.kb.cards_md_dir.mkdir(parents=True, exist_ok=True)
    for p in ctx.kb.cards_md_dir.glob(f"card_*_{stem}.md"):
        try:
            p.unlink()
        except Exception:
            pass

    title = extract_title(md_text, fallback=Path(origin_rel_path).stem)
    now = utc_now_iso()
    quality: dict[str, Any] | None = None

    # 1) Генерация карточек (писатель)
    raw_cards: list[dict[str, Any]] = []
    try:
        raw_cards = _generate_cards_once(ctx, origin_rel_path=origin_rel_path, doc_text=md_text)
    except Exception:
        raw_cards = []

    # 2) Если в карточках маркер ошибки — один раз повторяем прогон документа
    if not raw_cards or _cards_have_generation_error(raw_cards):
        try:
            # небольшая дополнительная пауза перед повтором
            if ctx.request_delay_s:
                time.sleep(float(ctx.request_delay_s))
            raw_cards = _generate_cards_once(
                ctx,
                origin_rel_path=origin_rel_path,
                doc_text=md_text,
                guidance="Предыдущая попытка содержала ошибку генерации. Верни корректные карточки.",
            )
        except Exception:
            raw_cards = []

    if not raw_cards:
        raw_cards = [
            {
                "title": title,
                "description": "Документ содержит информацию о (ошибка генерации карточек).",
                "content_md": "Краткое описание не сгенерировано (ошибка формата/сети).",
                "key_terms": [],
                "entities": [],
            }
        ]
        quality = {"judge": {"ok": False, "missing": ["Ошибка генерации/парсинга/сети"], "suggested_card_titles": []}}
    else:
        # 3) Судья (ОДНА итерация) — оцениваем исходный набор карточек
        judge_meta = _judge_once(ctx, origin_rel_path=origin_rel_path, doc_text=md_text, cards=raw_cards)
        judge_meta = _sanitize_judge_meta(doc_text=md_text, judge_meta=judge_meta)
        quality = {"judge": judge_meta}

        # 4) Если судья говорит "не ок" — ОБЯЗАТЕЛЬНО один раз добиваем писателем, без повторного вызова судьи
        if not bool(judge_meta.get("ok", False)):
            missing = judge_meta.get("missing") or []
            suggested = judge_meta.get("suggested_card_titles") or []
            guidance = ""
            if missing:
                # missing может быть списком dict (what/evidence)
                parts = []
                for item in missing:
                    if isinstance(item, dict):
                        what = str(item.get("what", "")).strip()
                        ev = str(item.get("evidence", "")).strip()
                        if what and ev:
                            parts.append(f"{what}\n  цитата: {ev}")
                        elif what:
                            parts.append(what)
                    else:
                        parts.append(str(item))
                guidance += "Не покрыто (с цитатами из оригинала):\n- " + "\n- ".join(parts) + "\n"
            if suggested:
                guidance += "Нужно добавить/исправить (заголовки):\n- " + "\n- ".join(str(x) for x in suggested) + "\n"
            guidance += (
                "\nСделай правки, опираясь ТОЛЬКО на оригинальный документ. "
                "Если какого-то 'missing' нет в документе — НЕ добавляй это."
            )
            try:
                refined = _generate_cards_once(
                    ctx,
                    origin_rel_path=origin_rel_path,
                    doc_text=md_text,
                    guidance=guidance,
                    existing_cards=raw_cards,
                )
                if refined:
                    raw_cards = refined
                    quality["refinement_applied"] = True
                else:
                    quality["refinement_applied"] = False
            except Exception as e:
                quality["refinement_applied"] = False
                quality["refinement_error"] = f"{type(e).__name__}"
        else:
            quality["refinement_applied"] = False

    md_dir = ctx.kb.cards_md_dir
    md_dir.mkdir(parents=True, exist_ok=True)
    source_stem = Path(origin_rel_path).stem
    created_files: list[str] = []
    for idx, rc in enumerate(raw_cards):
        t = str(rc.get("title", "")).strip() or f"{title} — часть {idx+1}"
        description = str(rc.get("description", "")).strip()
        if description and not description.lower().startswith("документ содержит информацию о"):
            description = f"Документ содержит информацию о {description.rstrip('.') }."
        content_md = str(rc.get("content_md", "")).strip()
        key_terms = [str(x).strip() for x in (rc.get("key_terms") or []) if str(x).strip()]
        entities = [str(x).strip() for x in (rc.get("entities") or []) if str(x).strip()]
        card_id = sha256(f"{origin_rel_path}:{md_hash}:{idx}:{t}".encode("utf-8")).hexdigest()[:12]
        md_filename = f"card_{card_id}_{source_stem}.md"
        md_path = md_dir / md_filename
        md_body = (
            f"-- {description} --\n\n"
            f"{content_md}\n\n"
            f"<!-- source: {ctx.kb.origins_dir.name}/{origin_rel_path} source_sha256: {md_hash} -->\n"
        )
        md_path.write_text(md_body, encoding="utf-8")
        created_files.append(md_path.as_posix())

    return {
        "ok": True,
        "skipped": False,
        "origin": origin_rel_path,
        "cards_md_count": len(created_files),
        "cards_md_files": created_files,
        "quality": quality,
    }


def kb_sync_all(ctx: ToolContext, force: bool = False) -> dict[str, Any]:
    md_files = _list_markdown_files(ctx)
    results = []
    for md in md_files:
        rel = _origin_rel(ctx, md)
        results.append(kb_upsert_cards_for_markdown(ctx, rel, force=force))
    return {"ok": True, "processed": len(md_files), "results": results}


class ReadDirectoryArgs(BaseModel):
    relative_to_kb_root: bool = Field(default=True, description="Вернуть пути относительно knowledge_base/")


class ReadMarkdownArgs(BaseModel):
    origin_rel_path: str = Field(description="Относительный путь внутри knowledge_base/origins (например: doc.md)")
    max_chars: int = Field(default=12000, ge=1000, le=200000)


class AnalyzeCoverageArgs(BaseModel):
    include_stale: bool = Field(default=True, description="Проверять устаревание по sha256")


class UpsertArgs(BaseModel):
    origin_rel_path: str = Field(description="Относительный путь внутри knowledge_base/origins (например: doc.md)")
    force: bool = Field(default=False, description="Перегенерировать даже если sha256 совпадает")


class SyncAllArgs(BaseModel):
    force: bool = Field(default=False, description="Перегенерировать все карточки даже если sha256 совпадает")


class SetRoleArgs(BaseModel):
    role: str = Field(description="Новая роль/фокус агента (внутренняя инструкция)")


def build_tools(*, ctx: ToolContext):
    """
    Возвращает список LangChain tools.
    """
    return [
        StructuredTool.from_function(
            name="kb_read_directory",
            description="Показать состояние knowledge_base: список markdown в origins и список json в cards.",
            func=lambda relative_to_kb_root=True: kb_read_directory(ctx, relative_to_kb_root=relative_to_kb_root),
            args_schema=ReadDirectoryArgs,
        ),
        StructuredTool.from_function(
            name="kb_read_markdown",
            description="Прочитать markdown из knowledge_base/origins по относительному пути.",
            func=lambda origin_rel_path, max_chars=12000: kb_read_markdown(
                ctx, origin_rel_path=origin_rel_path, max_chars=max_chars
            ),
            args_schema=ReadMarkdownArgs,
        ),
        StructuredTool.from_function(
            name="kb_analyze_coverage",
            description="Проверить покрытие: на каждый markdown в origins должна быть минимум 1 JSON карточка; найти устаревшие по sha256.",
            func=lambda include_stale=True: kb_analyze_coverage(ctx, include_stale=include_stale),
            args_schema=AnalyzeCoverageArgs,
        ),
        StructuredTool.from_function(
            name="kb_upsert_cards_for_markdown",
            description="Создать/обновить JSON карточку для одного markdown файла.",
            func=lambda origin_rel_path, force=False: kb_upsert_cards_for_markdown(
                ctx, origin_rel_path=origin_rel_path, force=force
            ),
            args_schema=UpsertArgs,
        ),
        StructuredTool.from_function(
            name="kb_sync_all",
            description="Синхронизировать все markdown из origins в JSON карточки в cards.",
            func=lambda force=False: kb_sync_all(ctx, force=force),
            args_schema=SyncAllArgs,
        ),
        StructuredTool.from_function(
            name="kb_set_role",
            description="Поменять роль/фокус агента (внутреннюю инструкцию, влияющую на саммари/термины).",
            func=lambda role: kb_set_role(ctx, role=role),
            args_schema=SetRoleArgs,
        ),
    ]


