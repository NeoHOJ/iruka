import pprint
import re
from functools import partial

from google.protobuf import text_format


ANSI_CODE_CRE = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')


_pp = pprint.PrettyPrinter(indent=2)
pformat = _pp.pformat
del _pp


def pformat_pb(message, max_level=None, as_utf8=False, *args, **kwargs):

    def _oneline_formatter(message):
        return text_format.MessageToString(
            message,
            *args,
            **kwargs,
            as_utf8=as_utf8,
            as_one_line=True,
            message_formatter=None)

    def _monkey_PrintMessage(_dfl_fn, _self, message):
        if (max_level is not None) and (_self.indent // 2 > max_level):
            _self.out.write(' ' * _self.indent)
            _self.out.write(_oneline_formatter(message))
            _self.out.write('\n')
            return
        return _dfl_fn(message)

    if max_level == 0:
        result = _oneline_formatter(message)
    else:
        out = text_format.TextWriter(as_utf8)
        printer = text_format._Printer(
            out,
            *args,
            **kwargs,
            as_utf8=as_utf8,
            indent=2)

        printer.PrintMessage = partial(
            _monkey_PrintMessage,
            printer.PrintMessage, printer)
        printer.PrintMessage(message)
        result = out.getvalue()
        out.close()

        result = '\n' + result

    return '<Protobuf {{{}}}>'.format(result)
