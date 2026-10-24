import sys
from pathlib import Path
from threading import Lock
from typing import Any


_generator: Any | None = None
_generator_lock = Lock()


def get_answer_generator() -> Any:
    global _generator

    if _generator is None:
        with _generator_lock:
            if _generator is None:
                project_root = str(Path(__file__).resolve().parents[3])
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                from src.answer_generator import ComplianceAnswerGenerator

                _generator = ComplianceAnswerGenerator()

    return _generator
