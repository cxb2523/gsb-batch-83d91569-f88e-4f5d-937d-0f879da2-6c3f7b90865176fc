from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "render_codex_agent.py"


class RenderCodexAgentTests(unittest.TestCase):
    def test_renderer_emits_valid_codex_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "demo.md"
            output = root / "demo.toml"
            source.write_text(
                textwrap.dedent(
                    """\
                    ---
                    name: demo-agent
                    description: Handles quoted "examples" safely.
                    tools: Read, Bash
                    ---

                    You are a focused demo agent.
                    """
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(source), str(output)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            parsed = tomllib.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(parsed["name"], "demo-agent")
            self.assertEqual(parsed["description"], 'Handles quoted "examples" safely.')
            self.assertIn("focused demo agent", parsed["developer_instructions"])
            self.assertNotIn("tools", parsed)

    def test_all_repository_agents_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            for source in sorted((REPO_ROOT / "agents").glob("*.md")):
                output = output_dir / f"{source.stem}.toml"
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(source), str(output)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, f"{source}: {result.stderr}")
                tomllib.loads(output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
