---
name: rp
description: 구현 보고서와 GitHub PR 본문을 함께 생성해 달라는 요청이나 RP 작업 요청에 사용한다. 둘 중 하나만 요청하면 report 또는 pr-description을 사용한다.
version: 1.0.0
---

Read `../../../.claude/commands/rp.md` completely, then execute that workflow.

Treat the user's full request as `$ARGUMENTS`. Map referenced Claude commands to the sibling Codex skills with the same names, and translate Claude-specific agent or tool syntax to Codex equivalents. Current system and `AGENTS.md` instructions take precedence.
