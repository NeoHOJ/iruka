import argparse
import click
import logging
import logging.config
import os
import sys
from pathlib import Path

import grpc
import yaml
from google.protobuf import empty_pb2
from google.protobuf import text_format
import iruka.handlers
from iruka.protos import (iruka_rpc_pb2, iruka_rpc_pb2_grpc)
from iruka.config import Config


BASE_PATH = Path(__file__).parent.absolute()
logging.Formatter.default_msec_format = '%s.%03d'
logger = logging.getLogger(__name__)


# the same machanism used in server
def loadConfig(path=None, configClass=Config):
    if path is None:
        try:
            path_dfl = BASE_PATH / '../iruka.yml'
            path = path_dfl.resolve(strict=True)
        except FileNotFoundError:
            raise FileNotFoundError(
                'The default config file "{}" does not exist. Specify one by --config.'.format(path_dfl.resolve()))

    with open(path, 'r') as f:
        d = yaml.safe_load(f)
    config = configClass()
    config.load_from_dict(d)
    return config


class IrukaClient(object):
    def __init__(self, config):
        self.base_path = BASE_PATH
        self.config = config
        self.stub = None

    def connect(self):
        # TODO: try to presist connection if the server
        # tells that the shutdown is temporatory
        try:
            logger.debug('Connecting to {}...'.format(self.config.server))
            with grpc.insecure_channel(self.config.server) as channel:
                self.stub = iruka_rpc_pb2_grpc.IrukaRpcStub(channel)
                self.subscribeToServer()
            self.stub = None
        except grpc.RpcError as err:
            if err.code() == grpc.StatusCode.UNAVAILABLE:
                logger.exception('Error connecting to server')
                return False
            else:
                raise

    def subscribeToServer(self):
        stub = self.stub
        config = self.config
        ret = stub.Version(empty_pb2.Empty())

        events = stub.Listen(iruka_rpc_pb2.AuthenticateRequest(token=config.auth_token))
        try:
            auth_result = next(events)
        except grpc.RpcError as err:
            logger.exception('Error to register client (%s)', err.code())
            return False

        logger.info('Auth success.')

        for event in events:
            self.processRequest(event)

        logger.info('The subscription channel is closed by the server.')

    def processRequest(self, event):
        enum = iruka_rpc_pb2.ServerEvent
        if event.type == enum.REQUEST_JUDGE:
            logger.info('Request judge...')
            iruka.handlers.requestJudge(self, event.submission_req)
        elif event.type == enum.ABORT_TASK:
            logger.info('Abort task...')
            raise NotImplementedError()
        elif event.type == enum.QUERY_STATUS:
            logger.info('Query status...')
            raise NotImplementedError()
        else:
            logger.error('Unknown or unexpected request {!r}'.format(event))


@click.command()
@click.option('-c', '--config', 'config_path', help=
    'The config file of judge client, default to `../iruka.yml`.')
def cli(config_path):
    ''' \U0001f42c Iruka, the backend of NeoHOJ. '''
    config = loadConfig(config_path)

    app = IrukaClient(config)
    exitCode = (1 if app.connect() == False else 0)
    sys.exit(exitCode)


def main(as_module=False):
    # duplicate
    log_config_path = Path(
        os.getenv('IRUKA_LOG_CONFIG', BASE_PATH / '../logging.yml'))
    with open(log_config_path, 'r') as f:
        logging.config.dictConfig(yaml.safe_load(f))

    cli(obj={})


if __name__ == '__main__':
    main(as_module=True)
