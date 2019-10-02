import shlex
import io
import os
import logging
import traceback
from pathlib import Path

from colors import color

import iruka._hoj_helpers as hoj_helpers
from iruka.common.utils import (pformat, pformat_pb)
from iruka.verdict import Verdict
from iruka.pipeline import JudgePipeline
from iruka.protos import (iruka_rpc_pb2, subtask_pb2, checker_io_pb2, common_pb2)
from iruka.exceptions import IrukaInternalError


logger = logging.getLogger(__name__)

LOG_STDOUT_PATH = '/tmp/judge.stdout.log'
LOG_STDERR_PATH = '/tmp/judge.stderr.log'


def judgeSubmission(irukaClient, req):
    # req:SubmissionRequest
    submission = req.submission
    # spec: list of Int64Array
    spec_pb = req.hoj_spec
    # convert back to 2D list, and then to hoj judge desc
    spec = hoj_helpers.hoj_to_judge_desc([ x.value for x in spec_pb ])
    # print(spec)

    problem_id = submission.problem_id

    if req.hoj_type != iruka_rpc_pb2.SubmissionRequest.REGULAR:
        logger.warn('Only problems of type REGULAR are supported. Rejecting this request...')
        yield iruka_rpc_pb2.SubmissionEvent(
            ack=iruka_rpc_pb2.SubmissionAck(
                id=req.id,
                reject_reason=iruka_rpc_pb2.SubmissionAck.UNSUPPORTED_PROBLEM))
        return

    yield iruka_rpc_pb2.SubmissionEvent(
        ack=iruka_rpc_pb2.SubmissionAck(id=req.id))

    # Note: HOJ sums scores to 100, but the spec suggests a convention that is
    # to sum to 1000k; will need to change the code afterwards
    total_score = 0

    # check testdata files' existence
    # a bit absurd to be included in pipeline
    # pipeline.verifyTestdata()
    all_tasks = [t[1] for t in (spec.samples + spec.subtasks)]
    prob_testdata = Path(irukaClient.config.testdata_path) / str(problem_id)
    testfiles, missing = hoj_helpers.hoj_collect_testdata(all_tasks, prob_testdata)

    if missing:
        # TODO: better error handling
        print('Missing the following files for testing, aborting...')
        for x in missing:
            print('> {!s}'.format(x))
        exc = IrukaInternalError('Testdata for problem id {} is not ready'.format(problem_id))
        exc._testfiles = testfiles
        exc._missing = missing
        raise exc

    log1 = open(LOG_STDOUT_PATH, 'w+')
    log2 = open(LOG_STDERR_PATH, 'w+')

    pipeline = JudgePipeline(
        spec,
        irukaClient.config,
        nsjail_cfg_path=Path('./nsjail-configs/nsjail.cfg').absolute(),
        log1=log1,
        log2=log2)

    # write out code; actually, gcc/g++ supports reading from stdin
    PATH_USERCODE = '/run/shm/program.cpp'
    PATH_PROGRAM = '/tmp/program'
    with open(PATH_USERCODE, 'w') as f:
        f.write(submission.code)
        code_length = f.seek(0, os.SEEK_CUR)
        logger.info('Written %d bytes to %s', code_length, PATH_USERCODE)

    # compile
    compile_ctx = {
        'CFLAGS': '-DONLINE_JUDGE',
    }
    build_success = pipeline.pl_build(
        src=Path(PATH_USERCODE).relative_to(pipeline.cwd_build),
        output=PATH_PROGRAM,
        context=compile_ctx)

    if not build_success:
        pipeline.finalize()
        yield iruka_rpc_pb2.SubmissionEvent(
            result=iruka_rpc_pb2.SubmissionResult(
                pipeline_success=False,
                final_stat=common_pb2.JudgeStat(
                    verdict=common_pb2.CE
                ),
                code_length=code_length,
                log=pipeline.log_dict))
        return

    group_idx = 0
    task_idx = 0
    stat_list = subtask_pb2.SubtaskContextList()
    score_total = 0
    final_verdict = common_pb2.AC

    for tgid, subtasks in pipeline.tasks:
        is_judging_sample = (tgid == 0)

        if is_judging_sample and len(subtasks):
            logger.info(color('------ Start judge sample ------', style='bold'))
        elif tgid == 1:
            logger.info(color('------ Start judge real tasks ------', style='bold'))

        score_group = 0

        # begin of a task group
        if not is_judging_sample:
            _, score_group_max = spec.task_groups[group_idx]
            score_group = score_group_max
            logger.info('+++ Start of group #%d: score_max=%d', group_idx, score_group_max)

        for indexed_subtask in subtasks:
            gidx, subtask = indexed_subtask
            logger.info('--- Task #%d, %d-%d: %r', task_idx, tgid, gidx, subtask)

            infile_path = testfiles[task_idx][0]
            subp = pipeline.pl_run(
                indexed_subtask,
                infile_path,
                cwd='/tmp',
                exec=['./program'])

            # inspect jail_report to decide whether to skip checking
            verdict = pipeline._determine_verdict(subtask.time_limit)

            if verdict == 0:
                checker_out = pipeline.pl_check(testfiles[task_idx])
                verdict = checker_out.verdict
                if verdict == common_pb2.WA:
                    logger.info(color('===== WA  =====', fg='red', style='negative'))
                else:
                    logger.info(color('===== AC  =====', fg='green', style='negative'))

            pipeline.pl_sandbox_clean()

            # populate contexts
            context = stat_list.values.add(
                task_group_num=tgid,
                subtask_num=gidx,
                stat=common_pb2.JudgeStat(
                    time_used=int(pipeline.jail_report['time']),
                    mem_used=int(pipeline.jail_report['cgroup_memory_max_usage']),
                    verdict=verdict))

            # FIXME!
            if Verdict.from_proto_greater(verdict, final_verdict):
                final_verdict = verdict

            if verdict != common_pb2.AC and not subtask.fallthrough:
                score_group = 0

            task_idx += 1

        # end of a task group

        if is_judging_sample:
            # TODO: if internal error happens or pretest fail when testing "sample", abort
            pass
        else:
            logger.info('[-] Group score: %d/%d', score_group, score_group_max)
            # group grading
            # FIXME: naive grading mechanism
            score_total += score_group

            group_idx += 1

    # print('j1', pipeline.journals[0].dump_all())
    # print('j2', pipeline.journals[1].dump_all())
    yield iruka_rpc_pb2.SubmissionEvent(partial_stat=stat_list)

    pipeline.finalize()

    # total grading (dummy)

    yield iruka_rpc_pb2.SubmissionEvent(
        result=iruka_rpc_pb2.SubmissionResult(
            pipeline_success=True,
            final_stat=common_pb2.JudgeStat(
                score=score_total,
                verdict=final_verdict,
            ),
            code_length=code_length,
            log=pipeline.log_dict))


def requestJudge(irukaClient, submissionRequest):
    logger.info('--- Server requested to judge %s ---',
        pformat_pb(submissionRequest))

    gen = judgeSubmission(irukaClient, submissionRequest)

    def extract(iterable):
        try:
            yield from iterable
        except IrukaInternalError as err:
            logger.exception('Internal error happens when judging')

            evt = iruka_rpc_pb2.SubmissionEvent(
                exception=iruka_rpc_pb2.SubmissionException(
                    message=str(err)))
            yield evt
        except Exception as err:
            logger.exception('Unhandled exception when judging')

            # should it dispose all previous result here?

            buf = io.StringIO()
            traceback.print_exc(file=buf)

            msg = 'Uncaught exception occurs in client!\n{!s}\n{}'.format(
                err, buf.getvalue())

            evt = iruka_rpc_pb2.SubmissionEvent(
                exception=iruka_rpc_pb2.SubmissionException(
                    message=msg))
            yield evt

    ret = irukaClient.stub.ReportSubmission(extract(gen))
    logging.info('--- Judge completes, report sent ---')
    return ret
