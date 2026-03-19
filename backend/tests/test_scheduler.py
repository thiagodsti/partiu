"""Tests for backend.scheduler."""

from unittest.mock import MagicMock, patch


class TestStartScheduler:
    def setup_method(self):
        import backend.scheduler as sched_mod

        sched_mod._scheduler = None

    def teardown_method(self):
        import backend.scheduler as sched_mod

        sched_mod._scheduler = None

    def test_disabled_when_setting_is_true(self, test_db, monkeypatch):
        import backend.config as cfg
        import backend.scheduler as sched_mod

        monkeypatch.setattr(cfg.settings, "DISABLE_SCHEDULER", True)
        from backend.scheduler import start_scheduler

        start_scheduler()
        assert sched_mod._scheduler is None

    def test_starts_with_two_jobs(self, test_db, monkeypatch):
        import backend.config as cfg
        import backend.scheduler as sched_mod

        monkeypatch.setattr(cfg.settings, "DISABLE_SCHEDULER", False)
        mock_sched = MagicMock()
        mock_sched.running = False
        with patch("backend.scheduler.BackgroundScheduler", return_value=mock_sched):
            with patch("backend.database.get_global_setting", return_value="10"):
                from backend.scheduler import start_scheduler

                start_scheduler()
        mock_sched.start.assert_called_once()
        assert mock_sched.add_job.call_count == 2

    def test_uses_sync_interval_from_settings(self, test_db, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "DISABLE_SCHEDULER", False)
        mock_sched = MagicMock()
        job_kwargs = []

        def capture_add_job(func, trigger=None, **kwargs):
            job_kwargs.append(kwargs)

        mock_sched.add_job = capture_add_job
        mock_sched.running = False
        with patch("backend.scheduler.BackgroundScheduler", return_value=mock_sched):
            with patch("backend.database.get_global_setting", return_value="15"):
                from backend.scheduler import start_scheduler

                start_scheduler()
        ids = [kw.get("id") for kw in job_kwargs]
        assert "email_sync" in ids
        assert "aircraft_sync" in ids


class TestStopScheduler:
    def test_stops_running_scheduler(self):
        import backend.scheduler as sched_mod

        mock_sched = MagicMock()
        mock_sched.running = True
        sched_mod._scheduler = mock_sched
        from backend.scheduler import stop_scheduler

        stop_scheduler()
        mock_sched.shutdown.assert_called_once_with(wait=False)
        sched_mod._scheduler = None

    def test_noop_when_no_scheduler(self):
        import backend.scheduler as sched_mod

        sched_mod._scheduler = None
        from backend.scheduler import stop_scheduler

        stop_scheduler()  # should not raise

    def test_noop_when_not_running(self):
        import backend.scheduler as sched_mod

        mock_sched = MagicMock()
        mock_sched.running = False
        sched_mod._scheduler = mock_sched
        from backend.scheduler import stop_scheduler

        stop_scheduler()
        mock_sched.shutdown.assert_not_called()
        sched_mod._scheduler = None


class TestGetScheduler:
    def test_returns_none_when_not_started(self):
        import backend.scheduler as sched_mod

        sched_mod._scheduler = None
        from backend.scheduler import get_scheduler

        assert get_scheduler() is None

    def test_returns_scheduler_when_set(self):
        import backend.scheduler as sched_mod

        mock_sched = MagicMock()
        sched_mod._scheduler = mock_sched
        from backend.scheduler import get_scheduler

        assert get_scheduler() is mock_sched
        sched_mod._scheduler = None
