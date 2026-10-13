"""Synthetic tachograph fixtures.

Everything here is generated from the regulation. No real driver card data — no
names, no card numbers, no activity — is stored in this repository.
"""

from .gen1_writer import (
    CardDownloadBuilder,
    make_garbage,
    make_sample_card_download,
    make_truncated_card_download,
    make_vu_download,
)

__all__ = [
    "CardDownloadBuilder",
    "make_garbage",
    "make_sample_card_download",
    "make_truncated_card_download",
    "make_vu_download",
]
