#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local wrapper for run_migrations.py with Windows encoding fix
"""

import sys
import os

# Fix Windows console encoding before importing anything else
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add the scripts directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Import and run the main migration script
from run_migrations import main

if __name__ == "__main__":
    main()
