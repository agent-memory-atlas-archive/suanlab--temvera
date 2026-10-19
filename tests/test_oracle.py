

def test_memoised_state_is_invalidated_by_append_and_safe_to_mutate():
    from datetime import datetime, timezone

    from temvera.model import MemoryEvent, Operation
    from temvera.oracle import LifecycleOracle

    def ingest(belief, value, day):
        moment = datetime(2025, 1, day, tzinfo=timezone.utc)
        return MemoryEvent(event_id=f"i-{belief}", operation=Operation.INGEST,
                           belief_id=belief, subject="s", attribute="a", value=value,
                           valid_from=moment, recorded_at=moment)

    oracle = LifecycleOracle([ingest("b1", "x", 1)])
    at = datetime(2025, 1, 10, tzinfo=timezone.utc)
    first = oracle.state_as_of(at)
    first.clear()
    assert set(oracle.state_as_of(at)) == {"b1"}
    oracle.append(ingest("b2", "y", 2))
    assert set(oracle.state_as_of(at)) == {"b1", "b2"}
