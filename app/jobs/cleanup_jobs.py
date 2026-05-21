from typing import Any

from app.config import Settings
from app.services.cleanup import cleanup_old_data


class CleanupJobService:
    def __init__(self, *, session_factory: Any, settings: Settings) -> None:
        self.session_factory = session_factory
        self.settings = settings

    def run_cleanup(self) -> dict[str, int]:
        with self.session_factory() as session:
            result = cleanup_old_data(
                session,
                price_history_days=self.settings.price_history_days,
                raw_result_retention_days=self.settings.raw_result_retention_days,
            )
            session.commit()
            return result
