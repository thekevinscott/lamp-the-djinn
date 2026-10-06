# Session Handoff Doc

Maintain one ongoing handoff doc per session and point the user to it at every **stopping point**: after each major unit of work lands (a push, a green CI run, a finished investigation, a merged PR) or when blocked on user input. A stopping point marks a checkpoint, not the end -- point to the doc, then keep working.

- Keep it in the session scratchpad / `/tmp` (e.g. `<scratchpad>/handoff.md`). It is conversation-scoped: NEVER commit it, stage it, or place it anywhere in the repo tree.
- Update the same doc in place at each checkpoint, then print its path (in hosted sessions, attach it via the file-delivery tool instead), so the freshest pointer sits near the bottom of the conversation. Print only the path: never the doc's contents or a summary of it. The user asks for a summary when they want one.
- Write it standalone, so a brand-new session with zero context can resume from it alone: task + status (done / in progress / next), branches/PRs/issues with numbers and CI state, key decisions and discovered constraints (one-line reasons), exact next commands to run, anything waiting on the user.

Purpose: the prompt cache survives at most an hour of inactivity, so resuming a long conversation after hours away reprocesses the entire history at full cost. A current handoff path near the end of the transcript lets the user grab it and start a cheap fresh session from the doc instead of resuming the stale one.
