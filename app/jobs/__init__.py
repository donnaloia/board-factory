"""Jobs domain — async pipeline orchestration + cost tracking.

Files in this package
---------------------

``runner``
    The runtime. Holds the in-process ``JobRunner`` singleton, the ``Job``
    dataclass, the ``JobProgressSink`` adapter, and cancellation helpers.

``repository``
    Pure DB I/O for the ``job_runs`` table: persist terminal snapshots
    and hydrate them back on boot.

``cost_ledger``
    ``cost_entries`` table writer + lifetime/session aggregation
    queries. Called by workers when they invoke a paid provider.

``routes_api``
    HTTP for ``/jobs``, ``/events/jobs`` (SSE), ``/api/cost-summary``.

Pipeline **workers** (``fn(job, cancel) -> cost``) live in each feature
domain as ``domains/<name>/pipeline_jobs.py`` — e.g.
``domains.boards.pipeline_jobs``, ``domains.cards.pipeline_jobs``.
Those modules import ``jobs.runner`` and call into ``pipeline/*``.

Other domains import explicitly::

    from jobs.runner import Job, get_runner, JobProgressSink
    from jobs import cost_ledger
    from domains.boards import pipeline_jobs
"""
