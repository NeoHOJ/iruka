#!/usr/bin/env python3
import io
import os

from iruka.cli import (loadConfig)
from iruka.utils.pipes import (_Popen, run_with_pipes)


config = loadConfig()
print(config.nsjail_path)

mockStdout = io.BytesIO()
mockStderr = io.BytesIO()

subp = run_with_pipes([config.nsjail_path],
    pipe_stdout=(mockStdout, None),
    pipe_stderr=(mockStderr, 128))

print(mockStdout.getvalue())
print(mockStderr.getvalue())

print('Stderr OLE?', subp._ole_stderr)
