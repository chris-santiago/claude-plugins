# Rigor level: intent ledger

Frozen 2026-11-05 from the brainstorming dialogue; changes only by the user's explicit decision.

1. A small project (under ~5k source lines) gets light testing, planning and mutation with no setup ("for super small applications at work the heavy tests seem overkill").
2. Ferrum stays at heavy testing ("Ferrum is large and uses python+rust. I expect heavy testing there").
3. Mutation time is proportionate to the project: few breaks on a small codebase, and a survivor outside the plan's rows doesn't force a fix round ("i hate spending disproportional time on mutations for a small or simple code base").
4. Below `heavy`, reviewers don't start fix rounds over esoteric edge cases. Tests cover the realistic cases first ("not spending as much time on esoteric edge cases, but still maintaining robustness").
5. A test that can't fail is a serious finding at every level, so robustness doesn't drop with the level.
6. Every brief and mutation run states the level and the reasons for it, and one `CLAUDE.md` line overrides it.
7. A plan can raise a single risky task above the project level, never lower it.
