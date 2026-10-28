"""Pure stock-ledger logic for the scrap service.

Stock movements are immutable: receipts (+), issues (-), transfers (out/in),
adjustments (+/-), reservations (hold). Balance = sum of signed quantities.
Negative balance is refused by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


class StockError(ValueError):
    pass


VALID_MOVEMENT_TYPES = {"receipt", "issue", "transfer_out", "transfer_in", "adjustment", "reservation", "release"}


@dataclass
class Movement:
    material_id: int
    warehouse_id: int
    quantity: float
    movement_type: str
    unit: str = "kg"
    reference: Optional[str] = None
    actor: Optional[str] = None
    reason: Optional[str] = None

    def signed_quantity(self) -> float:
        if self.movement_type in ("issue", "transfer_out", "reservation"):
            return -abs(self.quantity)
        if self.movement_type in ("receipt", "transfer_in", "release"):
            return abs(self.quantity)
        # adjustment keeps sign of quantity
        return self.quantity

    def validate(self) -> List[str]:
        problems: List[str] = []
        if self.movement_type not in VALID_MOVEMENT_TYPES:
            problems.append("unknown movement type %r" % self.movement_type)
        if self.quantity == 0:
            problems.append("quantity cannot be zero")
        if self.quantity < 0 and self.movement_type not in ("adjustment",):
            problems.append("quantity must be positive for this movement type")
        if self.movement_type == "adjustment" and not (self.reason or "").strip():
            problems.append("adjustment requires a reason")
        return problems


def compute_balance(movements: List[Movement]) -> float:
    return round(sum(m.signed_quantity() for m in movements), 3)


def would_go_negative(current_balance: float, movement: Movement, allow_negative: bool = False) -> bool:
    new_balance = current_balance + movement.signed_quantity()
    if new_balance < 0 and not allow_negative:
        return True
    return False
