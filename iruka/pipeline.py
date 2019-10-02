import importlib
import logging
import math
import os
import re
import resource
import shlex
import subprocess
import tempfile
from pathlib import Path

from colors import color

from iruka.common.utils import pformat
from iruka.exceptions import IrukaInternalError
from iruka.utils.pipes import (_Popen, run_with_pipes, Journals)
from iruka.utils.timer import Timer
from iruka.protos import (iruka_rpc_pb2, subtask_pb2, checker_io_pb2, common_pb2)


def _ctx_quote_if_not_empty(context: dict):
    return { k: shlex.quote(v) if v else '' for k, v in context.items() }


class JudgePipeline(object):
    def __init__(self, spec, config, *,
                 logger=None, log1=None, log2=None,
                 nsjail_cfg_path):
        self.spec = spec
        self.nsjail_path = config.nsjail_path
        self.nsjail_cfg_path = nsjail_cfg_path

        self.cwd_build = Path('/run/shm')

        self.BUILD_OUT_LIM = 128 * 1024
        self.BUILD_MEM_LIM = 256 * 1024 * 1024
        self.RUN_OUT_LIM = 64 * 1024 * 1024
        self.USEROUT_PATH = '/run/shm/judge/out'

        # self.current_group = None
        # self.current_group_index = -1
        # self.current_subtask = None
        # self.current_subtask_index = -1

        self.logger = logger
        if logger is None:
            self.logger = logging.getLogger(type(self).__name__)

        # populate some structures
        # no's are all 1-indexed; no=0 is reserved for special semantics (usually none)

        _tasks = [(0, spec.samples)]
        st_iter = iter(spec.subtasks)
        for i, (count, _) in enumerate(spec.task_groups):
            _tasks.append((i+1, [next(st_iter) for _ in range(count)]))
        # _tasks.extend([(i+1, s) for i, s in enumerate()])
        self.tasks = _tasks

        self.logger.debug('tasks %s', pformat(_tasks))

        # prepare logging facilities
        self.logfile_stdout = log1
        self.logfile_stderr = log2
        self.journals = Journals(self.logfile_stdout, self.logfile_stderr)

        self.user_temp = None
        self._reset_state()

    def __del__(self):
        self._reset_state()

    def pl_build(self, src, output, *, context: dict={}):
        # TODO: different preset
        cmdline_tpl = 'g++ -Wall -O2 -fdiagnostics-color=always {CFLAGS} -o {output} {src}'
        # shlex over string template is silly and dangerous
        # hopefully these interpolated strings are hardcoded for now :)
        context_quoted = _ctx_quote_if_not_empty(context)
        compile_cmdline = cmdline_tpl.format(src=src, output=output, **context_quoted)
        compile_cmd = shlex.split(compile_cmdline)

        self.logger.info('Running command: %r', compile_cmd)

        # TODO: also confine the building process in the jail (should be chrooted)
        def preexec():
            lim = self.BUILD_MEM_LIM
            resource.setrlimit(resource.RLIMIT_AS, (lim, lim))

        with Timer() as t:
            # Here we trust the compiler's output is well-formed
            with self.journals.start('COMPILE') as (j1, j2):
                subp = run_with_pipes(compile_cmd,
                    cwd=self.cwd_build,
                    preexec_fn=preexec,
                    universal_newlines=True,
                    pipe_stdout=(j1, self.BUILD_OUT_LIM),
                    pipe_stderr=(j2, self.BUILD_OUT_LIM))

            self.build_ole_stdout = subp._ole_stdout
            self.build_ole_stderr = subp._ole_stderr

            print(subp)

        self.logger.info("Build finished after %dms", t.duration * 1000)

        return (subp.returncode == 0)

    def pl_run(self, subtask, infile_path, *, cwd, exec, context:dict={}):
        cmdline_args_tpl = (
            '-C {nsjail_cfg_path} -D {cwd} '
            '-t {time} --cgroup_mem_max {mem} --log_fd {log_fd} '
            '{nsjail_args}')

        log_file = tempfile.TemporaryFile()
        log_fd = log_file.fileno()

        gidx, task_spec = subtask

        cmdline_args = cmdline_args_tpl.format(
            cwd=shlex.quote(cwd),
            time=math.ceil(task_spec.time_limit / 1000),
            mem=task_spec.mem_limit * 1024,
            nsjail_cfg_path=self.nsjail_cfg_path,
            # log_file=log_file_path,
            log_fd=log_fd,
            nsjail_args=context.get('nsjail_args', ''))
        run_cmd = [self.nsjail_path] + shlex.split(cmdline_args) + ['--'] + exec

        self.user_temp = tempfile.NamedTemporaryFile(delete=False)
        self.logger.info('Using temp %s', self.user_temp.name)

        self.logger.info('Running command: %r', run_cmd)

        with self.journals.start('RUN-{}'.format(task_spec.label)), \
             open(infile_path, 'rb') as stdin, \
             Timer() as t:
            subp = run_with_pipes(run_cmd,
                # check=True,
                stdin=stdin,
                pipe_stdout=(self.user_temp, self.RUN_OUT_LIM),
                # if we believe user's stderr is not used AT ALL, the log
                # can be passed with `--stderr_to_null` turned on in nsjail
                stderr=subprocess.DEVNULL,
                pass_fds=(log_fd,))
            # to let it flush
            self.user_temp.close()

        self.logger.info("Run finished after %dms", t.duration * 1000)

        self.is_stdout_ole = subp._ole_stdout
        self.run_failed = (subp.returncode != 0)
        with os.fdopen(log_fd, 'r') as nsjail_log:
            self.jail_report = self._process_nsjail_log(nsjail_log)

        return subp

    def pl_check(self, test_files):
        checker = importlib.import_module('iruka.checkers.tolerant_diff')
        inf, outf = test_files

        checker_input = checker_io_pb2.CheckerInput(
            path_infile=str(inf),
            path_outfile=str(outf),
            path_out_user=self.user_temp.name)

        checker_output = checker.main(checker_input)
        return checker_output

    def pl_sandbox_clean(self):
        Path(self.user_temp.name).unlink()
        self.user_temp = None

    def pl_grade(self):
        pass

    def pl_grade_total(self):
        pass

    def pl_after_success(self):
        pass

    def pl_after_failure(self):
        pass

    def finalize(self):
        # read dict from disk to memory
        self.log_dict['COMPILE_STDOUT'] = iruka_rpc_pb2.Log(
            content=self.journals[0].dump('COMPILE'),
            truncated=self.build_ole_stdout)
        self.log_dict['COMPILE_STDERR'] = iruka_rpc_pb2.Log(
            content=self.journals[1].dump('COMPILE'),
            truncated=self.build_ole_stderr)

    def _reset_state(self):
        # FIXME: is this a bad pattern?
        if self.user_temp is not None:
            self.user_temp.close()
        self.user_temp = None
        self.jail_report = None
        self.process_failed = False
        self.is_stdout_ole = False
        self.log_dict = {}

    def _process_nsjail_log(self, file):
        jail_report = {}

        for ln in file:
            mat = re.match(r'\[S\]\[\d+?\] __STAT__:0 (?:\d+?:)?([\w]+)\s+=\s+(.*)', ln)
            if mat is None:
                # TODO: triage the message to separate file
                # self.logger.debug('SANDBOX >>> %s', ln[:-1])
                continue
            jail_report[mat.group(1)] = mat.group(2)

        self.logger.debug('captured stat dict:\n%s', pformat(jail_report))

        mandatory_keys = [
            'cgroup_memory_failcnt',
            'cgroup_memory_max_usage',
            'exit_normally',
            'time'
        ]

        for k in mandatory_keys:
            if k not in jail_report:
                raise IrukaInternalError(
                    'Cannot extract key "{}" from log, which is mandatory'.format(k))

        return jail_report

    def _determine_verdict(self, time_limit, print_fn=print) -> common_pb2.Verdict:
        # Sadly, only time_limit is not exposed to any other sources
        report = self.jail_report
        time_used = int(report['time'])
        mem_used = int(report['cgroup_memory_max_usage'])
        is_seccomp_violating = (report.get('seccomp_violation', '') != 'false')

        if is_seccomp_violating:
            self.logger.info(color('===== RF =====', fg='yellow', style='negative'))
            return common_pb2.RF

        if self.is_stdout_ole:
            # looks like nsjail ignores SIGPIPE and let children continue to run
            # until TLE, because of the pid-namespace :(
            self.logger.info(color('===== OLE =====', style='negative'))
            return common_pb2.OLE

        # check if the process ends with error
        verdict = None

        if report['cgroup_memory_failcnt'] != '0':
            verdict = common_pb2.MLE
        elif (report['exit_normally'] == 'false' and time_used >= time_limit):
            # FIXME: task
            verdict = common_pb2.TLE
        elif self.process_failed:
            verdict = common_pb2.RE

        if verdict is not None:
            verdict_name = common_pb2.Verdict.Name(verdict)
            self.logger.info(
                color('===== {:3} ====='.format(verdict_name), fg='magenta', style='negative') +
                ' REPORTED_BY_SANDBOX')
            return verdict
        return common_pb2.PENDING
