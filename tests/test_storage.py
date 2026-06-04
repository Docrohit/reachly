from concurrent.futures import ThreadPoolExecutor

from reachly.storage import History


def test_history_can_be_used_from_scheduler_threads(tmp_path):
    history = History(tmp_path)
    history.record(
        theme="AI",
        hook="Why catalog teams need media agents",
        body="Body",
        platform="linkedin",
        ok=True,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        hooks = executor.submit(history.recent_hooks).result()
        executor.submit(
            history.record_event,
            platform="instagram",
            ok=False,
            error="scheduled failure",
        ).result()

    assert hooks == ["Why catalog teams need media agents"]
    history.close()
