"""Hardware validation test runner API."""

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..services import hw_validator

router = APIRouter(prefix="/api/v1/hw-tests", tags=["hw-tests"])


class RunRequest(BaseModel):
    tiers: List[int] = [1, 2, 3]
    client_ip: Optional[str] = None


class TestResultResponse(BaseModel):
    name: str
    tier: int
    category: str
    status: str
    message: str
    duration_ms: float


class ValidationReportResponse(BaseModel):
    results: List[TestResultResponse]
    passed: int
    failed: int
    skipped: int
    duration_ms: float


@router.post("/run", response_model=ValidationReportResponse)
async def run_tests(req: RunRequest):
    """Run hardware validation tests. Returns structured results."""
    report = await hw_validator.run_validation(
        tiers=req.tiers,
        client_ip=req.client_ip,
    )
    return ValidationReportResponse(
        results=[
            TestResultResponse(
                name=r.name, tier=r.tier, category=r.category,
                status=r.status, message=r.message, duration_ms=r.duration_ms,
            )
            for r in report.results
        ],
        passed=report.passed,
        failed=report.failed,
        skipped=report.skipped,
        duration_ms=report.duration_ms,
    )
