from __future__ import annotations

import inspect
import json
import os
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast, overload

from pydantic import BaseModel

P = ParamSpec("P")
R = TypeVar("R")


class JsonFileWriter:
    """Persist returned JSON-model instances to per-class files.

    Each JSON-capable class is mapped to one file in the user-provided
    directory. When a wrapped callable returns a supported model instance, the
    object is serialized in pretty JSON format and appended to that file.
    """

    def __init__(
        self,
        output_dir: str | os.PathLike[str],
        *,
        indent: int = 2,
        encoding: str = "utf-8",
    ) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._indent = indent
        self._encoding = encoding

    @overload
    def wrap(self, func: Callable[P, R]) -> Callable[P, R]: ...

    @overload
    def wrap(self, func: None = None) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

    def wrap(
        self,
        func: Callable[P, R] | None = None,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """Wrap a callable and append JSON-model return values to disk."""
        if func is None:
            return self._build_wrapper

        return self._build_wrapper(func)

    def __call__(
        self,
        func: Callable[P, R] | None = None,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        return self.wrap(func)

    def _build_wrapper(self, func: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                result = await cast(Any, func)(*args, **kwargs)
                self._append_if_json(result)
                return cast(R, result)

            return cast(Callable[P, R], async_wrapper)

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            result = func(*args, **kwargs)
            self._append_if_json(result)
            return result

        return sync_wrapper

    def _append_if_json(self, value: Any) -> None:
        if not isinstance(value, BaseModel):
            return

        file_path = self._file_path_for(value)
        json_text = self._dump_json(value)

        with file_path.open("a", encoding=self._encoding) as handle:
            if file_path.stat().st_size > 0:
                handle.write("\n\n")
            handle.write(json_text)
            handle.write("\n")

    def _dump_json(self, value: BaseModel) -> str:
        if hasattr(value, "model_dump_json"):
            return cast(Any, value).model_dump_json(indent=self._indent)

        return json.dumps(
            value.dict(),
            indent=self._indent,
            ensure_ascii=False,
        )

    def _file_path_for(self, value: BaseModel) -> Path:
        class_name = value.__class__.__module__ + "." + value.__class__.__qualname__
        file_name = class_name.replace(os.sep, "_").replace(".", "__") + ".json"
        return self._output_dir / file_name
