"""Pydantic models for network impairment parameters."""

from typing import Dict, Optional

from pydantic import BaseModel, Field


class DelayConfig(BaseModel):
    ms: float = Field(0, ge=0, le=60000, description="Delay in milliseconds")
    jitter_ms: float = Field(0, ge=0, le=60000, description="Jitter in milliseconds")
    correlation_pct: float = Field(0, ge=0, le=100, description="Correlation percentage")


class LossConfig(BaseModel):
    pct: float = Field(0, ge=0, le=100, description="Packet loss percentage")
    correlation_pct: float = Field(0, ge=0, le=100, description="Correlation percentage")


class CorruptConfig(BaseModel):
    pct: float = Field(0, ge=0, le=100, description="Packet corruption percentage")


class DuplicateConfig(BaseModel):
    pct: float = Field(0, ge=0, le=100, description="Packet duplication percentage")


class ReorderConfig(BaseModel):
    pct: float = Field(0, ge=0, le=100, description="Packet reorder percentage")
    correlation_pct: float = Field(0, ge=0, le=100, description="Correlation percentage")


class RateConfig(BaseModel):
    kbit: int = Field(0, ge=0, description="Rate limit in kbit/s (0 = unlimited)")
    burst: str = Field("32kbit", description="Burst size (e.g., '32kbit')")


class ImpairmentConfig(BaseModel):
    """Full impairment configuration for an interface."""

    delay: Optional[DelayConfig] = None
    loss: Optional[LossConfig] = None
    corrupt: Optional[CorruptConfig] = None
    duplicate: Optional[DuplicateConfig] = None
    reorder: Optional[ReorderConfig] = None
    rate: Optional[RateConfig] = None

    def is_empty(self) -> bool:
        """Return True if no impairments are configured."""
        return all(
            v is None
            for v in (self.delay, self.loss, self.corrupt, self.duplicate, self.reorder, self.rate)
        )


class InterfaceImpairmentState(BaseModel):
    """Current impairment state for an interface, as read back from tc."""

    interface: str
    active: bool = False
    config: ImpairmentConfig = ImpairmentConfig()
    per_client: Dict[str, ImpairmentConfig] = Field(
        default_factory=dict,
        description="Per-client impairments keyed by IP address",
    )
