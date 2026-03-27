# Heartbeat

Periodic checks to run during active hours.

## Session health
- Check `/health` on the Fortnox service
- If degraded, notify the user that Chrome CDP may be down

## Period closing reminders
- After the 5th of each month, check if the previous month's period has been closed
- If not, send a gentle reminder: "Perioden for {month} is still open. Want me to close it?"

## Reconciliation nudge
- If it's been more than 2 weeks since the last reconciliation, suggest running one
- "Det har gatt ett tag sedan senaste avstamningen. Vill du att jag kor en?"
