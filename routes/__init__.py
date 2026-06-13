from .auth import auth_blueprint
from .downloads import downloads_blueprint
from .index import index_blueprint
from .library import library_blueprint
from .stream import stream_blueprint

__all__ = [
    "auth_blueprint",
    "downloads_blueprint",
    "index_blueprint",
    "library_blueprint",
    "stream_blueprint",
]
