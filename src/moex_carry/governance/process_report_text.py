from __future__ import annotations

from typing import Any


RECOMMENDATION_TRANSLATIONS = {
    "No files provided. Use --from-git, --stdin, or --changed-files.":
        "Файлы не переданы. Укажите diff через `--from-git`, `--stdin` или `--changed-files`.",
    "No diff yet. Using request/session intent fallback.":
        "Дифф ещё не появился. Используется fallback по запросу и session handoff.",
    "Patch touches multiple contexts. Split by ownership to keep review and agent context small.":
        "Патч затрагивает несколько контекстов. Разделите изменения по зонам владения, чтобы ревью и агентный контекст оставались узкими.",
    "Intent spans multiple contexts. Set an explicit target module before implementation.":
        "Намерение задачи затрагивает несколько контекстов. До реализации явно выберите целевой модуль.",
    "CTX-CONTRACTS is combined with other contexts. Use ordered patch series: contracts -> code -> docs.":
        "CTX-CONTRACTS смешан с другими контекстами. Ведите серию патчей в порядке: контракты -> код -> документация.",
    "Some files are unmapped. Classify manually before implementation.":
        "Есть неразмеченные файлы. Перед реализацией вручную определите их контекст.",
    "Patch is scoped to one context.": "Патч ограничен одним контекстом.",
}

METRIC_LABELS = {
    "correct_first_time_pct": "Решения с первого раза",
    "start_match_pct": "Совпадение стартового контекста",
    "context_expansion_rate": "Расширение контекста",
    "repeat_error_rate": "Повторы ошибок",
    "environment_blocker_rate": "Блокеры среды",
}


def translate_recommendation(value: str) -> str:
    if value in RECOMMENDATION_TRANSLATIONS:
        return RECOMMENDATION_TRANSLATIONS[value]
    suffix = " imports span multiple neighboring contexts. Treat as cross-cutting and keep adapters thin."
    if value.endswith(suffix):
        prefix = value[: -len(suffix)]
        return (
            f"{prefix} затрагивает несколько соседних контекстов. "
            "Считайте это сквозной зоной и держите адаптеры тонкими."
        )
    return value


def normalize_environment_blocker_signature(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized == "none":
        return "environment/no-signature"
    return normalized


def translate_named_value(value: str) -> str:
    if value == "environment/no-signature":
        return "блокер среды без сигнатуры"
    if value == "none":
        return "без сигнатуры"
    return translate_recommendation(value)


def format_pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def format_seconds(value: int | float | None) -> str:
    if value is None:
        return "—"
    total_seconds = int(max(value, 0))
    if total_seconds < 60:
        return f"{total_seconds} с"
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}м {seconds:02d}с"


def top_named(items: list[tuple[str, int]]) -> str | None:
    if not items:
        return None
    name, count = items[0]
    if not name:
        return None
    return f"{translate_named_value(name)} ({count})"


