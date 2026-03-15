"""
Banking Workflow Engine.

Maps detected intent to a structured workflow context used by the
response generator and downstream systems.
"""

import logging
import time
from typing import Any, Dict, Tuple

from models.intent_models import WORKFLOW_CONFIG

logger = logging.getLogger("WorkflowEngine")


# Human-readable summaries shown in the pipeline UI
_ACTION_SUMMARIES: Dict[str, str] = {
    "greet":             "Welcome customer, ready to assist",
    "balance_inquiry":   "Retrieve account balance",
    "send_statement":    "Generate and send account statement",
    "block_card":        "Initiate card blocking workflow",
    "raise_dispute":     "Open transaction dispute ticket",
    "check_kyc":         "Query KYC verification status",
    "emi_inquiry":       "Fetch EMI schedule and due date",
    "foreclosure_info":  "Calculate foreclosure amount and charges",
    "update_address":    "Initiate address change workflow",
    "record_ptp":        "Record promise-to-pay commitment",
    "send_paylink":      "Generate and send payment link",
    "hardship_program":  "Escalate to hardship / restructuring team",
    "schedule_callback": "Schedule outbound callback",
    "transfer_agent":    "Escalate to live human agent",
    "farewell":          "Close interaction gracefully",
    "partial_payment":   "Process partial payment arrangement",
    "full_payment":      "Process full payment — send payment link",
}


class WorkflowEngine:
    """Determines the workflow action and context for a given intent."""

    async def process(
        self,
        intent: str,
        transcript_en: str,
    ) -> Tuple[Dict[str, Any], float]:
        """
        Process intent and return workflow context.

        Returns:
            (workflow_context_dict, latency_ms)
        """
        t0 = time.perf_counter()

        cfg = WORKFLOW_CONFIG.get(
            intent,
            {"action": "unknown", "escalate": False, "send_paylink": False},
        )

        context: Dict[str, Any] = {
            "action":       cfg["action"],
            "escalate":     cfg["escalate"],
            "send_paylink": cfg["send_paylink"],
            "summary":      _ACTION_SUMMARIES.get(cfg["action"], cfg["action"]),
            "intent":       intent,
            "customer_message_en": transcript_en,
        }

        latency_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            f"✅ Workflow: action={context['action']}  escalate={context['escalate']}  "
            f"paylink={context['send_paylink']}  [{latency_ms:.0f}ms]"
        )
        return context, latency_ms
