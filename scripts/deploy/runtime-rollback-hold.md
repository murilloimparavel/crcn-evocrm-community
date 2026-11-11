# Rollback with durable events

The previous runtime cannot read string IDs. On rollback keep CRM ingress and
Sidekiq drained; stop all runtime workers and verify all execution leases expired.
Do not resume ingress after switching to the old image: it cannot safely process
new messages either. Escalate the service interruption and recover forward.

Record a private, restorable backup. Take the complete ordered ZRANGE snapshot of
`bot_runtime:durable:ready`; do not output turn payloads or credentials. Use the
reviewed `hold-runtime-queue.lua` with the ready key, a unique
`bot_runtime:rollback:held:<incident>` key, and every snapshot member in order.
The script fails closed if any turn, lease, or queue differs. It renames only the
sorted-set index, preserving the exact payload keys and receipts with no replay.
Check that the held index contains every snapshot member, ready is absent, and
all original turn/receipt keys remain. Verify the previous image and datastore
identities after the application-only rollback. Keep the hold and backup until
individual reconciliation or a tested forward recovery. Never blindly rename
it back: it may contain obsolete, legacy, or already-answered messages.

This hold is not a distributed pause: the operator must establish and verify that
all writers and workers remain stopped before and throughout the procedure. The
previous image cannot provide working bot service, so rollback prioritizes data
preservation over availability and requires an explicit forward recovery.
