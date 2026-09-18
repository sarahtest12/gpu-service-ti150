# Domain Docs

## Before exploring

Read these files when they exist:

- `CONTEXT.md` at the repository root
- Relevant ADRs under `docs/adr/`

If they do not exist, proceed silently. The domain-modeling skill creates them when terminology or architectural decisions need to be recorded.

## Layout

This repository uses a single-context layout:

```
/
├── CONTEXT.md
├── docs/
│   └── adr/
└── service directories
```

## Vocabulary

Use terminology defined in `CONTEXT.md`. Avoid introducing synonyms for concepts already defined there.

If required terminology is missing, record the gap for domain modeling.

## ADR conflicts

Explicitly identify proposals that conflict with an existing ADR instead of silently overriding the decision.
