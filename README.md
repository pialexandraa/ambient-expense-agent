> [!NOTE]
> **This project is a Work in Progress (WIP).** The application is in active prototyping.

Expenses evaluating agent with an added layer of ambient mechanics that turns it into a background process: event-driven (Pub/Sub events containing an expense payload), on the always-on-execution model, with server-side runtime.

Without the ambient process, it can be used as a UI-based tool, a chat-like UI that ingests JSON payloads instead of user text/commands :)

It is build with ADK (Agent Development Kit), Google tools, Gemini, and Human-in-the-loop. The code is machine generated as per Google agents cli methodology.

The Human-in-the-loop: code tweaks and modifications to what was produced by the AI (for example, security changes or checks), changes to the initials templates, UI tests changes, pipeline automations, etc.
