#!/usr/bin/env python3
"""Create a private local Compose environment file without displaying keys."""

import argparse
import os
import secrets
import sys
from pathlib import Path


def token_count(value):
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('count must be an integer from 1 to 20') from None
    if not 1 <= count <= 20:
        raise argparse.ArgumentTypeError('count must be an integer from 1 to 20')
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new environment file path')
    parser.add_argument('--count', type=token_count, default=1, help='number of tester keys (1–20)')
    arguments = parser.parse_args()

    # O_EXCL refuses regular files and symlinks, including dangling symlinks.
    try:
        descriptor = os.open(arguments.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        print('Could not create token file; choose a new output path in an existing directory.',
              file=sys.stderr)
        return 1

    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
            os.fchmod(output.fileno(), 0o600)
            tokens = ','.join(secrets.token_urlsafe(32) for _ in range(arguments.count))
            output.write('BACKEND_PORT=8080\nSUBWAY_API_TOKENS=' + tokens + '\n')
    except OSError:
        print('Could not write token file; check the private file and choose a new output path.',
              file=sys.stderr)
        return 1

    print(arguments.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
