---
id: DP.ROLE.NNN
name: Маршрутизатор внешнего трекера
type: role
status: draft
layer: L4-Platform
owner_role: R6 Кодировщик
created: 2026-08-13
updated: 2026-08-13
wp: WP-34
related:
  realizes: DP.SC.NNN
---

# [DP.ROLE.NNN] Маршрутизатор внешнего трекера

## Kind и владелец

- **Kind:** детерминированная bridge-role.
- **Owner Role:** R6 Кодировщик; решение об owner-repository принимает пилот
  или открывающий РП агент до вызова роли.

## Обязанности

1. Принять WP-ID, название, context file и один owner-repository.
2. Проверить точный WP-ID среди GitHub issues owner-repository.
3. Вернуть существующую issue либо создать одну новую.
4. Записать URL в frontmatter context file.
5. В режиме проверки обнаружить missing, duplicate, stale и wrong-repo.
6. Вернуть наблюдаемый результат вызывающему циклу IWE.
7. Принять существующую GitHub issue как минимальный WP без вызова create.
8. Сверить adoption allowlist и cutover до пакетного принятия issues.
9. При `CLOSED` у связанной GitHub issue атомарно закрыть и архивировать WP, оставив неблокирующий маркер отложенного обогащения.

## Полномочия

- читать локальный WP context и WP Registry;
- выполнять `gh issue list`, `gh issue view` и `gh issue create`;
- создавать минимальный WP context, строку Registry и пересобирать active-wp
  одной локальной транзакцией; WeekPlan при adoption не менять;
- не обращаться к Linear API и не читать секреты GitHub.

## Входы и выходы

| Артефакт | Направление | Формат |
|----------|-------------|--------|
| WP context | вход | Markdown + YAML frontmatter |
| owner-repository | вход | одно значение из разрешённого списка |
| GitHub issue | выход | `WP-N Название`, URL |
| linkage report | выход | машинно-читаемый статус + пояснение |

## Инварианты

- один WP-ID не создаёт больше одной issue;
- локальная регистрация предшествует внешней;
- неизвестный owner-repository блокирует внешнее действие;
- внешний отказ не удаляет и не откатывает локальные файлы;
- статус Linear не считается источником истины для WP;
- текст issue для публичного FMT не содержит приватный DS-контекст.
- одна входящая GitHub issue связана максимум с одним WP;
- adoption не вызывает создание GitHub issue;

## Связи

- реализует «Синхронизация РП с внешним трекером»;
- вызывается `/wp-new`, Day Close и Week Close;
- Day Open использует её отчёт как сигнал внимания;
- штатная GitHub ↔ Linear интеграция находится за границей роли.
