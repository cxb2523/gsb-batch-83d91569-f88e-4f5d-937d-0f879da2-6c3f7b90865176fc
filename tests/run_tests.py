#!/usr/bin/env python3
"""
Test runner for Olostep SDK tests.

Supports three test modes:
- local: Unit tests only (no API calls) - DEFAULT
- full: All tests including API integration tests (requires valid API key)
- contracts: Massive API contract test suite only (ignores client code)
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def check_api_key() -> bool:
    """Check if a valid API key is available."""
    api_key = os.getenv("OLOSTEP_API_KEY")
    return bool(api_key and api_key.strip())


def run_local_tests(project_root: Path, extra_args: list[str]) -> int:
    """Run local unit tests (no API calls)."""
    test_dirs = [
        "tests/unit",
        "tests/self_tests", 
        "tests/stubs"
    ]
    
    cmd = ["python", "-m", "pytest"]
    
    # Add test directories
    for test_dir in test_dirs:
        cmd.append(str(project_root / test_dir))
    
    # Add markers to exclude API-dependent tests
    cmd.extend([
        "-m", "not api and not integration",
        "-v",
        "--tb=short",
        "--strict-markers",
        "--disable-warnings",
    ])
    
    cmd.extend(extra_args)
    
    print("Running LOCAL tests (unit tests only, no API calls)")
    print(f"Command: {' '.join(cmd)}")
    print("-" * 60)
    
    return subprocess.run(cmd, cwd=project_root).returncode


def run_full_tests(project_root: Path, extra_args: list[str]) -> int:
    """Run all tests including API integration tests."""
    if not check_api_key():
        print("ERROR: OLOSTEP_API_KEY environment variable not set!")
        print("Full test mode requires a valid, charged API key.")
        return 1
    
    test_dirs = [
        "tests/unit",
        "tests/self_tests", 
        "tests/stubs",
        "tests/api_contracts"
    ]
    
    cmd = ["python", "-m", "pytest"]
    
    # Add test directories
    for test_dir in test_dirs:
        cmd.append(str(project_root / test_dir))
    
    # Include all tests
    cmd.extend([
        "-v",
        "--tb=short",
        "--strict-markers",
        "--disable-warnings",
    ])
    
    cmd.extend(extra_args)
    
    print("Running FULL tests (all tests including API integration)")
    print(f"Command: {' '.join(cmd)}")
    print("-" * 60)
    
    return subprocess.run(cmd, cwd=project_root).returncode


def run_contracts_tests(project_root: Path, extra_args: list[str]) -> int:
    """Run API contract tests from as_is folder with parallel execution."""
    if not check_api_key():
        print("ERROR: OLOSTEP_API_KEY environment variable not set!")
        print("Contracts test mode requires a valid, charged API key.")
        return 1
    
    cmd = ["python", "-m", "pytest"]
    
    # Run tests from as_is folder
    cmd.append(str(project_root / "tests/api_contracts/as_is"))
    
    # Add parallel execution and other options
    cmd.extend([
        "-n", "32",  # Run with 32 parallel workers
        "-v",
        "--tb=short",
        "--strict-markers",
        "--disable-warnings",
    ])
    
    cmd.extend(extra_args)
    
    print("🚀 Running CONTRACTS tests (as_is folder)")
    print("=" * 60)
    print("📁 Test directory: tests/api_contracts/as_is/")
    print("🏷️  Filter: All tests in as_is folder")
    print("⚡ Parallel workers: 32")
    print(f"🔑 API Key: {'✅ Set' if check_api_key() else '❌ Missing'}")
    print("=" * 60)
    print(f"Command: {' '.join(cmd)}")
    print("=" * 60)
    
    return subprocess.run(cmd, cwd=project_root).returncode


def run_bugs_tests(project_root: Path, extra_args: list[str]) -> int:
    """Run API bug tests from as_should_be folder."""
    if not check_api_key():
        print("ERROR: OLOSTEP_API_KEY environment variable not set!")
        print("Bugs test mode requires a valid, charged API key.")
        return 1
    
    cmd = ["python", "-m", "pytest"]
    
    # Run tests from as_should_be folder
    cmd.append(str(project_root / "tests/api_contracts/as_should_be"))
    
    # Add parallel execution and other options
    cmd.extend([
        "-n", "32",  # Run with 32 parallel workers
        "-v",
        "--tb=short",
        "--strict-markers",
        "--disable-warnings",
    ])
    
    cmd.extend(extra_args)
    
    print("🐛 Running BUGS tests (as_should_be folder)")
    print("=" * 60)
    print("📁 Test directory: tests/api_contracts/as_should_be/")
    print("🏷️  Filter: All tests in as_should_be folder")
    print("⚡ Parallel workers: 32")
    print(f"🔑 API Key: {'✅ Set' if check_api_key() else '❌ Missing'}")
    print("=" * 60)
    print(f"Command: {' '.join(cmd)}")
    print("=" * 60)
    
    return subprocess.run(cmd, cwd=project_root).returncode


def main() -> int:
    """Main test runner with mode selection."""
    parser = argparse.ArgumentParser(
        description="Run Olostep SDK tests in different modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test Modes:
  local      Unit tests only (no API calls) - DEFAULT
  full       All tests including API integration (requires API key)
  contracts  API contract tests from as_is folder with 32 parallel workers (requires API key)
  bugs       API bug tests from as_should_be folder with 32 parallel workers (requires API key)

Examples:
  python tests/run_tests.py                    # Run local tests
  python tests/run_tests.py local              # Run local tests
  python tests/run_tests.py full               # Run all tests
  python tests/run_tests.py contracts          # Run API contract tests with 32 workers
  python tests/run_tests.py bugs               # Run API bug tests with 32 workers
  python tests/run_tests.py local -k "test_scrape"  # Run specific local tests
        """
    )
    
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["local", "full", "contracts", "bugs"],
        default="local",
        help="Test mode to run (default: local)"
    )
    
    # Parse known args to separate mode from pytest args
    args, extra_args = parser.parse_known_args()
    
    project_root = Path(__file__).parent.parent
    
    if args.mode == "local":
        return run_local_tests(project_root, extra_args)
    elif args.mode == "full":
        return run_full_tests(project_root, extra_args)
    elif args.mode == "contracts":
        return run_contracts_tests(project_root, extra_args)
    elif args.mode == "bugs":
        return run_bugs_tests(project_root, extra_args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