def build_human_summary(rollup: dict[str, Any], *, status: str) -> dict[str, Any]:
    metrics = rollup["current_metrics"]
    current_window_count = int(rollup["current_window_count"])
    if current_window_count == 0:
        return {
            "status": status,
            "headline": "Завершённых задач пока нет.",
            "what_happened": "В task outcome ledger ещё нет ни одной задачи с терминальным итогом.",
            "why_it_drifted": "Пока не закрыта хотя бы одна задача, weekly-сигнал по процессу не формируется.",
            "what_to_change_next": [
                "Закройте следующую нетривиальную задачу с заполненным Task Outcome и синхронизированным ledger."
            ],
            "current_risks": ["Историческая база ещё не накоплена."],
        }

    if status == "burn-in":
        headline = (
            f"Телеметрия процесса ещё на прогреве: {rollup['completed_tasks_count']}/"
            f"{rollup['window_size']} завершённых задач."
        )
    elif status == "healthy":
        headline = "Состояние процесса стабильно в текущем rolling-окне."
    elif status == "watch":
        headline = "Процесс проседает по одному измерению governance."
    else:
        headline = "Процесс требует вмешательства сразу по нескольким измерениям governance."

    what_happened = (
        f"В текущем окне {current_window_count} задач: "
        f"{format_pct(float(metrics['correct_first_time_pct']))} завершены с первого раза, "
        f"{format_pct(float(metrics['start_match_pct']))} стартовали в верном контексте, "
        f"медианное время до первого патча — {format_seconds(int(metrics['median_time_to_first_patch_sec']))}."
    )

    drift_fragments: list[str] = []
    if float(metrics["context_expansion_rate"]) > 0:
        drift_fragments.append(
            f"расширение контекста составило {format_pct(float(metrics['context_expansion_rate']))}"
        )
    if float(metrics["repeat_error_rate"]) > 0:
        repeated = top_named(list(rollup["top_repeated_error_signatures"]))
        if repeated:
            drift_fragments.append(f"повторы ошибок ведёт сигнатура {repeated}")
        else:
            drift_fragments.append(
                f"доля повторных ошибок выросла до {format_pct(float(metrics['repeat_error_rate']))}"
            )
    if float(metrics["environment_blocker_rate"]) > 0:
        blocker = top_named(list(rollup["top_environment_blockers"]))
        if blocker:
            drift_fragments.append(f"блокеры среды чаще всего связаны с {blocker}")
        else:
            drift_fragments.append("в текущем окне присутствуют блокеры среды")
    if rollup["tasks_with_wrong_path_or_partial"]:
        drift_fragments.append(
            f"{len(rollup['tasks_with_wrong_path_or_partial'])} задач завершились неверным путём или частичным итогом"
        )
    if not drift_fragments:
        drift_fragments.append("в текущем окне нет заметного кластера повторных или частичных сбоев")

    next_actions: list[str] = []
    if float(metrics["correct_first_time_pct"]) < 0.70:
        next_actions.append(
            "Жёстче сужайте маршрут до реализации и останавливайтесь после первого сигнала wrong-path."
        )
    if float(metrics["start_match_pct"]) < 0.75 or float(metrics["context_expansion_rate"]) > 0.25:
        next_actions.append(
            "Раньше фиксируйте целевой модуль и разделяйте межконтекстные патчи по зонам владения."
        )
    if float(metrics["repeat_error_rate"]) > 0.15:
        next_actions.append(
            "Каждую повторную сигнатуру превращайте в новый validator, workflow или docs-артефакт до следующей похожей задачи."
        )
    if float(metrics["environment_blocker_rate"]) > 0.20:
        next_actions.append(
            "Отправляйте блокеры среды в runbook или env-fix, а не повторяйте тот же путь задачи."
        )
    top_risky_recommendation = top_named(list(rollup["high_risk_start_recommendations"]))
    if top_risky_recommendation:
        next_actions.append(
            f"Проверьте, не игнорируется ли стартовая рекомендация '{top_risky_recommendation}' перед началом rework."
        )
    if not next_actions:
        next_actions.append(
            "Сохраняйте текущую дисциплину маршрутизации и closeout: дополнительных процессных вмешательств пока не требуется."
        )

    current_risks: list[str] = []
    if status in {"watch", "critical"}:
        current_risks.extend(
            [
                METRIC_LABELS.get(item["metric"], item["metric"])
                for payload in rollup["threshold_results"].values()
                for item in payload["checks"]
                if not item["passed"]
            ]
        )
    top_recommendation = top_named(list(rollup["top_start_recommendations"]))
    if top_recommendation:
        current_risks.append(f"Самая частая стартовая рекомендация: {top_recommendation}")
    if not current_risks:
        current_risks.append("В rolling-окне сейчас нет активного порогового нарушения.")

    return {
        "status": status,
        "headline": headline,
        "what_happened": what_happened,
        "why_it_drifted": "; ".join(drift_fragments) + ".",
        "what_to_change_next": next_actions,
        "current_risks": current_risks,
    }
