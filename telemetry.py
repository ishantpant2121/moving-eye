# telemetry.py
"""
Telemetry wrapper for Sentry (exception tracking) and PostHog (event analytics).
Gracefully degrades to local logging if SDKs are missing or credentials are not configured.
"""
import logging
import os

logger = logging.getLogger("Telemetry")

# Try to load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

SENTRY_DSN = os.environ.get("SENTRY_DSN")
HAS_SENTRY = False
if SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=1.0,
        )
        logger.info("[TELEMETRY] Sentry initialized successfully.")
        HAS_SENTRY = True
    except ImportError:
        logger.warning("[TELEMETRY] Sentry SDK not installed. Standard logging fallback.")
    except Exception as e:
        logger.error(f"[TELEMETRY] Failed to initialize Sentry: {e}")

POSTHOG_API_KEY = os.environ.get("POSTHOG_API_KEY")
POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.posthog.com")
HAS_POSTHOG = False
if POSTHOG_API_KEY:
    try:
        from posthog import Posthog
        posthog_client = Posthog(POSTHOG_API_KEY, host=POSTHOG_HOST)
        logger.info("[TELEMETRY] PostHog initialized successfully.")
        HAS_POSTHOG = True
    except ImportError:
        logger.warning("[TELEMETRY] PostHog SDK not installed. Standard logging fallback.")
    except Exception as e:
        logger.error(f"[TELEMETRY] Failed to initialize PostHog: {e}")

def capture_exception(exc):
    """Gracefully capture exception in Sentry or fall back to standard logging."""
    if HAS_SENTRY:
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
            return
        except Exception:
            pass
    logger.error(f"[TELEMETRY] Exception captured locally: {exc}", exc_info=True)

def track_event(distinct_id, event_name, properties=None):
    """Gracefully capture event in PostHog or fall back to standard logging."""
    if properties is None:
        properties = {}
    if HAS_POSTHOG:
        try:
            posthog_client.capture(distinct_id, event_name, properties)
            return
        except Exception as e:
            logger.error(f"[TELEMETRY] Failed to capture event in PostHog: {e}")
    # Always log locally as backup
    logger.info(f"[TELEMETRY] Event tracked [{distinct_id}]: {event_name} - {properties}")
