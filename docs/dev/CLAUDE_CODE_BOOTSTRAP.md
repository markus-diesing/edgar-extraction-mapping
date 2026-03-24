# CLAUDE_CODE_BOOTSTRAP.md
# First Prompt for Claude Code Session

> **Instructions for Markus:** Copy the text below the divider and paste it as your first message when you open Claude Code in the `EDGAR-Extraction_Mapping/` folder. Do not send anything else first.

---

## PASTE THIS AS YOUR FIRST MESSAGE IN CLAUDE CODE:

---

You are building a local, standalone EDGAR extraction and mapping tool for LPA. The project root is `EDGAR-Extraction_Mapping/`. All code you write must live within this folder.

**Start by reading these four files in order — do not write any code until you have read all of them:**

1. `README.md` — project overview and your operating rules
2. `REQUIREMENTS.md` — full functional requirements (v0.2)
3. `EDGAR_API.md` — EDGAR API reference, endpoints, rate limits, filing structure
4. `DATA_MODEL.md` — SQLite schema, PRISM field format, export spec, path conventions

After reading, confirm your understanding by summarising:
- The six pipeline phases and what each does
- The tech stack you will use
- The three most important constraints from REQUIREMENTS.md section 2 (Portability)

Then ask me if I am ready to begin Phase 1 before writing any code.

---

*End of bootstrap prompt*
