'''Inspired from
1. https://codereview.stackexchange.com/a/17959/188792,
2. DMOJ: https://github.com/DMOJ,
3. CPython subprocess library:
     https://github.com/python/cpython/blob/3.6/Lib/subprocess.py.
'''

import contextlib
import io
import os
import queue
import selectors
import subprocess
import threading
from time import monotonic as _time

from subprocess import (_mswindows, Popen, TimeoutExpired, CalledProcessError,
                        CompletedProcess)

if _mswindows:
    pass
else:
    from subprocess import (_PIPE_BUF, _PopenSelector)

# default pipe buffer size is 16 pages
PIPE_BUFFER_SIZE = 4096 * 16


class _Popen(Popen):
    def __init__(self, *args, pipe_stdout=None, pipe_stderr=None, **kwargs):
        self.is_ole = [False] * 2
        self._fd2dest = {}
        self._fd2limit = {}
        self._fd2length = {}

        if pipe_stdout is not None:
            if 'stdout' in kwargs:
                raise ValueError(
                    'piped and regular stdout may not both be used.')
            kwargs['stdout'] = subprocess.PIPE
        if pipe_stderr is not None:
            if 'stderr' in kwargs:
                raise ValueError(
                    'piped and regular stderr may not both be used.')
            kwargs['stderr'] = subprocess.PIPE

        super(_Popen, self).__init__(*args, **kwargs)

        fd_out = self.stdout.fileno() if self.stdout else None
        fd_err = self.stderr.fileno() if self.stderr else None

        self._fd2length[fd_out] = 0
        self._fd2length[fd_err] = 0

        if pipe_stdout is not None:
            self._fd2dest[fd_out], self._fd2limit[fd_out] = pipe_stdout
        if pipe_stderr is not None:
            self._fd2dest[fd_err], self._fd2limit[fd_err] = pipe_stderr

    def communicate(self, input=None, timeout=None):
        '''Modified from CPython 3.6: subprocess.communicate
        '''
        if self._communication_started and input:
            raise ValueError("Cannot send input after starting communication")

        # Optimization: If we are not worried about timeouts, we haven't
        # started communicating, and we have one or zero pipes, using select()
        # or threads is unnecessary.
        if (timeout is None and not self._communication_started
                and [self.stdin, self.stdout, self.stderr].count(None) >= 2):
            stdout = None
            stderr = None
            if self.stdin:
                self._stdin_write(input)
            elif self.stdout:
                if self.stdout.fileno() in self._fd2dest:
                    stdout, ole = self._sync_all(self.stdout.fileno())
                    if ole:
                        self.is_ole[0] = True
                else:
                    stdout = self.stdout.read()
                self.stdout.close()
            elif self.stderr:
                if self.stderr.fileno() in self._fd2dest:
                    stderr, ole = self._sync_all(self.stderr.fileno())
                    if ole:
                        self.is_ole[1] = True
                else:
                    stderr = self.stderr.read()
                self.stderr.close()
            self.wait()
        else:
            if timeout is not None:
                endtime = _time() + timeout
            else:
                endtime = None

            try:
                stdout, stderr = self._communicate(input, endtime, timeout)
            finally:
                self._communication_started = True

            sts = self.wait(timeout=self._remaining_time(endtime))

        return (stdout, stderr)

    def _communicate(self, input, endtime, orig_timeout):
        '''Modified from CPython 3.6: subprocess._communicate
        Only POSIX version here. Windows version is WIP
        '''
        if _mswindows:
            raise NotImplementedError(
                '_communicate for Windows is not supported yet')

        if self.stdin and not self._communication_started:
            # Flush stdio buffer.  This might block, if the user has
            # been writing to .stdin in an uncontrolled fashion.
            try:
                self.stdin.flush()
            except BrokenPipeError:
                pass  # communicate() must ignore BrokenPipeError.
            if not input:
                try:
                    self.stdin.close()
                except BrokenPipeError:
                    pass  # communicate() must ignore BrokenPipeError.

        stdout = None
        stderr = None

        # Only create this mapping if we haven't already.
        if not self._communication_started:
            self._fd2output = {}
            if self.stdout:
                self._fd2output[self.stdout] = []
            if self.stderr:
                self._fd2output[self.stderr] = []

        if self.stdout:
            stdout = self._fd2output[self.stdout]
        if self.stderr:
            stderr = self._fd2output[self.stderr]

        self._save_input(input)

        if self._input:
            input_view = memoryview(self._input)

        with _PopenSelector() as selector:
            if self.stdin and input:
                selector.register(self.stdin, selectors.EVENT_WRITE)
            if self.stdout:
                selector.register(self.stdout, selectors.EVENT_READ)
            if self.stderr:
                selector.register(self.stderr, selectors.EVENT_READ)

            while selector.get_map():
                timeout = self._remaining_time(endtime)
                if timeout is not None and timeout < 0:
                    raise TimeoutExpired(self.args, orig_timeout)

                ready = selector.select(timeout)
                self._check_timeout(endtime, orig_timeout)

                # XXX Rewrite these to use non-blocking I/O on the file
                # objects; they are no longer using C stdio!

                for key, events in ready:
                    if key.fileobj is self.stdin:
                        chunk = input_view[self._input_offset:self.
                                           _input_offset + _PIPE_BUF]
                        try:
                            self._input_offset += os.write(key.fd, chunk)
                        except BrokenPipeError:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                        else:
                            if self._input_offset >= len(self._input):
                                selector.unregister(key.fileobj)
                                key.fileobj.close()
                    elif key.fileobj in (self.stdout, self.stderr):
                        if key.fileobj.fileno() in self._fd2dest:
                            # added impl.
                            sz = self._sync_once(key.fd)
                            if sz < 0:
                                self.is_ole[(self.stdout, self.stderr).index(
                                    key.fileobj)] = True
                            if sz <= 0:
                                selector.unregister(key.fileobj)
                                key.fileobj.close()
                        else:
                            data = os.read(key.fd, 32768)
                            if not data:
                                selector.unregister(key.fileobj)
                                key.fileobj.close()
                            self._fd2output[key.fileobj].append(data)

        self.wait(timeout=self._remaining_time(endtime))

        # All data exchanged.  Translate lists into strings.
        if stdout is not None:
            stdout = b''.join(stdout)
        if stderr is not None:
            stderr = b''.join(stderr)

        # Translate newlines, if requested.
        # This also turns bytes into strings.
        if self._text_mode:
            if stdout is not None:
                stdout = self._translate_newlines(stdout, self.stdout.encoding,
                                                  self.stdout.errors)
            if stderr is not None:
                stderr = self._translate_newlines(stderr, self.stderr.encoding,
                                                  self.stderr.errors)

        return (stdout, stderr)

    @property
    def _text_mode(self):
        try:
            return getattr(self, 'text_mode')
        except:
            # mock Python 3.7 behavior for 3.6
            # see Popen.__init__: text_mode = encoding or errors or universal_newlines
            return self.encoding or self.errors or self.universal_newlines

    def _sync_all(self, fd, buffer_size=PIPE_BUFFER_SIZE):
        ole = False

        ntotal = 0
        while True:
            szr = self._sync_once(fd, buffer_size=buffer_size)
            if szr < 0:
                ole = True
                break
            elif szr == 0:
                break
            ntotal += szr

        return ntotal, ole

    def _sync_once(self, fd, buffer_size=PIPE_BUFFER_SIZE):
        dest = self._fd2dest[fd]
        limit = self._fd2limit[fd]
        length_read = self._fd2length[fd]

        if limit is None or limit < 0:
            sz = buffer_size
        else:
            sz = min(buffer_size, limit - length_read)

        buf = os.read(fd, sz)
        # print(f'sync ({sz}/{limit}): [{buf}], rem {limit - length_read}')

        if sz != 0 and not buf:  # EOF
            return 0
        if sz == 0 and os.read(fd, 1):
            # read returning, meaning not EOF yet,
            # which means exceeding the max_size limit
            return -1
        szr = len(buf)
        self._fd2length[fd] += szr

        dest.write(buf)
        return szr


