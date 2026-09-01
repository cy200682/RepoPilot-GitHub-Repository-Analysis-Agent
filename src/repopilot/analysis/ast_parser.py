"""Safe single-file Python AST extraction without importing target code."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Sized
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repopilot.analysis.models import (
    CallSiteRecord,
    ImportRecord,
    InheritanceRecord,
    PythonFileAnalysis,
    ReferenceKind,
    ReferenceRecord,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from repopilot.config import Settings
from repopilot.repository.reader import RepositoryReaderProtocol


def stable_id(prefix: str, *parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _safe_expression(node: ast.AST, max_chars: int = 200) -> str:
    try:
        value = ast.unparse(node)
    except Exception:
        value = node.__class__.__name__
    value = " ".join(value.split())
    return value[:max_chars]


def _span(path: str, node: ast.AST) -> SourceSpan:
    start_line = int(getattr(node, "lineno", 1))
    start_col = int(getattr(node, "col_offset", 0))
    end_line_value = getattr(node, "end_lineno", None)
    end_col_value = getattr(node, "end_col_offset", None)
    complete = end_line_value is not None and end_col_value is not None
    return SourceSpan(
        path=path,
        start_line=start_line,
        start_col=start_col,
        end_line=int(end_line_value or start_line),
        end_col=int(end_col_value or start_col),
        span_complete=complete,
    )


@dataclass(slots=True)
class _Scope:
    symbol_id: str
    qualified_name: str
    kind: SymbolKind


class _Extractor(ast.NodeVisitor):
    def __init__(self, path: str, module_name: str, settings: Settings, total_lines: int) -> None:
        self.path = path
        self.module_name = module_name
        self.settings = settings
        self.symbols: list[SymbolRecord] = []
        self.imports: list[ImportRecord] = []
        self.inheritances: list[InheritanceRecord] = []
        self.calls: list[CallSiteRecord] = []
        self.references: list[ReferenceRecord] = []
        module_id = f"{module_name}:<module>"
        self.scopes = [_Scope(module_id, "<module>", "module")]
        self.symbols.append(
            SymbolRecord(
                symbol_id=module_id,
                name=module_name.rsplit(".", 1)[-1],
                qualified_name="<module>",
                kind="module",
                module_name=module_name,
                path=path,
                span=SourceSpan(
                    path=path,
                    start_line=1,
                    end_line=max(total_lines, 1),
                    end_col=0,
                    span_complete=True,
                ),
            )
        )
        self.truncated = False
        self.notes: list[str] = []
        self.visited_node_count = 0

    def visit(self, node: ast.AST) -> Any:
        if self.visited_node_count >= self.settings.ast_max_nodes_per_file:
            self.truncated = True
            note = f"AST traversal limited to {self.settings.ast_max_nodes_per_file} nodes."
            if note not in self.notes:
                self.notes.append(note)
            return None
        self.visited_node_count += 1
        return super().visit(node)

    @property
    def current(self) -> _Scope:
        return self.scopes[-1]

    def _capacity(self, collection: Sized, limit: int, label: str) -> bool:
        if len(collection) < limit:
            return True
        self.truncated = True
        note = f"{label} limited to {limit} records."
        if note not in self.notes:
            self.notes.append(note)
        return False

    def _qualified(self, name: str) -> str:
        parent = self.current
        if parent.kind == "module":
            return name
        separator = (
            ".<locals>."
            if parent.kind
            in {
                "function",
                "async_function",
                "method",
                "async_method",
            }
            else "."
        )
        return f"{parent.qualified_name}{separator}{name}"

    @staticmethod
    def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        args = node.args
        result = [item.arg for item in args.posonlyargs]
        result.extend(item.arg for item in args.args)
        if args.vararg:
            result.append(f"*{args.vararg.arg}")
        result.extend(item.arg for item in args.kwonlyargs)
        if args.kwarg:
            result.append(f"**{args.kwarg.arg}")
        return result

    def _docstring(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
        value = ast.get_docstring(node, clean=True)
        if not value or self.settings.ast_docstring_max_chars == 0:
            return None
        first_paragraph = value.split("\n\n", 1)[0]
        return first_paragraph[: self.settings.ast_docstring_max_chars]

    def _add_reference(
        self,
        *,
        name: str,
        kind: ReferenceKind,
        node: ast.AST,
        enclosing_symbol_id: str | None = None,
    ) -> None:
        if not self._capacity(
            self.references,
            self.settings.ast_max_relationships_per_file,
            "References",
        ):
            return
        owner = enclosing_symbol_id or self.current.symbol_id
        self.references.append(
            ReferenceRecord(
                reference_id=stable_id(
                    "reference",
                    owner,
                    kind,
                    name,
                    getattr(node, "lineno", 1),
                    getattr(node, "col_offset", 0),
                ),
                symbol_name=name,
                reference_kind=kind,
                enclosing_symbol_id=owner,
                span=_span(self.path, node),
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified = self._qualified(node.name)
        symbol_id = f"{self.module_name}:{qualified}"
        if self._capacity(self.symbols, self.settings.ast_max_symbols_per_file, "Symbols"):
            self.symbols.append(
                SymbolRecord(
                    symbol_id=symbol_id,
                    name=node.name,
                    qualified_name=qualified,
                    kind="class",
                    module_name=self.module_name,
                    path=self.path,
                    span=_span(self.path, node),
                    parent_symbol_id=self.current.symbol_id,
                    decorators=[_safe_expression(item) for item in node.decorator_list],
                    docstring_summary=self._docstring(node),
                    is_nested=self.current.kind != "module",
                )
            )
        for base in node.bases:
            if self._capacity(
                self.inheritances,
                self.settings.ast_max_relationships_per_file,
                "Inheritance relationships",
            ):
                expression = _safe_expression(base)
                self.inheritances.append(
                    InheritanceRecord(
                        relationship_id=stable_id(
                            "inherit", symbol_id, expression, self.path, getattr(base, "lineno", 1)
                        ),
                        subclass_symbol_id=symbol_id,
                        base_expression=expression,
                        base_name=expression.rsplit(".", 1)[-1] if expression else None,
                        span=_span(self.path, base),
                    )
                )
            self._add_reference(
                name=_safe_expression(base).rsplit(".", 1)[-1],
                kind="base",
                node=base,
                enclosing_symbol_id=symbol_id,
            )
        for decorator in node.decorator_list:
            self._add_reference(
                name=_safe_expression(decorator).rsplit(".", 1)[-1],
                kind="decorator",
                node=decorator,
                enclosing_symbol_id=symbol_id,
            )
        self.scopes.append(_Scope(symbol_id, qualified, "class"))
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool
    ) -> None:
        parent_kind = self.current.kind
        if parent_kind == "class":
            kind: SymbolKind = "async_method" if is_async else "method"
        else:
            kind = "async_function" if is_async else "function"
        qualified = self._qualified(node.name)
        symbol_id = f"{self.module_name}:{qualified}"
        if self._capacity(self.symbols, self.settings.ast_max_symbols_per_file, "Symbols"):
            self.symbols.append(
                SymbolRecord(
                    symbol_id=symbol_id,
                    name=node.name,
                    qualified_name=qualified,
                    kind=kind,
                    module_name=self.module_name,
                    path=self.path,
                    span=_span(self.path, node),
                    parent_symbol_id=self.current.symbol_id,
                    parameters=self._parameters(node),
                    decorators=[_safe_expression(item) for item in node.decorator_list],
                    docstring_summary=self._docstring(node),
                    is_async=is_async,
                    is_nested=parent_kind not in {"module", "class"},
                )
            )
        for decorator in node.decorator_list:
            self._add_reference(
                name=_safe_expression(decorator).rsplit(".", 1)[-1],
                kind="decorator",
                node=decorator,
                enclosing_symbol_id=symbol_id,
            )
        self.scopes.append(_Scope(symbol_id, qualified, kind))
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if not self._capacity(
                self.imports, self.settings.ast_max_relationships_per_file, "Imports"
            ):
                break
            self.imports.append(
                ImportRecord(
                    import_id=stable_id(
                        "import", self.module_name, alias.name, alias.asname, node.lineno
                    ),
                    importer_module=self.module_name,
                    kind="import",
                    module=alias.name,
                    alias=alias.asname,
                    span=_span(self.path, node),
                )
            )
            self._add_reference(name=alias.name.rsplit(".", 1)[-1], kind="import", node=node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if not self._capacity(
                self.imports, self.settings.ast_max_relationships_per_file, "Imports"
            ):
                break
            self.imports.append(
                ImportRecord(
                    import_id=stable_id(
                        "from_import",
                        self.module_name,
                        node.level,
                        node.module,
                        alias.name,
                        alias.asname,
                        node.lineno,
                    ),
                    importer_module=self.module_name,
                    kind="from_import",
                    module=node.module,
                    imported_name=alias.name,
                    alias=alias.asname,
                    level=node.level,
                    span=_span(self.path, node),
                )
            )
            self._add_reference(name=alias.name, kind="import", node=node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self._capacity(self.calls, self.settings.ast_max_relationships_per_file, "Calls"):
            expression = _safe_expression(node.func)
            callee_name = None
            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr
            self.calls.append(
                CallSiteRecord(
                    call_id=stable_id(
                        "call", self.current.symbol_id, expression, self.path, node.lineno
                    ),
                    caller_symbol_id=self.current.symbol_id,
                    callee_expression=expression,
                    callee_name=callee_name,
                    span=_span(self.path, node),
                )
            )
            if callee_name:
                self._add_reference(name=callee_name, kind="call", node=node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and self._capacity(
            self.references,
            self.settings.ast_max_relationships_per_file,
            "References",
        ):
            self.references.append(
                ReferenceRecord(
                    reference_id=stable_id(
                        "reference",
                        self.current.symbol_id,
                        "name",
                        node.id,
                        node.lineno,
                        node.col_offset,
                    ),
                    symbol_name=node.id,
                    reference_kind="name",
                    enclosing_symbol_id=self.current.symbol_id,
                    span=_span(self.path, node),
                )
            )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load) and self._capacity(
            self.references,
            self.settings.ast_max_relationships_per_file,
            "References",
        ):
            self.references.append(
                ReferenceRecord(
                    reference_id=stable_id(
                        "reference",
                        self.current.symbol_id,
                        "attribute",
                        node.attr,
                        node.lineno,
                        node.col_offset,
                    ),
                    symbol_name=node.attr,
                    reference_kind="attribute",
                    enclosing_symbol_id=self.current.symbol_id,
                    span=_span(self.path, node),
                )
            )
        self.generic_visit(node)


class PythonAstParser:
    def __init__(self, settings: Settings, reader: RepositoryReaderProtocol) -> None:
        self.settings = settings
        self.reader = reader

    def parse_file(self, root_path: Path, path: str, module_name: str) -> PythonFileAnalysis:
        if not path.endswith(".py"):
            raise ValueError("Python AST analysis requires a .py file.")
        result = self.reader.read_file(root_path, path)
        content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()
        if result.truncated:
            return PythonFileAnalysis(
                path=path,
                module_name=module_name,
                content_hash=content_hash,
                parse_status="truncated",
                truncated=True,
                truncation_notes=["Source file exceeded the safe read limit; AST parse skipped."],
            )
        try:
            tree = ast.parse(result.content, filename=path, type_comments=True)
        except SyntaxError as exc:
            message = f"{exc.msg} at line {exc.lineno or 1}"
            return PythonFileAnalysis(
                path=path,
                module_name=module_name,
                content_hash=content_hash,
                parse_status="syntax_error",
                syntax_error=message[:500],
            )
        extractor = _Extractor(
            path,
            module_name,
            self.settings,
            total_lines=len(result.content.splitlines()),
        )
        try:
            extractor.visit(tree)
        except RecursionError:
            extractor.truncated = True
            extractor.notes.append("AST traversal stopped at the Python recursion limit.")
        notes = list(extractor.notes)
        node_count = extractor.visited_node_count
        truncated = extractor.truncated
        return PythonFileAnalysis(
            path=path,
            module_name=module_name,
            content_hash=content_hash,
            parse_status="truncated" if truncated else "parsed",
            symbols=extractor.symbols,
            imports=extractor.imports,
            inheritances=extractor.inheritances,
            calls=extractor.calls,
            references=extractor.references,
            node_count=node_count,
            truncated=truncated,
            truncation_notes=notes,
        )
