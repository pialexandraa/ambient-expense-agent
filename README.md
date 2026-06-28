# Ambient Expense Agent

# About

This is an event-driven expense evaluation agent built with Google's Agent Development Kit (ADK) and human intervetion. The tool goes a bit beyond the standard code-generated project.

The human intervention in this case included (besides the standard orchestration): code modifications to fit the needs, optimizations for performance improvements, security tweaks, and automated pipeline(s).

# Stack and Structure

The tools/stack used are: Gemini (various models), Antigrativity and IDE, ADK v.2.0 (the Google's Agent creation toolkit), and other code editors and local machine items.

The functioning mechanism of this agent is intended to be in 2 ways:
1. Can be a browser-based app that ingests JSON payloads and follows a specific approval sequence.

For visualization purposes, this is what it looks like during testing; plus, at the left side, the approval schema (step-by-step):






2. Can be (truly) an ambient agent/tool that runs in the background and handles the approval/refusal processes.

In this case, the FastAPI web server would run for example in production and for amounts over the 50$ sum, would save the state to the database (or other indicated endpoint) and send a notifications requiring manual human approval (via, let's say as an example: a Slack notification or a webhook set up to a dashboard, etc).

By looking at this schema, the background process, truly ambient, would like that:



It runs as a background process that automatically processes expense reports sent via Pub/Sub events, filters out PII, checks for prompt injection, automatically approves low-value expenses, runs LLM risk analysis on high-value expenses (over the value of 50$), and suspends for human review if necessary.

---

## 🚀 Quick Start

### 1. Installation
Install the project dependencies and set up the virtual environment:
```bash
make install
```

### 2. Run Tests
Verify that the codebase, FastAPI server, and agent workflows load and function correctly:
```bash
uv run pytest
```

---

## 💻 How to Run & Test

### Option A: The Interactive Playground (Testing/UI Mode)
Great for development. This starts a local chat-like interface that lets you send payloads and interactively approve or reject expenses via a simple yes/no text field.

1. Start the playground:
   ```bash
   make playground
   ```
2. Open the URL provided in the terminal (usually `http://localhost:8085`).
3. Send a test payload to trigger the workflow.

---

### Option B: The FastAPI Web Server (Production/API Mode)
This runs the agent as a background web service listening to webhooks or Pub/Sub events.

1. Start the FastAPI server:
   ```bash
   make run
   ```
2. Trigger the server locally on the CLI using `curl` with a mock Pub/Sub payload:

   * **Auto-Approval Payload ($10.00)**:
     ```bash
     curl -X POST http://localhost:8080/apps/expense_agent/trigger/pubsub \
       -H "Content-Type: application/json" \
       -d '{"message": {"data": "eyJhbW91bnQiOiAxMC4wLCAic3VibWl0dGVyIjogImFsaWNlQGNvbXBhbnkuY29tIiwgImNhdGVnb3J5IjogInNvZnR3YXJlIiwgImRlc2NyaXB0aW9uIjogIklERSBMaWNlbnNlIiwgImRhdGUiOiAiMjAyNi0wNi0wNiJ9"}, "subscription": "projects/my-project/subscriptions/my-sub"}'
     ```

   * **Manual Review Payload ($250.00)**:
     ```bash
     curl -X POST http://localhost:8080/apps/expense_agent/trigger/pubsub \
       -H "Content-Type: application/json" \
       -d '{"message": {"data": "eyJhbW91bnQiOiAyNTAuMCwgInN1Ym1pdHRlciI6ICJhbGljZUBjb21wYW55LmNvbSIsICJjYXRlZ29yeSI6ICJzb2Z0d2FyZSIsICJkZXNjcmlwdGlvbiI6ICJFbnRlcnByaXNlIFN1YnNjcmlwdGlvbiIsICJkYXRlIjogIjIwMjYtMDYtMjgifQ=="}, "subscription": "projects/my-project/subscriptions/my-sub"}'
     ```

---

## 👥 How Human-in-the-Loop (HITL) Works

When an expense exceeds the **$50.00 threshold**, it requires human approval. The agent handles this depending on how it's run:

* **In the Playground**: The agent yields a prompt requesting your decision. The UI renders a text field allowing you to type `yes` or `no` to approve/reject the expense.
* **On the Web Server**: The server does not block the request. It automatically saves the agent's state to a local SQLite database (`session.db`) and pauses. To resume the workflow, an external application (like Slack or email) sends a `POST` request containing the decision to the `/apps/expense_agent/resume` endpoint.
