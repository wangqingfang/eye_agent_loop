# Domain Docs

How the engineering skills should consume this project's domain documentation. Layout: **single-context**, rooted at `eye_doc/AgentLoop/` (the surrounding repo holds unrelated projects).

## Before exploring, read these

- **`eye_doc/AgentLoop/GLOSSARY.md`**
- **`eye_doc/AgentLoop/docs/adr/`**: read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill creates them lazily when terms or decisions actually get resolved.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0003 (fixed exploration/validation split), but worth reopening because…_
