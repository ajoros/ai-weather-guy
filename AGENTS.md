# Agent notes

- Git commits and `git push` must not include a Cursor, Copilot, Claude, or other LLM signature, trailer, or `Co-authored-by`.
- See `.cursor/rules/no-cursor-git-signature.mdc`.
- Enforcement is `.githooks/commit-msg` (copied to `.git/hooks/commit-msg`). Do not skip hooks.