def run_with_pipes(*popenargs, input=None, timeout=None, check=False,
                   **kwargs):
    '''Only replace _Popen with the above implementation. The logic is the same
    as subprocess.run
    '''
    if input is not None:
        if 'stdin' in kwargs:
            raise ValueError('stdin and input arguments may not both be used.')
        kwargs['stdin'] = PIPE

    with _Popen(*popenargs, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            raise TimeoutExpired(
                process.args, timeout, output=stdout, stderr=stderr)
        except:
            process.kill()
            process.wait()
            raise
        retcode = process.poll()
        if check and retcode:
            raise CalledProcessError(
                retcode, process.args, output=stdout, stderr=stderr)
    # to include OLE information
    ret = CompletedProcess(process.args, retcode, stdout,
                            stderr)
    ole1, ole2 = process.is_ole
    ret._ole_stdout = ole1
    ret._ole_stderr = ole2
    return ret


class JournalPipe(object):
    def __init__(self, file):
        self.file = file
        self.text_mode = None

        self._reset_state()

        # auto-detect whether text mode should be used
        if isinstance(file, io.TextIOBase):
            self.text_mode = True
        else:
            self.text_mode = False

        # str -> (offs, len)
        self.tag_map = {}
        self._start_offset = self._offset

    def _reset_state(self):
        self._offset = self.file.seek(0, io.SEEK_CUR)
        self._length = 0
        self.active = False
        self._active_tag = None

    def mark(self, tag):
        if self._active_tag is not None:
            # consider replacing it with a lock
            raise Exception('Pipe is still in use. Call JournalPipe.mark_end()'
                            + ' first before starting another task.')
        if tag is None:
            raise ValueError('No tag is specified.')

        self._active_tag = tag
        self.active = True

    def mark_end(self):
        if not self._active_tag:
            raise Exception('No active tag to mark_end.')
        self.tag_map[self._active_tag] = (self._offset, self._length)
        self._reset_state()

    def write(self, buf):
        if self.text_mode:
            self.file.write(buf.decode())
        else:
            self.file.write(buf)
        self._length += len(buf)

    def dump(self, tag):
        _conf = self.tag_map.get(tag, None)
        if _conf is None:
            raise ValueError('Undefined tag "{}"'.format(tag))
        offs, length = _conf
        offs_orig = self.file.seek(0, io.SEEK_CUR)
        self.file.seek(offs, io.SEEK_SET)
        buf = self.file.read(length)
        self.file.seek(offs_orig, io.SEEK_SET)
        return buf

    def dump_all(self):
        offs_orig = self.file.seek(0, io.SEEK_CUR)
        ret = []
        # assumes the enumeration order is as key creation order
        for name, (offs, length) in self.tag_map.items():
            self.file.seek(offs, io.SEEK_SET)
            ret.append((name, self.file.read(length)))
        self.file.seek(offs_orig, io.SEEK_SET)
        return ret

    def _read(self):
        offs_orig = self.file.seek(0, io.SEEK_CUR)
        self.file.seek(offs_orig - self._length, io.SEEK_SET)
        buf = self.file.read(self._length)
        return buf


class Journals(object):
    def __init__(self, *files):
        self._journals = tuple(map(JournalPipe, files))

    def __getitem__(self, idx):
        return self._journals[idx]

    def mark(self, *tags):
        for j, tag in zip(self._journals, tags):
            if tag:
                j.mark(tag)

    def mark_end(self):
        for j in self._journals:
            if j.active:
                j.mark_end()

    @contextlib.contextmanager
    def start(self, tag):
        try:
            self.mark(*([tag] * len(self._journals)))
            yield self
        finally:
            self.mark_end()
