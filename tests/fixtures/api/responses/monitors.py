# Monitor response fixtures

MONITOR_CREATE_RESPONSE = {
    "id": "monitor_abc1234567",
    "object": "monitor",
    "query": "Watch the Stripe status page for incidents",
    "status": "provisioning",
    "tracked": None,
    "source_policy": {
        "include_urls": ["https://status.stripe.com"],
        "exclude_urls": None,
        "include_domains": None,
        "exclude_domains": None,
    },
    "schedule": {
        "frequency": "every hour",
        "cron": "0 * * * ? *",
        "timezone": "UTC",
        "next_run_at": None,
    },
    "notification": {
        "events": ["changed", "first_snapshot"],
        "channels": [{"type": "email", "target": "you@example.com", "events": None}],
    },
    "webhook": None,
    "output_schema": None,
    "metadata": {},
    "agent": {"id": "agent_forward_deployed_0_fda_xyz"},
    "last_run": None,
    "total_count": None,
    "mermaid_diagram": None,
    "error_message": None,
    "created": 1760327323,
    "updated": 1760327323,
}

MONITOR_GET_RESPONSE = {
    **MONITOR_CREATE_RESPONSE,
    "status": "active",
    "schedule": {
        **MONITOR_CREATE_RESPONSE["schedule"],
        "next_run_at": "2026-06-19T13:00:00Z",
    },
    "last_run": {
        "id": "run_xyz789",
        "status": "completed",
        "change_detected": False,
        "ran_at": "2026-06-19T12:00:00Z",
    },
    "total_count": 5,
}

MONITOR_LIST_RESPONSE = {
    "monitors": [MONITOR_CREATE_RESPONSE],
    "count": 1,
}

MONITOR_EVENTS_RESPONSE = {
    "data": [
        {
            "id": "run_xyz789",
            "run_id": "run_xyz789",
            "created": 1760327323,
            "changed": False,
            "summary": "No changes detected.",
            "snapshot_url": "https://olostep-monitor-snapshots.s3.amazonaws.com/snap_abc?X-Amz-Signature=...",
        }
    ],
    "has_more": False,
    "next_cursor": None,
    "total_count": 5,
}
