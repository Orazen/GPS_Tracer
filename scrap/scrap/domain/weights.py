"""Pure weight logic for the scrap service.

Net weight = gross - tare. All values in a single unit (kg). Validation flags
implausible or negative values. No database access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List


class WeightError(ValueError):
    pass


@dataclass
class WeighTicket:
    gross: float
    tare: float
    unit: str = "kg"
    scale_ref: Optional[str] = None
    ticket_number: Optional[str] = None

    @property
    def net(self) -> float:
        return round(self.gross - self.tare, 3)

    def validate(self) -> List[str]:
        problems: List[str] = []
        if self.unit not in ("kg", "t", "lb"):
            problems.append("unit must be kg, t, or lb")
        if self.gross < 0:
            problems.append("gross weight cannot be negative")
        if self.tare < 0:
            problems.append("tare weight cannot be negative")
        if self.tare > self.gross:
            problems.append("tare weight cannot exceed gross weight")
        if self.gross == 0 and self.tare == 0:
            problems.append("both weights are zero")
        if self.net > 50000:
            problems.append("net weight exceeds 50000 kg - check units or scale")
        if self.net < 0:
            problems.append("net weight is negative")
        return problems

    def is_plausible(self) -> bool:
        return not self.validate()


def convert_to_kg(value: float, unit: str) -> float:
    if unit == "kg":
        return value
    if unit == "t":
        return value * 1000.0
    if unit == "lb":
        return value * 0.45359237
    raise WeightError("unknown unit %r" % unit)


def compute_net(gross: float, tare: float, unit: str = "kg") -> float:
    ticket = WeighTicket(gross=gross, tare=tare, unit=unit)
    errors = ticket.validate()
    if errors:
        raise WeightError("; ".join(errors))
    return ticket.net
