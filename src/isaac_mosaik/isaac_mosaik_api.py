import asyncio
import sys
import logging
import multiprocessing
import numpy as np
import time

# imports in order to read target file
import os.path
import json
import lzma
import io

from aiomas import expose
import aiomas
import arrow
import click

import controller.controller as controller
import observer.observer as observer
import isaac_util.util as util

logger = logging.getLogger(__name__)


@click.command()
@click.option('--log-level', '-l', default='info', show_default=True,
              type=click.Choice(['debug', 'info', 'warning', 'error',
                                 'critical']),
              help='Log level for the MAS')
@click.option('--log-file', '-lf', default='isaac.log', show_default=True,
              help='Log file for the MAS')
@click.argument('addr', metavar='HOST:PORT', callback=util.validate_addr)
def main(addr, log_level, log_file):
    """Open VPP multi-agent system."""
    try:
        # change event loop in case the platform is windows
        if sys.platform == 'win64' or sys.platform == 'win32':
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
        initialize_logger(log_level, log_file)
        aiomas.run(until=run(addr, log_level, log_file))
    finally:
        asyncio.get_event_loop().close()


def initialize_logger(log_level, log_file):
    """
    Initializes logger
    """
    # create clean log file
    # if os.path.exists(log_file):
    #     os.remove(log_file)

    # set log_level
    logging.getLogger('').setLevel(getattr(logging, log_level.upper()))
    # set file handler
    logging.getLogger('').addHandler(util.get_log_file_handler(log_file))
    # set console handler
    logging.getLogger('').addHandler(util.get_log_console_handler())


async def run(addr, log_level, log_file):
    mosaik_api = MosaikAPI(log_level, log_file)
    try:
        # Create an RPC connection to mosaik. It will handle all incoming
        # requests until one of them sets a result for "self.stopped".
        logger.debug('Connecting to %s:%s ...' % addr)
        mosaik_con = await aiomas.rpc.open_connection(
            addr, rpc_service=mosaik_api, codec=aiomas.JSON)
        mosaik_api.mosaik = mosaik_con.remote

        def on_connection_reset_cb(exc):
            # Gets called if the remote side closes the connection
            # (e.g., because it dies).
            if not mosaik_api.stopped.done():
                # If the remote side stopped, we also want to stop ...
                mosaik_api.stopped.set_result(True)

        mosaik_con.on_connection_reset(on_connection_reset_cb)

        # Wait until mosaik asks us to stop
        logger.debug('Waiting for mosaik requests ...')
        await mosaik_api.stopped
    except KeyboardInterrupt:
        logger.info('Execution interrupted by user')
    finally:
        logger.debug('Closing socket and terminating ...')
        await mosaik_con.close()
        await mosaik_api.finalize()


