# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import os
import re
from typing import Any
from dotenv import load_dotenv
from pydantic import BaseModel
import google.cloud.dlp_v2 as dlp_v2

# Load local environment variables from .env
load_dotenv()

# Setup local authentication fallback for Google Cloud / Vertex AI
if not os.environ.get("GEMINI_API_KEY"):
    import google.auth
    try:
        _, project_id = google.auth.default()
        if project_id:
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
    except Exception:
        pass
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.workflow import Workflow, node, START
from google.genai import types

# Import config thresholds
from expense_agent.config import THRESHOLD, MODEL_NAME

# (Note: In a production setting, you might want to initialize this once globally or handle auth more robustly)
dlp_project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")

# Suspicious phrases checklist for prompt injection defense
SUSPICIOUS_PHRASES = [
    "ignore", "instruction", "bypass", "override", "system", 
    "auto-approve", "auto approve", "instead", "do not flag", 
    "forget all prior", "assistant instructions"
]


# ==============================================================================
# Helper Security Functions
# ==============================================================================
def scrub_pii_and_check_injection(expense: dict) -> tuple[dict, list[str], bool]:
    """Scrubs International PII from description using Cloud DLP and checks for prompt injection."""
    description = expense.get("description", "")
    redacted_categories = []
    clean_expense = dict(expense)
    suspicious = False
    
    if not description:
        return clean_expense, redacted_categories, suspicious

    # 1. Scrub PII using Google Cloud DLP
    if dlp_project:
        try:
            # Instantiate the DLP client inside the try block to avoid crashing on missing credentials
            dlp_client = dlp_v2.DlpServiceClient()
            
            # Define infoTypes we care about globally
            info_types = [
                {"name": "CREDIT_CARD_NUMBER"},
                {"name": "SWEDEN_PERSONAL_IDENTITY_NUMBER"},
                {"name": "DENMARK_CPR_NUMBER"},
                {"name": "ROMANIA_CNP"},
                {"name": "FRANCE_NIR"},
                {"name": "GERMANY_IDENTITY_CARD_NUMBER"},
                {"name": "NETHERLANDS_BSN_NUMBER"},
                {"name": "NETHERLANDS_PASSPORT"},
                {"name": "PERSON_NAME"},
            ]
            
            # Configure inspection and deidentification
            inspect_config = {
                "info_types": info_types,
                "min_likelihood": dlp_v2.Likelihood.LIKELY
            }
            
            # Use simple masking (replace with [INFO_TYPE])
            deidentify_config = {
                "info_type_transformations": {
                    "transformations": [
                        {
                            "primitive_transformation": {
                                "replace_with_info_type_config": {}
                            }
                        }
                    ]
                }
            }
            
            item = {"value": description}
            parent = f"projects/{dlp_project}/locations/global"
            
            response = dlp_client.deidentify_content(
                request={
                    "parent": parent,
                    "deidentify_config": deidentify_config,
                    "inspect_config": inspect_config,
                    "item": item,
                }
            )
            scrubbed_desc = response.item.value
            
            # Inspect to get the categories that were redacted
            inspect_response = dlp_client.inspect_content(
                request={
                    "parent": parent,
                    "inspect_config": inspect_config,
                    "item": item,
                }
            )
            for finding in inspect_response.result.findings:
                if finding.info_type.name not in redacted_categories:
                    redacted_categories.append(finding.info_type.name)
                    
        except Exception as e:
            # Fallback if DLP fails (e.g. API not enabled, no auth) - just pass through
            scrubbed_desc = description
            print(f"Warning: DLP API Error or Missing Credentials: {e}")
    else:
        scrubbed_desc = description
        print("Warning: No GOOGLE_CLOUD_PROJECT set, skipping DLP PII scrubbing.")

    clean_expense["description"] = scrubbed_desc

    # 2. Check for prompt injection keywords
    lower_desc = scrubbed_desc.lower()
    for phrase in SUSPICIOUS_PHRASES:
        if phrase in lower_desc:
            suspicious = True
            break

    return clean_expense, redacted_categories, suspicious


