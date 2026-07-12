"""Source code indexer for ResQ.

Indexes local repositories and GitHub repositories for code analysis.
"""

import os
import re
import json
import requests
from pathlib import Path
from typing import Optional, List, Dict, Tuple


class SourceIndexer:
    """Indexes source code for agent analysis."""

    def __init__(
        self,
        local_path: Optional[str] = None,
        github_url: Optional[str] = None,
        github_token: Optional[str] = None,
    ):
        self.local_path = local_path or os.getenv("SOURCE_LOCAL_PATH")
        self.github_url = github_url or os.getenv("SOURCE_GITHUB_URL")
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.index: Dict[str, Dict] = {}

    def index_local_repo(self, path: Optional[str] = None, extensions: List[str] = None):
        """Index a local repository."""
        path = Path(path or self.local_path)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        extensions = extensions or [".py", ".js", ".ts", ".java", ".go", ".rb"]

        for file_path in path.rglob("*"):
            if file_path.is_file() and file_path.suffix in extensions:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    rel_path = str(file_path.relative_to(path))
                    self.index[rel_path] = {
                        "content": content,
                        "lines": content.split("\n"),
                        "functions": self._extract_functions(content, file_path.suffix),
                        "classes": self._extract_classes(content, file_path.suffix),
                    }
                except Exception as e:
                    print(f"Warning: Could not index {rel_path}: {e}")

    def index_github_repo(self, url: Optional[str] = None, branch: str = "main"):
        """Index a GitHub repository via API."""
        url = url or self.github_url
        if not url:
            raise ValueError("GitHub URL required")

        # Parse owner/repo from URL
        match = re.search(r"github\.com/([^/]+)/([^/]+)", url)
        if not match:
            raise ValueError(f"Invalid GitHub URL: {url}")

        owner, repo = match.groups()
        headers = {"Authorization": f"token {self.github_token}"} if self.github_token else {}

        # Get repo contents
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
            headers=headers,
        )
        response.raise_for_status()
        tree = response.json().get("tree", [])

        for item in tree:
            if item["type"] == "blob" and item["path"].endswith((".py", ".js", ".ts", ".java", ".go", ".rb")):
                try:
                    content_response = requests.get(item["url"], headers=headers)
                    content_response.raise_for_status()
                    content = content_response.json().get("content", "")
                    import base64
                    content = base64.b64decode(content).decode("utf-8", errors="ignore")

                    self.index[item["path"]] = {
                        "content": content,
                        "lines": content.split("\n"),
                        "functions": self._extract_functions(content, Path(item["path"]).suffix),
                        "classes": self._extract_classes(content, Path(item["path"]).suffix),
                    }
                except Exception as e:
                    print(f"Warning: Could not index {item['path']}: {e}")

    def _extract_functions(self, content: str, extension: str) -> List[Dict]:
        """Extract function definitions from code."""
        functions = []
        patterns = {
            ".py": r"def\s+(\w+)\s*\(([^)]*)\)\s*(->\s*[\w\[\],\s]+)?:",
            ".js": r"(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)",
            ".ts": r"(?:async\s+)?(?:function\s+)?(\w+)\s*\(([^)]*)\)\s*(?::\s*[\w\[\],\s<>]+)?(?:\s*=\s*(?:async\s+)?\([^)]*\)\s*=>)?",
            ".java": r"(?:public|private|protected)?\s*(?:static\s+)?(?:[\w<>\[\]]+)\s+(\w+)\s*\(([^)]*)\)",
            ".go": r"func\s+(?:\(\w+\s+[\w*]+\))?\s*(\w+)\s*\(([^)]*)\)",
            ".rb": r"def\s+(\w+)(?:\s*\(([^)]*)\))?",
        }

        pattern = patterns.get(extension)
        if not pattern:
            return functions

        for i, line in enumerate(content.split("\n"), 1):
            match = re.search(pattern, line)
            if match:
                functions.append({
                    "name": match.group(1),
                    "params": match.group(2) if match.group(2) else "",
                    "line": i,
                })

        return functions

    def _extract_classes(self, content: str, extension: str) -> List[Dict]:
        """Extract class definitions from code."""
        classes = []
        patterns = {
            ".py": r"class\s+(\w+)(?:\s*\(([^)]*)\))?:",
            ".js": r"class\s+(\w+)(?:\s+extends\s+(\w+))?",
            ".ts": r"(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?",
            ".java": r"(?:public|private|protected)?\s*(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?",
            ".go": r"type\s+(\w+)\s+struct",
            ".rb": r"class\s+(\w+)(?:\s*<\s*(\w+))?",
        }

        pattern = patterns.get(extension)
        if not pattern:
            return classes

        for i, line in enumerate(content.split("\n"), 1):
            match = re.search(pattern, line)
            if match:
                classes.append({
                    "name": match.group(1),
                    "parent": match.group(2) if match.group(2) else None,
                    "line": i,
                })

        return classes

    def get_code_at_line(self, file_path: str, line_number: int, context_lines: int = 5) -> str:
        """Get code around a specific line."""
        if file_path not in self.index:
            return f"File not indexed: {file_path}"

        file_data = self.index[file_path]
        lines = file_data["lines"]
        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)

        result = []
        for i in range(start, end):
            marker = " >>> " if i + 1 == line_number else "     "
            result.append(f"{marker}{i+1:4d}: {lines[i]}")

        return "\n".join(result)

    def find_function(self, file_path: str, function_name: str) -> Optional[Dict]:
        """Find a function in a file."""
        if file_path not in self.index:
            return None

        for func in self.index[file_path]["functions"]:
            if func["name"] == function_name:
                return func
        return None

    def search_code(self, pattern: str, file_pattern: Optional[str] = None) -> List[Dict]:
        """Search for a pattern in indexed code."""
        results = []
        regex = re.compile(pattern, re.IGNORECASE)

        for file_path, file_data in self.index.items():
            if file_pattern and not re.search(file_pattern, file_path):
                continue

            for i, line in enumerate(file_data["lines"], 1):
                if regex.search(line):
                    results.append({
                        "file": file_path,
                        "line": i,
                        "content": line.strip(),
                    })

        return results

    def get_file_summary(self, file_path: str) -> Optional[Dict]:
        """Get a summary of a file."""
        if file_path not in self.index:
            return None

        file_data = self.index[file_path]
        return {
            "path": file_path,
            "total_lines": len(file_data["lines"]),
            "functions": len(file_data["functions"]),
            "classes": len(file_data["classes"]),
            "function_names": [f["name"] for f in file_data["functions"]],
            "class_names": [c["name"] for c in file_data["classes"]],
        }
