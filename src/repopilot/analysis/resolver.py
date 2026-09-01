"""Conservative resolver for unambiguous repository-local Python relationships."""

from __future__ import annotations

from repopilot.analysis.models import PythonFileAnalysis, SymbolRecord
from repopilot.analysis.module_index import ModuleIndex


def _relative_module(importer: str, module: str | None, level: int, *, is_package: bool) -> str:
    if level == 0:
        return module or ""
    package = importer.split(".") if is_package else importer.split(".")[:-1]
    keep = max(len(package) - (level - 1), 0)
    prefix = package[:keep]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


class SymbolResolver:
    def __init__(self, module_index: ModuleIndex) -> None:
        self.module_index = module_index

    def resolve(
        self,
        analysis: PythonFileAnalysis,
        known_symbols: list[SymbolRecord],
    ) -> PythonFileAnalysis:
        resolved = analysis.model_copy(deep=True)
        symbols_by_id = {item.symbol_id: item for item in known_symbols}
        symbols_by_id.update({item.symbol_id: item for item in resolved.symbols})
        symbols = list(symbols_by_id.values())
        by_name: dict[str, list[SymbolRecord]] = {}
        by_id = {item.symbol_id: item for item in symbols}
        for symbol in symbols:
            by_name.setdefault(symbol.name, []).append(symbol)

        import_bindings: dict[str, tuple[str, str | None]] = {}
        for import_record in resolved.imports:
            module_name = _relative_module(
                resolved.module_name,
                import_record.module,
                import_record.level,
                is_package=resolved.path.endswith("/__init__.py") or resolved.path == "__init__.py",
            )
            if import_record.kind == "import":
                module_name = import_record.module or ""
                binding = import_record.alias or module_name.split(".", 1)[0]
            else:
                binding = import_record.alias or import_record.imported_name or ""
            path, status = self.module_index.resolve_module(module_name)
            import_record.resolved_module = module_name or None
            import_record.resolved_path = path
            import_record.resolution = status
            import_bindings[binding] = (module_name, import_record.imported_name)

        for inheritance in resolved.inheritances:
            base_name = inheritance.base_name or ""
            imported_base = import_bindings.get(base_name)
            if imported_base:
                imported_module, imported_name = imported_base
                base_candidates = [
                    symbol
                    for symbol in symbols
                    if symbol.module_name == imported_module
                    and symbol.name == (imported_name or base_name)
                ]
            else:
                base_candidates = [
                    symbol
                    for symbol in by_name.get(base_name, [])
                    if symbol.module_name == resolved.module_name
                ]
            if len(base_candidates) == 1:
                inheritance.resolved_base_symbol_id = base_candidates[0].symbol_id
                inheritance.resolution = "resolved"
            elif len(base_candidates) > 1:
                inheritance.resolution = "ambiguous"

        for call in resolved.calls:
            expression = call.callee_expression
            call_candidates: list[SymbolRecord] = []
            strategy = "unresolved"
            if "." not in expression and call.callee_name:
                imported_call = import_bindings.get(expression)
                if imported_call:
                    imported_module, imported_name = imported_call
                    call_candidates = [
                        symbol
                        for symbol in symbols
                        if symbol.module_name == imported_module
                        and symbol.name == (imported_name or expression)
                    ]
                    strategy = "import_binding"
                else:
                    call_candidates = [
                        symbol
                        for symbol in by_name.get(call.callee_name, [])
                        if symbol.module_name == resolved.module_name
                    ]
                    strategy = "same_module_name"
            elif expression.startswith(("self.", "cls.")) and call.callee_name:
                caller = by_id.get(call.caller_symbol_id)
                if caller and "." in caller.qualified_name:
                    class_name = caller.qualified_name.rsplit(".", 1)[0]
                    call_candidates = [
                        item
                        for item in symbols
                        if item.module_name == caller.module_name
                        and item.qualified_name == f"{class_name}.{call.callee_name}"
                    ]
                strategy = "self_method" if expression.startswith("self.") else "cls_method"
            elif "." in expression:
                binding, attribute = expression.split(".", 1)
                imported = import_bindings.get(binding)
                if imported:
                    module_name, imported_name = imported
                    target_name = attribute.rsplit(".", 1)[-1]
                    if imported_name and attribute == imported_name:
                        target_name = imported_name
                    call_candidates = [
                        item
                        for item in symbols
                        if item.module_name == module_name and item.name == target_name
                    ]
                    strategy = "import_alias"
            if len(call_candidates) == 1:
                call.resolved_symbol_id = call_candidates[0].symbol_id
                call.resolution = "resolved"
                call.resolution_strategy = (
                    "constructor" if call_candidates[0].kind == "class" else strategy
                )
            elif len(call_candidates) > 1:
                call.resolution = "ambiguous"
                call.resolution_strategy = strategy

        for reference in resolved.references:
            imported_reference = import_bindings.get(reference.symbol_name)
            if imported_reference:
                imported_module, imported_name = imported_reference
                reference_candidates = [
                    symbol
                    for symbol in symbols
                    if symbol.module_name == imported_module
                    and symbol.name == (imported_name or reference.symbol_name)
                ]
            else:
                reference_candidates = [
                    symbol
                    for symbol in by_name.get(reference.symbol_name, [])
                    if symbol.module_name == resolved.module_name
                ]
            if len(reference_candidates) == 1:
                reference.resolved_symbol_id = reference_candidates[0].symbol_id
                reference.resolution = "resolved"
            elif len(reference_candidates) > 1:
                reference.resolution = "ambiguous"
            else:
                reference.resolution = "candidate"
        return resolved
