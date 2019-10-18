#!/usr/bin/env python3

import logging
import os
import re
import sys
from os import path

# from google.protobuf.wrappers_pb2 import Int64Value

# cwd = path.dirname(path.realpath(__file__))
# sys.path.append(path.join(cwd, '..'))

from ..protos import (common_pb2, checker_io_pb2)


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('checkers.tolerant_diff')

def strip_eol(s):
    last = -1
    while s and (s[last] in ('\r', '\n')):
        last -= 1
    return s[:last]


def tolerant_diff_at(fa, fb):
    line = 0
    while True:
        la, lb = fa.readline(), fb.readline()
        if la:
            if not lb or strip_eol(la.strip()) != strip_eol(lb.strip()): return line
        elif lb:
            return line
        else:
            break
        line += 1
    return -1

def main(checker_input):
    pathOut = checker_input.path_outfile
    pathOut_user = checker_input.path_out_user
    context = checker_input.context


    fOut_user = open(pathOut_user, 'r')
    fOut = open(pathOut, 'r')

    fOut_user = open(pathOut_user, 'r')
    fOut = open(pathOut, 'r')
    diffResult = tolerant_diff_at(fOut_user, fOut)
    fOut_user.close()
    fOut.close()

    f1 = open(pathOut_user, 'r')
    f2 = open(pathOut, 'r')

    if diffResult >= 0:
        logger.debug('Rejected - Line #{} differs'.format(diffResult + 1))
    else:
        logger.debug('Accepted - No differences found')

    output = checker_io_pb2.CheckerOutput()
    # output.meta['lineno'].Pack(Int64Value(value=diffResult + 1))

    if context.stat.verdict == 0:
        if diffResult >= 0:
            output.verdict = common_pb2.WA
        else:
            output.verdict = common_pb2.AC

    return output


# writing an interface for debugging is extremely helpful
# but not absolutely necessary
if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python -m {} out out_user'.format(__spec__.name))
        sys.exit(1)

    inp = checker_io_pb2.CheckerInput(
        path_infile='__not_provided__',
        path_outfile=sys.argv[1],
        path_out_user=sys.argv[2])

    cxtOut = main(inp)

    from google.protobuf import text_format

    print('---  # checker output')
    print(text_format.MessageToString(cxtOut)[:-1])
    print('---')
