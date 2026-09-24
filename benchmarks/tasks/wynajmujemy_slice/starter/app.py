"""Starter. Every route fails until the service is implemented."""

from starlette.applications import Starlette
from starlette.responses import JSONResponse


def create_app(*, seed=None, fetcher=None, sender=None):
    app = Starlette()

    @app.middleware("http")
    async def unimplemented(request, call_next):
        return JSONResponse({"error": "not_implemented"}, status_code=501)

    def set_now(_dt):
        return None

    app.state.set_now = set_now
    app.state.fetcher = fetcher
    return app
