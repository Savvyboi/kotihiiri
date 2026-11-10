# Agents

Read [PLAN.md](PLAN.md) before changing anything. It is the build spec; work milestone by
milestone (§15). The hard constraints in §2 are non-negotiable: robots.txt is law (the only
exceptions are `robots_exceptions` and the off-by-default `robots_override` in
`config/project.yaml`, each approved by a human; never add to them on your own), Oulu and
Turku stay disabled, never commit raw HTML/PDFs, strip personal data, keep output deterministic.
If a task seems to require breaking one, stop and ask a human.
