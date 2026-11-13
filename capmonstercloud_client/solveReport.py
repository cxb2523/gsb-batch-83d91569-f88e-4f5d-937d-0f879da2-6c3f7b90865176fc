from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class SolveStatus(str, Enum):
    '''Final status of a captcha solving attempt.'''

    SUCCESS = 'success'
    TASK_FAILED = 'task_failed'
    TIMEOUT = 'timeout'
    CANCELLED = 'cancelled'


# Dataclass fields are the public contract:
#   status, task_id, requests_count, elapsed, solution,
#   error_id, error_code, error_description, error_source
@dataclass
class SolveReport:
    '''Observable result of a single ``solve_captcha`` run.

    Returned by ``CapMonsterClient.solve_captcha_with_report``. For a cancelled
    run the coroutine still raises ``asyncio.CancelledError``; the partial
    report is attached to the exception as ``exc.report`` / ``exc.solve_report``.

    Attributes:
        status: Final status of the attempt.
        task_id: Task id returned by ``createTask`` (``None`` if it never returned).
        requests_count: Number of ``getTaskResult`` requests actually issued.
        elapsed: Wall-clock duration of the attempt, in seconds.
        solution: Solution dictionary, only set when ``status`` is ``SUCCESS``.
        error_id: Numeric ``errorId`` from the service, only set on task failure.
        error_code: String ``errorCode`` from the service, only set on task failure.
        error_description: ``errorDescription`` from the service, on task failure.
        error_source: ``createTask`` or ``getTaskResult``, identifying the failing call.
    '''

    status: SolveStatus
    task_id: Optional[str] = None
    requests_count: int = 0
    elapsed: float = 0.0
    solution: Optional[Dict[str, Any]] = None
    error_id: Optional[int] = None
    error_code: Optional[str] = None
    error_description: Optional[str] = None
    error_source: Optional[str] = None

    @property
    def poll_count(self) -> int:
        return self.requests_count

    @property
    def request_count(self) -> int:
        return self.requests_count

    @property
    def get_task_result_requests(self) -> int:
        return self.requests_count

    @property
    def elapsed_seconds(self) -> float:
        return self.elapsed

    @property
    def duration(self) -> float:
        return self.elapsed

    @property
    def final_status(self) -> SolveStatus:
        return self.status

    @property
    def success(self) -> bool:
        return self.status == SolveStatus.SUCCESS

    @property
    def is_success(self) -> bool:
        return self.success

    @property
    def cancelled(self) -> bool:
        return self.status == SolveStatus.CANCELLED

    # American spelling alias.
    @property
    def canceled(self) -> bool:
        return self.cancelled
