import asyncio

import aiomas
from aiomas import expose
import logging

from controller.core.management import TopologyManager

DEFAULT_TOPMNGR = 'controller.core.management:TopologyManager'

logger = logging.getLogger(__name__)


class ControllerAgent(aiomas.Agent):
    """
    Controller for system of unit agents.
    
    Create pairs of (controller, observer) via the factory :meth:`factory`.
    
    Tasks:
     - read target file
     - Trigger Observer to monitor the negotiation process
     - create topology of agents
     - let one agent start the communication
     - Broadcast negotiation results, i.e. new schedules, to UnitAgents
    """

    @classmethod
    async def factory(cls, container, ctrl_kwargs, obs_cls, obs_kwargs):
        """Factory for general setup of controller-observer system.

        As in a controller-observer system these agents have to know
        eachother before any other process in the system starts, this factory
        creates and returns both agents after the setup is finished.

        The observer class has to be provided and thus can be modified,
        if needed. In the given setup, both agents reside in the same
        container.

        """
        # create controller
        ctrl = cls(container, **ctrl_kwargs)
        #connect to controller, so that obs can register
        ctrl_proxy = await container.connect(ctrl.addr)
        # crete observer
        obs = obs_cls(container, ctrl_proxy, **obs_kwargs)
        # register obs at ctrl
        ctrl_proxy.register_observer(obs)
        return (ctrl, obs)


    def __init__(self, container, *,
                 n_agents=None,
                 negotiation_single_start=True,
                 negotiation_timeout=15 * 60,
                 topology_manager=DEFAULT_TOPMNGR,
                 topology_phi=1,
                 topology_seed=None, # random seed for topology creation
                 scheduling_res=15 * 60, # resolution in seconds
                 scheduling_period= 2 * 24 * 60 * 60): # period in seconds
        """
        Initialize agent instance.
        For normal system setup within observer-controller system, do not
        directly initiate this class but use the factory provided at
        :meth:`controller.ControllerAgent.factory
        """
        super().__init__(container)

        self._agents = {}       # dict mapping from agent_instance to agent_addr
        self._agent_names = {}  # dict mapping from agnet_addr to agent_name
        self._n_agents = n_agents
        self._agents_registered = asyncio.Future()
        if n_agents is None:
            self._agents_registered.set_result(True)

        self._observer = None
        self._observer_registered = asyncio.Future()

        # init topology management
        cls = aiomas.util.obj_from_str(topology_manager)
        self._topology_manager = cls(topology_phi, topology_seed)
        assert isinstance(self._topology_manager, TopologyManager)
        
        # scheduling / negotiation
        self._scheduling_res = scheduling_res
        self._scheduling_period = scheduling_period
        self._scheduling_intervals = self._scheduling_period // self._scheduling_res
        self._neg_single_start = negotiation_single_start
        self._neg_timeout = negotiation_timeout
        self._task_negotiation = None
        self._neg_done = None
        
    @expose
    async def stop(self):
        if self._task_negotiation:
            if not self._task_negotiation.done():
                self._task_negotiation.cancel()
                try:
                    await self._task_negotiation
                except asyncio.CancelledError:
                    pass  # Because we just cancelled it!
            
    @expose
    def register_unitAgent(self, agent_proxy, addr, name=None):
        """
        Register the unitAgent represented by *agent_proxy*
        with the address *addr*
        """
        logger.debug('[Controller] unitAgent registered: %s' % addr)
        self._agents[agent_proxy] = addr
        self._agent_names[addr] = name if name else addr
        if self._n_agents is not None and len(self._agents) == self._n_agents:
            self._agents_registered.set_result(True)
            
    @expose
    def register_observer(self, agent_proxy):
        """
        Register the observer agent represented by *agent_proxy*
        with the address *addr*.
        """
        logger.debug('[Controller] Observer agent registered')
        self._observer = agent_proxy
        self._observer_registered.set_result(True)

    @expose
    async def run_negotiation(self, startdate, target_schedule, weights):
        """
        Start the negotations
        """
        self._neg_done = asyncio.Future()
        # initialize negotiation
        await self.init_negotiation(target_schedule, weights, startdate)
        # Wait until agents finish (observer informs controller via
        # :meth:negotiation_finished) or timeout is reached.
        try:
            await asyncio.wait_for(self._neg_done, self._neg_timeout)
        except asyncio.TimeoutError:
            logger.info('[Controller] Negotioation finished due to timeout')  # we handle this error by stopping the negotiation below
        await self.stop_negotiation()
    
        # get solution from observer
        final_cs = await self._observer.pass_solution()
        await self._broadcast_solution(final_cs)

    async def init_negotiation(self, target_schedule, weights, startdate):
        """
        Initialize negotiation
        """       
         
        logger.debug('[ControllerAgent] Build topology for new negotiation')
        # build topology with topology manager
        topology = self._topology_manager.make_topology(self._agents)
        conn_data = self._topology_manager.topology_as_list(self._agent_names)  # for observer

        # begin observation of negotiation
        if self._observer is None:
            raise RuntimeError('Observer not registered yet!')
        await self._observer.start_observation(conn_data, startdate,
                                                    target_schedule, weights)

        # call store topology for all agents
        for a in self._agents:
            # tell unit about new negotiation
            await a.new_negotiation()
            await a.store_topology(
                self.addr, tuple(topology[a]), target_schedule,
                weights, self._scheduling_res, self._scheduling_intervals, startdate)

        # initialize negotiation by calling init_negotiation of one agent
        logger.debug('[ControllerAgent] Initializing new negotiation for %s' % startdate)
        for agent in self._agents.keys():
            await agent.init_negotiation()
            if self._neg_single_start:
                break 

    async def stop_negotiation(self):
        """
        Stop negotiation for each agent
        """
        futs = [agent.stop_negotiation() for agent in self._agents.keys()]
        logger.debug('[ControllerAgent] send stop_negotiation to all agents')
        await asyncio.gather(*futs)
            
    @expose
    def negotiation_finished(self):
        """
        Called by Observer after termination of negotiation has been
        detected.
        """
        logger.debug('[Controller] Negotiation finished - info received by observer.')
        self._neg_done.set_result(True)
        
    async def _broadcast_solution(self, solution):
        """
        Called at the end of a negotiation. The solution of negotiation is broadcasted
        to the unit agents so that they can inform their units.
        """
        futs = []
        logger.info("[Controller] Broadcast solution: %s Performance: %s"
              %(solution.sids, solution.perf))
        # inform all agents about their schedule id
        for agent, addr in self._agents.items():
            schedule_id = solution.sids[solution.idx[addr]]
            futs.append(agent.set_schedule(schedule_id))
        await asyncio.gather(*futs)





