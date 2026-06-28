import json
import logging
import uvicorn
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from google.adk.cli.fast_api import get_fast_api_app

# 1. Setup standard Python logging for console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("expense_agent_runtime")

# 2. Construct the FastAPI App from ADK
# We use get_fast_api_app with otel_to_cloud=False and trace_to_cloud=False as requested.
# The trigger_sources=["pubsub"] exposes the trigger endpoint.
app = get_fast_api_app(
    agents_dir="expense_agent",
    web=False,
    otel_to_cloud=True,
    trace_to_cloud=True,
    trigger_sources=["pubsub"]
)

# 3. Add middleware to normalize the Pub/Sub subscription name
class PubSubNormalizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # We only target the Pub/Sub trigger endpoint
        if request.url.path == "/apps/expense_agent/trigger/pubsub" and request.method == "POST":
            body = await request.body()
            try:
                data = json.loads(body.decode("utf-8"))
                if "subscription" in data and isinstance(data["subscription"], str):
                    original_sub = data["subscription"]
                    # Normalize subscription path to keep session records readable
                    normalized_sub = original_sub.split("/")[-1]
                    data["subscription"] = normalized_sub
                    logger.info(f"Normalizing Pub/Sub subscription path from '{original_sub}' to '{normalized_sub}'")
                    
                    new_body = json.dumps(data).encode("utf-8")
                    async def receive():
                        return {"type": "http.request", "body": new_body, "more_body": False}
                    request._receive = receive
            except Exception as e:
                logger.warning(f"Failed to parse or normalize request body: {e}")
                
        return await call_next(request)

app.add_middleware(PubSubNormalizeMiddleware)

if __name__ == "__main__":
    logger.info("Starting local web service on port 8080...")
    uvicorn.run(app, host="0.0.0.0", port=8080)
