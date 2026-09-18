"""Optional standalone Celery entrypoint with database recovery polling.

Run: celery -A apps.worker.celery_app worker -l info -Q verification,report
The original workers.celery_app entrypoint remains compatible when an API poller runs.
"""
from workers.celery_app import celery_app

if celery_app is not None:
    from celery.signals import worker_ready, worker_shutdown

    @worker_ready.connect(weak=False)
    def start_recovery(**kwargs):
        from apps.api.services import get_runner
        get_runner().start()

    @worker_shutdown.connect(weak=False)
    def stop_recovery(**kwargs):
        from apps.api.services import get_runner
        get_runner().stop()
