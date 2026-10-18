from prometheus_client import Counter, Histogram, Gauge

http_requests_total = Counter(
    "xa_http_requests_total", "HTTP requests",
    ["method", "route", "status"],
)
http_request_seconds = Histogram(
    "xa_http_request_seconds", "HTTP latency",
    ["method", "route"],
)
inference_requests_total = Counter(
    "xa_inference_requests_total", "Model inference requests",
    ["model", "status"],
)
inference_seconds = Histogram(
    "xa_inference_seconds", "Model inference duration",
    ["model"],
)
jobs_total = Counter("xa_jobs_total", "Jobs by terminal status", ["job_type", "status"])
jobs_in_flight = Gauge("xa_jobs_in_flight", "Jobs currently running", ["job_type"])
webhook_deliveries_total = Counter(
    "xa_webhook_deliveries_total", "Webhook deliveries", ["status"],
)
rate_limit_hits_total = Counter(
    "xa_rate_limit_hits_total", "Rate limit hits", ["route"],
)
quota_rejections_total = Counter(
    "xa_quota_rejections_total", "Quota rejections", ["key"],
)
voice_sessions_total = Counter("xa_voice_sessions_total", "Voice sessions", ["status"])
voice_utterance_seconds = Histogram(
    "xa_voice_utterance_seconds", "Voice utterance duration",
)
agent_runs_total = Counter(
    "xa_agent_runs_total", "Agent runs by status", ["status"],
)
agent_steps_total = Counter("xa_agent_steps_total", "Agent steps", ["tool"])
device_commands_total = Counter(
    "xa_device_commands_total", "Device commands", ["status"],
)
outbox_events_total = Counter(
    "xa_outbox_events_total", "Outbox events", ["event", "status"],
)
