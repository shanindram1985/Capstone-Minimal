from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def load_environment(dotenv_path: Path | None = None) -> None:
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parents[1] / ".env"
    if load_dotenv and dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path)
