import json
import sys
import logging
import traceback

from uuid import uuid4 as uuid
from kafka import KafkaConsumer
from activitystreams import parse as parse_as
from activitystreams import Activity

from logistik.utils import ParseException
from logistik.config import ConfigKeys
from logistik.environ import GNEnvironment

logger = logging.getLogger(__name__)


class KafkaReader(object):
    def __init__(self, env: GNEnvironment):
        self.logger = logging.getLogger(__name__)
        self.env = env

    def run(self) -> None:
        bootstrap_servers = self.env.config.get(ConfigKeys.HOSTS, domain=ConfigKeys.KAFKA)
        self.logger.info('bootstrapping from servers: %s' % (str(bootstrap_servers)))

        topic_name = self.env.config.get(ConfigKeys.TOPIC, domain=ConfigKeys.KAFKA)
        self.logger.info('consuming from topic {}'.format(topic_name))

        consumer = KafkaConsumer(
            topic_name,
            group_id='{}-{}'.format(self.env.config.get(ConfigKeys.MODEL_NAME), str(uuid())),
            value_deserializer=lambda m: json.loads(m.decode('ascii')),
            bootstrap_servers=bootstrap_servers,
            enable_auto_commit=True,
            connections_max_idle_ms=9 * 60 * 1000,
        )

        while True:
            try:
                for message in consumer:
                    self.handle_message(message)
            except InterruptedError:
                self.logger.info('got interrupted, shutting down...')
                break

    def handle_message(self, message) -> None:
        self.logger.debug("%s:%d:%d: key=%s value=%s" % (
            message.topic, message.partition,
            message.offset, message.key,
            message.value)
        )

        data, activity = None, None

        try:
            data, activity = self.try_to_parse(message)
        except InterruptedError:
            raise
        except ParseException:
            self.logger.error('activity stream was: {}'.format(str(message.value)))
            self.logger.exception(traceback.format_exc())
            self.env.capture_exception(sys.exc_info())
            return
        except Exception as e:
            self.logger.error('got uncaught exception: {}'.format(str(e)))
            self.logger.error('event was: {}'.format(str(message)))
            self.logger.exception(traceback.format_exc())
            self.env.capture_exception(sys.exc_info())
            return

        try:
            self.try_to_handle(data, activity)
        except InterruptedError:
            raise
        except Exception as e:
            self.logger.error('got uncaught exception: {}'.format(str(e)))
            self.logger.error('event was: {}'.format(str(message)))
            self.logger.exception(traceback.format_exc())
            self.env.capture_exception(sys.exc_info())

    def try_to_parse(self, message) -> (dict, Activity):
        try:
            data = message.value
            activity = parse_as(data)
            return data, activity
        except Exception as e:
            self.logger.error('could not parse message as activity stream: {}'.format(str(e)))
            raise ParseException(e)

    def try_to_handle(self, data: dict, activity: Activity) -> None:
        if activity.verb not in self.env.event_handler_map:
            self.logger.error('no plugin enabled for event {}, dropping message'.format(activity.verb))
            self.env.dropped_msg_log.info(data)
            self.env.stats.incr('dropped')
            return

        for handler in self.env.event_handler_map[activity.verb]:
            all_ok, status_code, msg = handler(data, activity)
            if not all_ok:
                logger.warning('[%s] handler "%s" failed: %s' % (activity.verb, str(handler), str(msg)))

        # TODO: return response
