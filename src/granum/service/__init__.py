"""The Granum Object Service."""

from granum.service.cache import ByteCache

__all__ = ["ByteCache", "create_app", "serve"]


def create_app(**kwargs):
    """Build the FastAPI application. Imported lazily so the SDK stays light."""
    from granum.service.app import create_app as _create_app

    return _create_app(**kwargs)


def serve(host: str = "127.0.0.1", port: int = 8000, **kwargs) -> None:
    """Run the Object Service."""
    import uvicorn

    uvicorn.run(create_app(**kwargs), host=host, port=port)