class MosaikAPI:
    """Interface to mosaik."""
    router = aiomas.rpc.Service()

    def __init__(self, log_level, log_file, host='localhost', port_start=10000):
        self.log_level = log_level
        self.log_file = log_file
        self.host = host
        self.port_start = port_start + 1
        self.step_size = 1 * 60 * 60 * 24  # seconds. can be overwritten in config['negotiation_details']['step_size']

        self.meta = {
            # TODO check what the api_version flag stands for - is it needed?
            'api_version': '2.2',
            'models': {
                'Agent': {
                    'public': True,
                    'params': [
                    ],
                    'attrs': [
                        'possible_schedules',
                        'chosen_schedule',  # only needed if isaac returns the chosen schedule to connected simulator
                    ],
                },
            },
        }
        # This future is gonna be triggered by "self.stop()".  "run()" waits
        # for it and stops the main event loop when it is done.
        self.stopped = asyncio.Future()

        # Set in run()
        self.mosaik_con = None  # Rpc connection to mosaik
        self.mosaik = None  # Proxy object for mosaik

        # Set in init()
        self.sid = None
        self.n_agents = None
        self.config = None
        self.container = None  # Container for all agents (all local)
        self.start_date = None

        self.ctrl = None  # ControllerAgent
        self.obs = None   # ObserverAGent

        self.agent_containers = []  # Proxies to agent containers
        self.container_procs = []  # Open instances for agent containers

        # Set/updated in create()/setup_done()
        self._aids = []
        self._created_agents = 0
        self._agents = {}  # UnitAgents
        self._t_last_step = None  # needed in case of some real time requirement

        # negotiation details
        self.intervals = None  # can be set in config['negotiation_details']['intervals']
        self.resolution = None  # can be set in config['negotiation_details']['resolution']

    async def finalize(self):
        """Stop all agents, containers and subprocesses when the simulation
        finishes."""
        futs = [a.stop() for a in self._agents.values()]
        futs += [c.stop() for c in self.agent_containers]
        await asyncio.gather(*futs)
        if self.ctrl:
            await self.ctrl.stop()
        if self.obs:
            await self.obs.stop()

        # Shutdown sub-processes
        for p in self.container_procs:
            await p.wait()
            logger.debug('UnitAgent container process terminated')

        await self.container.shutdown(as_coro=True)
        logger.debug('Controller / Observer container process terminated')

    @expose
    async def init(self, sid, *, start_date, n_agents, config):
        """Create a local agent container and the mosaik agent."""
        self.sid = sid  # simulator id
        self.n_agents = n_agents  # number of required agents
        self.config = config

        # negotiation details
        # set step size
        self.step_size = config['Negotiation_details']['step_size']

        # In-proc container for ControllerAgent / ObserverAgent
        addr = (self.host, self.port_start)
        container_kwargs = util.get_container_kwargs(start_date)
        container_kwargs.update(as_coro=True)  # Behave like a coro
        self.container = await aiomas.Container.create(
            addr, **container_kwargs)
        self.start_date = arrow.get(start_date).to('utc')

        ctrl_conf = config['ControllerAgent']
        obs_conf = config['ObserverAgent']
        self.ctrl, self.obs = await controller.ControllerAgent.factory(
            self.container, ctrl_conf, observer.ObserverAgent, obs_conf)

        self.resolution = self.ctrl._scheduling_res
        self.intervals = self.ctrl._scheduling_intervals

        # Remote containers for UnitAgents
        c, p = await self._start_containers(
            self.host, self.port_start + 1, start_date, self.log_level, self.log_file)
        self.agent_containers = c  # proxies to the container
        self.container_procs = p  # processes that run the container

        return self.meta

    @expose
    def create(self, num, model):
        # We do not yet want to instantiate the agents, b/c we don't know
        # to which units they will be connected.  So we just store the model
        # conf. for the agents and start them later.  Mosaik will get a list
        # of entities nonetheless.
        entities = []
        # Number of agents we "started" so far:
        n_agents = self._created_agents
        eid_start = 'Agent'
        self._created_agents += num
        for i in range(n_agents, n_agents + num):
            eid = eid_start + '%s' % i
            entities.append({'eid': eid, 'type': model})
            aid = '%s.%s' % (self.sid, eid)
            self._aids.append(aid)
        return entities

    @expose
    async def setup_done(self):
        relations = await self.mosaik.get_related_entities(self._aids)
        n_containers = len(self.agent_containers)
        futs = []
        for i, (aid, units) in enumerate(relations.items()):
            # in debug mode, start all unit and planning agents in same
            # container to achieve determinism in messages
            if self.log_level == 'debug':
                c = self.agent_containers[0]
            else:
                c = self.agent_containers[i % n_containers]
            assert len(units) == 1, 'Agent is connected to more than one unit.'
            uid, _ = units.popitem()
            futs.append(self._spawn_ua(container=c, aid=aid, uid=uid))

        results = await asyncio.gather(*futs)
        self._agents = {aid: agent for aid, agent in results}
        self._t_last_step = time.monotonic()

    @expose
    async def step(self, t, inputs):
        # Update the time for the agents
        await self._set_time(t)
        # Prepare input data and forward it to the agents
        data = {}
        for eid, attrs in inputs.items():
            input_data = {}
            for attr, values in attrs.items():
                assert len(values) == 1, 'Received Data from more than one unit'  # b/c we're only connected to 1 unit
                sender_id, value = values.popitem()
                input_data[attr] = value
                data['%s.%s' % (self.sid, eid)] = input_data

        # Update the unit agents with new possible schedules from mosaik.
        # in data there should be a list with possible schedules as lists
        futs = []
        for aid, input_data in data.items():
            # pass inputs to unitAgent
            futs.append(self._agents[aid].set_possible_schedules(input_data['possible_schedules']))

        await asyncio.gather(*futs)

        # wait for registration of observer and agents
        await self.ctrl._agents_registered
        await self.ctrl._observer_registered

        # read the target from .csv files
        # This could also be adopted, such that the target comes from a simulator
        # or by getting different targets per day
        target, weights = read_target_file(self.config['Negotiation_details']['target_file'],
                                           resolution=self.resolution, intervals=self.intervals)

        # get startdate
        now = self.container.clock.utcnow()
        # if now.format('HH:mm:ss,SSS') > '00:00':
        #     days = 1  # Next occurrence is tomorrow
        # else:
        #     days = 0  # Next occurrence is today
        # days = 0
        #
        # startdate = now.replace(days=days, hour=0, minute=0, second=0,
        #                         microsecond=0).to('utc')

        startdate = now
        logger.info('*** Starting Negotiation for %s***' % startdate)
        # add some real time requirement here if you have such
        await self.ctrl.run_negotiation(startdate, target, weights)
        logger.info('*** Negotiation finished for %s***' % startdate)
        self._t_last_step = time.monotonic()

        t_next = t + self.step_size

        # create outputs (the chosen schedule_id) for connected simulators
        futs = [a.get_current_schedule() for a in self._agents.values()]
        schedules = await asyncio.gather(*futs)
        outputs = {aid: {uid: {'chosen_schedule': schedule}}
                   for aid, uid, schedule in schedules}
        if outputs:
            await self.mosaik.set_data(outputs)

        return t_next

    @expose
    async def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            aid = '%s.%s' % (self.sid, eid)
            if aid not in self._aids:
                raise ValueError('Unknown entity ID "%s"' % eid)
            agent_instance = self._agents[aid]
            data[eid] = {}
            schedule_data = await agent_instance.unit.get_current_schedule()
            for attr in attrs:
                if 'chosen_schedule' in attr:
                    data[eid][attr] = schedule_data[2]
        return data

    @expose
    def stop(self):
        self.stopped.set_result(True)

    async def _start_containers(self, host, start_port, start_date, log_level, log_file):
        addrs = []
        procs = []
        for i in range(multiprocessing.cpu_count()):
            addr = (host, start_port + i)
            addrs.append('tcp://%s:%s/0' % addr)
            cmd = ['isaac-container',
                   '--start-date=%s' % start_date,
                   '--log-level=%s' % log_level,
                   '--log-file=%s' % log_file,
                   '%s:%s' % addr]
            procs.append(asyncio.ensure_future(asyncio.create_subprocess_exec(*cmd)))
        procs = await asyncio.gather(*procs)
        futs = [self.container.connect(a, timeout=10) for a in addrs]
        containers = await asyncio.gather(*futs)
        return containers, procs

    async def _spawn_ua(self, *, container, aid, uid):
        """Configure agents and connect simulated entities from mosaik with
        unit agents.

        :param container
        :param aid
        :param uid
        @:return tuple of agent_id, unit_agent instance

        """
        unit_model_cls = self.config['UnitModel_cls']
        unit_model_conf = self.config['UnitModel']
        unit_if_cls = self.config['UnitIf_cls']
        planner_cls = self.config['Planner_cls']
        planner_config = self.config['Planner']
        unit_agent, ua_addr = await container.spawn(
            'unit:UnitAgent.factory',
            ctrl_agent_addr=self.ctrl.addr,
            obs_agent_addr=self.obs.addr,
            unit_model=(unit_model_cls, unit_model_conf),
            unit_if=(unit_if_cls, {'agent_id': aid, 'unit_id': uid},),
            planner=(planner_cls, planner_config,),
        )
        return aid, unit_agent

    async def _set_time(self, time):
        self.container.clock.set_time(time)
        futs = [c.set_time(time) for c in self.agent_containers]
        await asyncio.gather(*futs)


def read_target_file(path_to_target_file, resolution=900, intervals=96):
    """
    Read target file and return target and weights
    """
    assert os.path.isfile(path_to_target_file), 'Could not find target file: {}'.format(path_to_target_file)
    # open the target file and read the header
    my_open = lzma.open if path_to_target_file.endswith('.xz') else io.open
    with my_open(path_to_target_file, 'rt') as target_file:
        # assert that the length of the file corresponds with the no_intervals (minus 1 because of the json header)
        no_rows = sum(1 for _ in target_file)
        assert intervals == no_rows - 1
        target_file.seek(0)  # jump back to beginning of file
        line = next(target_file).strip()
        targets_meta = json.loads(line)  # get json header
        assert targets_meta['interval_minutes'] == resolution / 60
        # load the target schedule and weights
        target = [0.0] * intervals
        weight = [0.0] * intervals
        for i in range(intervals):
            data = next(target_file).strip().split(',')
            target[i] = float(data[0])
            weight[i] = float(data[1])
    return target, weight
