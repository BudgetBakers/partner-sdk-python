"""budgetbakers-partner-sdk — BudgetBakers Partner API server SDK (WP4.2).

Spec: spec/partner-api-v1.1.yaml (single source of truth, D9).
"""

from . import webhooks
from ._lossless import MONEY_KEYS, quantize2
from .client import DEFAULT_BASE_URL, BudgetBakers, ClientScope
from .errors import PartnerApiError, PartnerApiUnreachable
from .webhooks import SIGNATURE_HEADER, TOLERANCE_SECONDS, parse_event, sign, verify

__version__ = "0.1.1"

__all__ = [
    "DEFAULT_BASE_URL",
    "MONEY_KEYS",
    "SIGNATURE_HEADER",
    "TOLERANCE_SECONDS",
    "BudgetBakers",
    "ClientScope",
    "PartnerApiError",
    "PartnerApiUnreachable",
    "__version__",
    "parse_event",
    "quantize2",
    "sign",
    "verify",
    "webhooks",
]
