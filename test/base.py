from activitystreams import Activity
from flask import Flask
from flask_testing import TestCase

from logistik.cache import ICache
from logistik.cache.redis import CacheRedis
from logistik.config import ErrorCodes
from logistik.enrich.identity import IdentityEnrichment
from logistik.enrich.manager import EnrichmentManager
from logistik.enrich.published import PublishedEnrichment
from logistik.environ import ConfigDict
from logistik.environ import GNEnvironment
from logistik.handlers.base import BaseHandler
from logistik.handlers.manager import HandlersManager
from logistik.stats import IStats
from logistik.utils.kafka_reader import KafkaReader


class MockLogger(object):
    def __init__(self):
        self.drops = 0

    def info(self, _):
        self.drops += 1

    def warning(self, _):
        self.drops += 1


class MockHandler(BaseHandler):
    def __init__(self):
        super().__init__()
        self.n_handled = 0

    def setup(self, env: GNEnvironment):
        self.enabled = True

    def handle(self, data: dict, activity: Activity):
        self.n_handled += 1
        return BaseHandler.OK, ErrorCodes.OK, dict()


class MockStats(IStats):
    def incr(self, key: str) -> None:
        pass

    def decr(self, key: str) -> None:
        pass

    def timing(self, key: str, ms: float):
        pass

    def gauge(self, key: str, value: int):
        pass

    def set(self, key: str, value: int):
        pass


class MockEnv(GNEnvironment):
    def __init__(self):
        super().__init__(None, ConfigDict(dict()))
        self.dropped_msg_log = MockLogger()
        self.failed_msg_log = MockLogger()
        self.stats = MockStats()
        self.cache = ICache
        self.event_handler_map = dict()
        self.handlers_manager = None
        self.enrichment_manager = None
        self.enrichers = [
            ('published', PublishedEnrichment()),
            ('id', IdentityEnrichment()),
        ]


class BaseTest(TestCase):
    def create_app(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        return app

    def setUp(self):
        self.env = MockEnv()
        self.reader = KafkaReader(self.env)
        self.env.handlers_manager = MockHandler()
        self.env.enrichment_manager = EnrichmentManager(self.env)
        self.env.cache = CacheRedis(self.env, host='mock')