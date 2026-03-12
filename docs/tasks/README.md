# Task Notes

This directory stores per-task continuity notes.

## Layout
- `docs/tasks/active/` active task notes.
- `docs/tasks/archive/` closed task notes.
- `docs/tasks/templates/` note templates.
- `docs/tasks/active/index.yaml` active note index.
- `docs/tasks/archive/index.yaml` archive index.

## Policy
- `docs/session_handoff.md` is a pointer shim to the active task note.
- Non-trivial changes require a task note (`full` or `lite` template).
- Trivial changes may skip task-note creation.
- Closeout writes durable outcomes to `memory/task_outcomes.yaml`.
