"""Serializable Python AST and repository-map facts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Resolution = Literal["resolved", "inferred", "candidate", "ambiguous", "external", "unresolved"]
SymbolKind = Literal["module", "class", "function", "async_function", "method", "async_method"]
ReferenceKind = Literal["name", "attribute", "import", "call", "decorator", "base"]
RelationshipType = Literal["defines", "imports", "inherits", "calls", "references"]


class SourceSpan(BaseModel):
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    start_col: int = Field(default=0, ge=0)
    end_line: int = Field(ge=1)
    end_col: int = Field(default=0, ge=0)
    span_complete: bool = True

    @model_validator(mode="after")
    def validate_range(self) -> SourceSpan:
        if self.end_line < self.start_line:
            raise ValueError("SourceSpan end_line must not precede start_line.")
        if self.end_line == self.start_line and self.end_col < self.start_col:
            raise ValueError("SourceSpan end_col must not precede start_col on the same line.")
        return self


class SymbolRecord(BaseModel):
    symbol_id: str
    name: str
    qualified_name: str
    kind: SymbolKind
    module_name: str
    path: str
    span: SourceSpan
    parent_symbol_id: str | None = None
    parameters: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)
    docstring_summary: str | None = None
    is_async: bool = False
    is_nested: bool = False


class ImportRecord(BaseModel):
    import_id: str
    importer_module: str
    kind: Literal["import", "from_import"]
    module: str | None = None
    imported_name: str | None = None
    alias: str | None = None
    level: int = Field(default=0, ge=0)
    span: SourceSpan
    resolved_path: str | None = None
    resolved_module: str | None = None
    resolution: Resolution = "unresolved"


class InheritanceRecord(BaseModel):
    relationship_id: str
    subclass_symbol_id: str
    base_expression: str
    base_name: str | None = None
    resolved_base_symbol_id: str | None = None
    span: SourceSpan
    resolution: Resolution = "unresolved"


class CallSiteRecord(BaseModel):
    call_id: str
    caller_symbol_id: str
    callee_expression: str
    callee_name: str | None = None
    resolved_symbol_id: str | None = None
    span: SourceSpan
    resolution_strategy: str = "unresolved"
    resolution: Resolution = "unresolved"


class ReferenceRecord(BaseModel):
    reference_id: str
    symbol_name: str
    resolved_symbol_id: str | None = None
    reference_kind: ReferenceKind
    enclosing_symbol_id: str
    span: SourceSpan
    resolution: Resolution = "unresolved"


class PythonFileAnalysis(BaseModel):
    path: str
    module_name: str
    content_hash: str
    parse_status: Literal["parsed", "syntax_error", "skipped", "truncated"]
    syntax_error: str | None = None
    symbols: list[SymbolRecord] = Field(default_factory=list)
    imports: list[ImportRecord] = Field(default_factory=list)
    inheritances: list[InheritanceRecord] = Field(default_factory=list)
    calls: list[CallSiteRecord] = Field(default_factory=list)
    references: list[ReferenceRecord] = Field(default_factory=list)
    node_count: int = Field(default=0, ge=0)
    truncated: bool = False
    truncation_notes: list[str] = Field(default_factory=list)


class RepositoryMapEdge(BaseModel):
    relationship_id: str
    relationship_type: RelationshipType
    source_id: str
    target_id: str | None = None
    target_expression: str | None = None
    span: SourceSpan
    resolution: Resolution = "unresolved"


class RepositoryMapSnapshot(BaseModel):
    repository_commit: str
    indexed_files: list[str] = Field(default_factory=list)
    nodes: list[SymbolRecord] = Field(default_factory=list)
    edges: list[RepositoryMapEdge] = Field(default_factory=list)
    parse_errors: dict[str, str] = Field(default_factory=dict)
    truncated: bool = False
    truncation_notes: list[str] = Field(default_factory=list)
