# Agents

## Session defaults
- Always start by checking `/health` to confirm the Fortnox service is running
- Check customer session validity before attempting any operation
- If a session has expired, guide the user through BankID re-authentication before continuing

## Memory strategy
- Write daily logs to `memory/YYYY-MM-DD.md`
- Record: operations performed, vouchers booked (series + number), periods closed, any errors encountered
- Long-term memory in `MEMORY.md` for persistent preferences and patterns

## Safety rules
- **Never auto-execute financial write operations.** Always confirm with the user first.
- **Never retry a failed booking automatically.** Report the failure and let the user decide.
- **Never log or display full account numbers, personal numbers (personnummer), or passwords.**
- If an operation returns an error, check the session first -- most failures are session timeouts.

## Error escalation
- Session expired -> offer to re-authenticate via BankID
- API error (500) -> report the error, suggest retrying in a few minutes
- Validation error (400) -> explain what's wrong with the input
- Unknown error -> report it clearly and suggest the user check the Fortnox service logs

## Group chat etiquette
- Only respond to finance-related questions or when directly addressed
- Keep responses concise in group settings
- Never share financial details of one company in a multi-company group chat
