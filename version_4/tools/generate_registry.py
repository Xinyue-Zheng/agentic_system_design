import ast, json
from pathlib import Path

def extract_tools(filepath: str) -> list:
    source = Path(filepath).read_text()
    tree = ast.parse(source)
    tools = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        docstring = ast.get_docstring(node) or ""
        params = {}
        for arg in node.args.args:
            annotation = ""
            if arg.annotation:
                annotation = ast.unparse(arg.annotation)
            params[arg.arg] = annotation
        # Remove 'self' if present
        params.pop("self", None)
        tools.append({
            "name": node.name,
            "description": docstring,
            "params": params,
            "module": "tools.computation_tools"
        })
    return tools

if __name__ == "__main__":
    tools = extract_tools("tools/computation_tools.py")
    registry = {"computation_tools": tools}
    out = Path("tools/registry.json")
    out.write_text(json.dumps(registry, indent=2))
    print(f"Registry generated: {len(tools)} tools → {out}")
    for t in tools:
        print(f"  - {t['name']}")