# ==============================================================================
# 1. Parsing Node
# ==============================================================================
@node
def parse_expense(node_input: Any) -> dict:
    """Parses and extracts expense fields from base64 Pub/Sub or plain JSON."""
    payload = None

    # Handle input type from START
    if hasattr(node_input, 'parts'):  # types.Content from CLI
        parts_text = [p.text for p in node_input.parts if p.text]
        payload_str = "".join(parts_text)
        try:
            payload = json.loads(payload_str)
        except Exception:
            payload = payload_str
    elif isinstance(node_input, dict):
        payload = node_input
    elif isinstance(node_input, str):
        try:
            payload = json.loads(node_input)
        except Exception:
            payload = node_input

    # Extract the data field (supports both flat JSON or nested under 'data'/'message.data')
    data_field = None
    if isinstance(payload, dict):
        if "amount" in payload:
            data_field = payload
        elif "message" in payload and isinstance(payload["message"], dict):
            data_field = payload["message"].get("data")
        else:
            data_field = payload.get("data")
    else:
        data_field = payload

    # If data_field is a string, check if it's base64-encoded or a JSON string
    if isinstance(data_field, str):
        try:
            # Try to decode from base64
            decoded_bytes = base64.b64decode(data_field)
            data_field = json.loads(decoded_bytes.decode("utf-8"))
        except Exception:
            # Fallback to direct JSON parsing if not base64
            try:
                data_field = json.loads(data_field)
            except Exception:
                pass

    # Extract clean expense metadata fields
    expense = {}
    if isinstance(data_field, dict) and "amount" in data_field:
        expense["amount"] = float(data_field.get("amount", 0.0))
        expense["submitter"] = data_field.get("submitter", "Unknown")
        expense["category"] = data_field.get("category", "Uncategorized")
        expense["description"] = data_field.get("description", "No description")
        expense["date"] = data_field.get("date", "Unknown")
    else:
        raise ValueError(
            "Invalid expense payload! Please submit a JSON object containing at least "
            "an 'amount' field. Example:\n"
            '{"amount": 150.0, "submitter": "alice@company.com", "category": "software", "description": "IDE License", "date": "2026-06-06"}'
        )

    return expense


# ==============================================================================
# 2. Routing Node (Pure Python)
# ==============================================================================
@node
def route_expense(node_input: dict) -> Event:
    """Routes the expense report depending on the configured threshold."""
    amount = node_input.get("amount", 0.0)
    
    # Store expense details in workflow context state
    state_delta = {"expense": node_input}

    if amount < THRESHOLD:
        return Event(output=node_input, route="auto_approve", state=state_delta)
    else:
        return Event(output=node_input, route="manual_review", state=state_delta)


# ==============================================================================
# 3. Security Checkpoint Node (PII and Injection Defense)
# ==============================================================================
@node
def security_checkpoint(ctx: Context, node_input: dict) -> Event:
    """Sanitizes PII and defends against prompt injection before invoking LLM."""
    clean_expense, redacted, suspicious = scrub_pii_and_check_injection(node_input)

    state_delta = {
        "expense": clean_expense,
        "redacted_categories": redacted
    }

    if suspicious:
        # Preemptively construct a mock high-risk assessment and bypass the LLM
        security_incident_assessment = {
            "risk_score": 10,
            "risk_factors": ["PROMPT INJECTION ATTEMPT DETECTED (SECURITY CHECKPOINT)"],
            "assessment_summary": (
                "LLM review bypassed to prevent injection attempt. "
                "The expense description contained suspicious instruction override phrases."
            )
        }
        # Route straight to human approval
        return Event(
            output=security_incident_assessment,
            route="flagged",
            state=state_delta
        )
    else:
        # Route clean output to risk_analyst LLM
        return Event(
            output=clean_expense,
            route="clean",
            state=state_delta
        )


# ==============================================================================
# 4. Auto-Approval Node
# ==============================================================================
@node
def auto_approve(node_input: dict) -> dict:
    """Instantly auto-approves low value expenses."""
    return {
        "status": "APPROVED",
        "reason": f"Amount is under the ${THRESHOLD} threshold.",
        "expense": node_input,
    }


