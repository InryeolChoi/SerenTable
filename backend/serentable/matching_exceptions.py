"""Shared read-only definition of unresolved runner failures; never exposes DB errors."""

MATCHING_FAILURE_SELECT = """SELECT DISTINCT ON (f.event_slot_id)
    f.id,f.event_slot_id,f.attempt,f.reason_code,f.finished_at
    FROM match_run f WHERE f.state='FAILED'
    AND NOT EXISTS (SELECT 1 FROM match_run s
        WHERE s.event_slot_id=f.event_slot_id AND s.state='SUCCEEDED')
    ORDER BY f.event_slot_id,f.attempt DESC"""
