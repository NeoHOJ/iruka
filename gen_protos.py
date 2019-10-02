#!/usr/bin/env python3
import os
import sys
from pathlib import Path

import pkg_resources
from grpc_tools import protoc


PROTO_WKT_PATH = pkg_resources.resource_filename('grpc_tools', '_proto')

GRPC_SRCS = [
    'iruka_rpc.proto',
    'iruka_admin.proto',
]

if __name__ == '__main__':
    base_path = Path(__file__).parent.absolute()
    client_path = base_path.parent / 'iruka_client'
    src_base = client_path / 'iruka/protos'
    protos = [str(src.relative_to(client_path)) for src in src_base.glob('*.proto')]

    if not protos:
        print('Unable to find any proto defs!', file=sys.stderr)
        sys.exit(1)

    os.chdir(client_path)

    leading_args = (
        '',
        '-I.',
        '-I{}'.format(PROTO_WKT_PATH))

    protoc.main((
        *leading_args,
        '--python_out=.',
        '--mypy_out=quiet:.',
        *protos,
    ))

    protoc.main((
        *leading_args,
        '--grpc_python_out=.',
        *(str(Path('iruka/protos') / src) for src in GRPC_SRCS),
    ))
