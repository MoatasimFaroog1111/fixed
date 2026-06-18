"""Shared fixtures for the test suite."""
import sys
import os

# Ensure the project root is on the path so tests can import modules directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