# ==============================================================================
# 5. LLM Risk Analyst Node
# ==============================================================================
class RiskAssessment(BaseModel):
    risk_score: int  # Scale 1-10
    risk_factors: list[str]
    assessment_summary: str


risk_analyst = LlmAgent(
    name="risk_analyst",
    model=MODEL_NAME,
    instruction=(
        "You are a professional corporate expense risk analyst. Review the provided expense "
        "report details for signs of policy violations, fraud, or high-risk spending. "
        "Provide a risk score (1-10), a list of risk factors, and a concise summary."
    ),
    output_schema=RiskAssessment,
    output_key="risk_assessment",  # Save structured output into context state
)


# ==============================================================================
# 6. Human-in-the-Loop Node
# ==============================================================================
# ==============================================================================
# 6. Human-in-the-Loop Node
# ==============================================================================
@node(rerun_on_resume=True)
async def hitl_approval(ctx: Context, node_input: dict):
    """Pauses workflow for a human reviewer to approve or reject high value expenses."""
    expense = ctx.state.get("expense", {})
    risk_assessment = node_input
    redacted = ctx.state.get("redacted_categories", [])
    
    redacted_info = f" (PII Redacted: {', '.join(redacted)})" if redacted else ""

    if not ctx.resume_inputs:
        msg = (
            f"⚠️  High-value expense requires approval (>= ${THRESHOLD}):\n"
            f"  Submitter:   {expense.get('submitter')}\n"
            f"  Amount:      ${expense.get('amount'):.2f}\n"
            f"  Category:    {expense.get('category')}\n"
            f"  Description: {expense.get('description')}{redacted_info}\n"
            f"  Date:        {expense.get('date')}\n\n"
            f"🔍  Risk Assessment Summary:\n"
            f"  Risk Score:  {risk_assessment.get('risk_score')}/10\n"
            f"  Risk Factors: {', '.join(risk_assessment.get('risk_factors', []))}\n"
            f"  Summary:     {risk_assessment.get('assessment_summary')}\n\n"
            f"Approve this expense? (Yes/No)"
        )
        yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=msg)]))
        yield RequestInput(
            interrupt_id="expense_decision",
            message=msg,
        )
        return

    # Read human choice from resume input
    decision = ctx.resume_inputs.get("expense_decision", "")
    is_approved = "yes" in str(decision).lower()

    yield Event(
        output={
            "status": "APPROVED" if is_approved else "REJECTED",
            "reason": "Human approval" if is_approved else f"Human rejection: {decision}",
            "risk_assessment": risk_assessment,
            "expense": expense,
        }
    )


# ==============================================================================
# 7. Finalization Node
# ==============================================================================
@node
def record_outcome(node_input: dict):
    """Outputs a clean, human-friendly summary of the final decision."""
    status = node_input.get("status", "UNKNOWN")
    reason = node_input.get("reason", "No reason provided.")
    expense = node_input.get("expense", {})
    amount = expense.get("amount", 0.0)
    submitter = expense.get("submitter", "Unknown")
    
    summary = (
        f"🏁 **Expense Workflow Completed**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 **Decision:** **{status}**\n"
        f"👤 **Submitter:** {submitter}\n"
        f"💰 **Amount:** ${amount:.2f}\n"
        f"📝 **Reason:** {reason}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    print(summary)
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=summary)]))
    yield Event(output=node_input)


# ==============================================================================
# 8. Workflow Definition (Wired Graph)
# ==============================================================================
root_agent = Workflow(
    name="root_agent",
    edges=[
        (START, parse_expense),
        (parse_expense, route_expense),
        (route_expense, {
            "auto_approve": auto_approve,
            "manual_review": security_checkpoint,
        }),
        (security_checkpoint, {
            "clean": risk_analyst,
            "flagged": hitl_approval,
        }),
        (risk_analyst, hitl_approval),
        (auto_approve, record_outcome),
        (hitl_approval, record_outcome),
    ],
    rerun_on_resume=False,
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
)
