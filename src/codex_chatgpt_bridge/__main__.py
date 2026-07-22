from .config import Settings
from .server import mcp


def main() -> None:
    settings = Settings()
    mcp.run(transport=settings.transport)


if __name__ == "__main__":
    main()
