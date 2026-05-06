"""Jobs domain — async pipeline orchestration + cost tracking.

Files in this package
---------------------

``runner``
    The runtime. Holds the in-process ``JobRunner`` singleton, the ``Job``
    dataclass, the ``JobProgressSink`` adapter, and cancellation helpers.
    Conceptually this is the "service" layer for the jobs domain — kept
    as ``runner.py`` rather than the canonical ``services.py`` because
    that name describes the actual responsibility (running jobs).

``pipeline_adapters``
    Worker callables bound to the runner that drive ``boardfactory``
    pipeline ops (analyze, style, generate, export, …). Specialized
    services that bridge ``runner`` and ``boardfactory``.

``repository``
    Pure DB I/O for the ``job_runs`` table: persist terminal snapshots
    and hydrate them back on boot.

``cost_ledger``
    ``cost_entries`` table writer + lifetime/session aggregation
    queries. Called by workers when they invoke a paid provider.

``routes_api``
    HTTP for ``/jobs``, ``/events/jobs`` (SSE), ``/api/cost-summary``.

Other domains import explicitly:

    from jobs.runner import Job, get_runner, JobProgressSink
    from jobs import cost_ledger, pipeline_adapters
"""
