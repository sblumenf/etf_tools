# Project Rules

## Parser Work Requires Documentation Review
Any work on parsers — creation, modification, debugging, or extension — **MUST** begin by reading `docs/reference/README.md` and then consulting the specific files listed in `docs/reference/PARSER_REFERENCE_MAP.md` for the parser being worked on. Do not rely on memory or assumptions about filing formats. The reference documents contain the authoritative field definitions, XML schemas, and sample filings.

## Use Agents for All Operations
All operations **MUST** be delegated to subagents (via the Task tool) to preserve main conversation context. This includes research, implementation, testing, and review. Do not perform multi-step work inline.
