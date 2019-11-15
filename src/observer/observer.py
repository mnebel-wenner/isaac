import asyncio
import functools
import logging

import aiomas
from aiomas import expose

import planning
from observer.core.monitoring import Monitoring
from observer.core.termination import TerminationDetector

DEFAULT_MONITOR = 'observer.core.monitoring:Monitoring'
DEFAULT_TERM = 'observer.core.termination:MessageCounter'

logger = logging.getLogger(__file__)


class ObserverAgent(aiomas.Agent):
    """Observer for system of unit agents.

    Tasks:

    - Monitor scheduling of agents

      - Detect termination of negotiation processes
      - collect results from agents and store to database

    - Report to ControllerAgent

      - Termination
      - Negotiation results, i.e. identified cluster schedule

    For normal system setup within observer-controller system, do not
    directly initiate this class but use the factory provided at
    :meth:`controller.ControllerAgent.factory`

    """
    def __init__(self, container, ctrl_proxy, *,
                 n_agents=None,
                 log_dbcls=DEFAULT_MONITOR,
                 log_dbfile=None,
                 termcls=DEFAULT_TERM):

        super().__init__(container)

        self._n_agents = n_agents   # number of unitAgents
        self._ctrl = ctrl_proxy     # controller
        self._agents_registered = asyncio.Future()  # are all agents registered?
        if n_agents is None:
            self._agents_registered.set_result(True)
            
        self._ts = None             # target schedule
        self._weights = None        # weights

        # init monitoring database
        if log_dbfile:
            cls = aiomas.util.obj_from_str(log_dbcls)
            self._db = cls(log_dbfile)
            assert isinstance(self._db, Monitoring)
        else:
            self._db = None

        self._agents = {}   # mapping from agent_instace to agent_addr
        self._agent_names = {}  # mapping from agent_addr to agent_name

        # termination detection
        cls = aiomas.util.obj_from_str(termcls)
        self._termination_detector = cls(self._n_agents)
        assert isinstance(self._termination_detector, TerminationDetector)

        # negotiation related variables
        self._solution_determined = asyncio.Future()
        self._solution = None
        self._candidates = []
        self._task_finish_neg = None

        self._stop = False
        self._terminated = False
        
    @expose
    async def stop(self):
        """
        Cancel running async processes and close database.

        """
        if not self._task_finish_neg.done():
            self._task_finish_neg.cancel()
            try:
                await self._task_finish_neg
            except asyncio.CancelledError:
                pass  # Because we just cancelled it on purpose :)

        if self._db is not None:
            db, self._db = self._db, None
            db.close()
        self._stop = True
        
    @expose
    def register_unitAgent(self, agent_proxy, addr, name=None):
        """Register the unit agent represented by *agent_proxy* with the
        address *addr*.

        Called by all unit agents during startup.

        :param agent_proxy: The agent's proxy.
        :param addr: The agent's addr string representation.

        """
        logger.debug('[ObserverAgent] unitAgent registered: %s', addr)
        self._agents[agent_proxy] = addr
        self._agent_names[addr] = name if name else addr
        # check if all agents have registered
        if self._n_agents is not None and len(self._agents) == self._n_agents:
            self._agents_registered.set_result(True)
        
    @expose
    def start_observation(self, conn_data, date, target_schedule, weights):
        """Initiate the observer's task of observing a negotiation.

        Called by controller agents when starting a negotiation, including
        all initial information needed for database storage. Calls
        `:meth:Database.store_topology`

        :param conn_data: The topology as list of tuples (agent_1, agent_2), to
        be understood as bidirectional connections.
        :param date: The start date of the *target_schedule*.
        :param target_schedule: A list of values indicating the electrical
        target for the negotiation.
        :param weights: A list of weights [0,1] indicating the optimization
        weight of the respective value in the *target_schedule*
        """
        assert len(target_schedule) == len(weights)
        self._ts = target_schedule
        self._weights = weights

        self._termination_detector.reset()
        self._reset_negotiation_setup()

        if self._db is not None:
            self._db.setup(date, self._agents, self._agent_names)
            self._db.store_topology(conn_data)
            
    def _reset_negotiation_setup(self):
        self._candidates = []
        self._solution = None
        self._solution_determined = asyncio.Future()
        self._task_finish_neg = aiomas.create_task(self._wait_finish_neg())

    @expose
    def update_stats(self, agent, t, perf, n_os, msgs_in, msgs_out, msg_sent):
        """Update an *agent*'s statistics.

        Called multiple times by unit agents during a negotiation, informing
        the observer on negotiation meta data like current performance,
        the number of the operation schedule chosen by the agent and the
        numbers of messages received, sent and outgoing.

        :param agent: The unit agent's name.
        :param t: Date of sending.
        :param perf: Current performance measured at the unit agent.
        :param n_os: Number of operation schedule chosen at the agent.
        :param msgs_in: Number of messages received.
        :param msgs_out: Number of messages outgoing.
        :param msg_sent: Did the agent send out some messages (True or false).
        """
        if self._db is not None:
            self._db.append((t, agent, perf, n_os == len(self._agents),
                            msgs_out, msgs_in, msg_sent))

        self._termination_detector.update(agent, msgs_in, msgs_out)

    @expose
    async def update_final_cand(self, candidate):
        """Store final negotiation candidates.

        Called by each unit agent after receiving the stop signal to inform
        observer on final candidate.

        :param: :class:`openvpp_agents.planning.Candidate`
        """
        self._candidates.append(candidate)
        if len(self._candidates) == len(self._agents):
            logger.debug('[ObserverAgent] Received all final candidates.')
            # all agents have sent their candidates
            solution = self._get_solution(self._candidates)
            if self._db is not None:
                await self._db.flush(self._ts, self._weights, solution)

    def _get_solution(self, candidates):
        if self._terminated:
            # All candidates should be the same
            solution = candidates[0]
            for c in candidates[1:]:
                assert c == solution
            self._solution = solution
        else:
            # Merge all candidates into a single solution.
            # We need a dummy WorkingMemory for this:
            wm = planning.WorkingMemory(
                neighbors=None,
                start=None, res=None, intervals=None,
                ts=self._ts,
                weights=self._weights,
                ps=None,
                sysconf=None, candidate=None)
            reducer = functools.partial(planning.Candidate.merge,
                                        agent='controller',
                                        perf_func=wm.objective_function)
            solution = functools.reduce(reducer, candidates)
            self._solution = solution
        self._solution_determined.set_result(True)
        return solution

    @expose
    async def pass_solution(self):
        """Passes the solution of the last negotiation to the calling
        agent, e.g. the controller agent.

        :return: Cluster schedule as :class:`openvpp_agents.planning.Candidate`
        """
        await self._solution_determined

        # return solution
        assert self._solution
        return self._solution

    async def _wait_finish_neg(self):
        """Waits for termination detection and then informs the controller
        on this termination.
        """
        await self._termination_detector.terminated
        await self._ctrl.negotiation_finished()
