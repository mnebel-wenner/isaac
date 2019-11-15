"""
Planning module

See :file:`docs/planning.rst` for a detailed description of our planning
algorithm.

"""

import aiomas
import asyncio
from collections import namedtuple
import logging
import numpy as np
import time

import unit

logger = logging.getLogger(__name__)


class Planner(unit.Planner):
    """ Planning instance that is used to manage the negotiations.
    It belongs to a specific UnitAgent *agent* """

    def __init__(self, agent, check_inbox_interval=0.01):
        """Initialize planner."""
        self.agent = agent
        self.name = agent.addr
        self.check_inbox_interval = check_inbox_interval

        self.task_negotiation = None        # Task for negotiation
        self.task_negotiation_stop = False  # Is True if negotiation should stop
        self.inbox = []                     # Inbox of messages
        self.wm = None                      # Working memory

    def stop(self):
        if self.task_negotiation and not self.task_negotiation.done():
            self.task_negotiation.cancel()
        
    @aiomas.expose
    async def store_topology(self, _, neighbors, target_schedule, weights,
                             resolution, intervals, startdate):
        """Inform this agent about its neighbors."""
        # connect to neighbors
        futs = [self.agent.container.connect(n) for n in neighbors]
        neighbors = await asyncio.gather(*futs)

        assert intervals == len(target_schedule)

        # get possible schedules
        possible_schedules = self.agent.model.generate_schedules(
            startdate, resolution, intervals, None)
        logger.debug("%s found %s possible schedules" %(self.agent.name, len(possible_schedules)))

        # create an initial WorkingMemory
        self.wm = WorkingMemory(neighbors=neighbors, start=startdate,
                                res=resolution, intervals=intervals,
                                ts=target_schedule, weights=weights,
                                ps=possible_schedules, sysconf=None,
                                candidate=None)

        # Take the first possible OS and ignore its utility (not important yet)
        schedule_id, _, op_sched = possible_schedules[0]

        # create sysconf with only the first possible OS
        sysconf = SystemConfig(
            idx={self.name: 0},
            cs=np.array([op_sched], dtype=float),
            sids=[schedule_id],
            cnt=[0])
        # store it in your wm
        self.wm.sysconf = sysconf
        # get performance of this sysconf
        perf = self.wm.objective_function(sysconf.cs)

        # create a candidate equivalent to the sysconf
        candidate = Candidate(
            agent=self.name,
            idx={self.name: 0},
            cs=np.array([op_sched], dtype=float),
            sids=[schedule_id],
            perf=perf)
        # store it in your wm
        self.wm.candidate = candidate
        # check your inbox and for the negotiation_stop signal
        self.task_negotiation_stop = False
        self.task_negotiation = aiomas.create_task(self.process_inbox())

    @aiomas.expose
    async def init_negotiation(self):
        """
        Initialize negotiation by sending initial sysconf and candidate to all
        neighbors
        """
        for neighbor in self.wm.neighbors:
            self.wm.msgs_out += 1
            logger.debug('%s sending message %d' % (self.agent.name, self.wm.msgs_out))
            aiomas.create_task(neighbor.update(self.wm.sysconf, self.wm.candidate))
        logger.debug('%s updating Observer from init_negotiation' % self.agent.name)
        await self._update_obs_agent(True)
        
    @aiomas.expose
    async def stop_negotiation(self):
        """
        Stop negotiation and update observer
        about your current *candidate*
        """
        # send signal to negotiation task
        self.task_negotiation_stop = True
        # wait for task to finish
        await self.task_negotiation
        
        # get solution and empty inbox and wm
        candidate = self.wm.candidate
        self.inbox = []
        self.wm = None
            
        # inform observer
        await self.agent.obs_agent.update_final_cand(candidate)
        logger.debug('{} finished negotiation'.format(self.agent.name))

    async def process_inbox(self):
        """Process inbox."""
        while not self.task_negotiation_stop:
            # wait for some time
            await asyncio.sleep(self.check_inbox_interval)

            if not self.inbox:  # Inbox is empty
                continue

            logger.debug('%s checking inbox - #msg %s' % (self.agent.name, len(self.inbox)))

            wm = self.wm
            sysconf = wm.sysconf
            candidate = wm.candidate
            inbox, self.inbox = self.inbox, []

            # check all messages
            for sysconf_other, candidate_other in inbox:
                self.wm.msgs_in += 1
                # If necessary: update initial sysconf/candidate
                sysconf, candidate = self._perceive(
                    sysconf, sysconf_other,
                    candidate, candidate_other)

            # Has sysconf or candidate changed?
            state_changed = (sysconf is not wm.sysconf or
                             candidate is not wm.candidate)

            if state_changed:
                # sysconf or candidate changed.
                # Check if we can do better by changing our os
                sc, cand = self._decide(sysconf, candidate)
                wm.sysconf = sc
                wm.candidate = cand

                # broadcast new sysconf and candidate
                self._act()
            
            await self._update_obs_agent(state_changed)

    def _perceive(self, sysconf, sysconf_other, candidate, candidate_other):
        """Merge the system configuration and candidates from *self* and
        *other*.

        """
        # It's important to *not* update the WorkingMemory here!  We want to
        # keep our original sysconf/candidate until we know if and which new
        # sysconf/candidate we choose.
        sysconf = SystemConfig.merge(sysconf, sysconf_other)
        candidate = Candidate.merge(candidate, candidate_other, self.name,
                                    self.wm.objective_function)

        return sysconf, candidate

    def _get_new_os(self, current_best_perf, sysconf, name):
        """Return a tuple *os, sid* from the list of possible schedules *ps* if we
        find a Candidate, that performs better than the current one.

        Return ``None`` if we don't find any.

        """
        best_perf = current_best_perf
        new_op_sched = None
        new_sid = None
        new_candidate_found = False
        for sid, _, op_sched in self.wm.ps:  # utility can be ignored
            # Currently, we use the "global" check here, but this might change
            # so don't return the candidate directly.
            new_s = sysconf.update(name, op_sched, sid)
            new_perf = self.wm.objective_function(new_s.cs)
            if new_perf > best_perf:
                # new_c performs better than all others before
                new_candidate_found = True
                best_perf = new_perf
                new_op_sched = op_sched
                new_sid = sid

        # return *new_op_sched* with sid *new_sid* if we found a better candidate
        if new_candidate_found:
            return new_op_sched, new_sid
        else:
            return None

    @aiomas.expose
    def update(self, sysconf_other, candidate_other):
        """Update agent."""
        logger.debug('%s received message.' % self.agent.name)
        self.inbox.append((sysconf_other, candidate_other))

    def _act(self):
        """Broadcast new sysconf and candidate to all neighbors."""
        wm = self.wm
        for neighbor in wm.neighbors:
            wm.msgs_out += 1
            logger.debug('%s sending message %d' % (self.agent.name, wm.msgs_out))
            aiomas.create_task(neighbor.update(wm.sysconf, wm.candidate))

    def _decide(self, sysconf, candidate):
        """
        Try to find a schedule that leads to a better candidate
        """
        name = self.name
        current_sid = sysconf.data(name).sid

        # data returns a tuple (*os*, *sid*)
        current_best = candidate.data(name)
        # cuurent performance of candidate
        current_best_perf = candidate.perf

        # Expand "current_best"
        best_os, best_sid = current_best.os, current_best.sid
        new_os_sid = self._get_new_os(current_best_perf, sysconf, name)

        if new_os_sid is not None:
            # We have a new Candidate that is locally better then the old one. Check if
            # it is also globally better

            # new_os_sid is actually a tuple of (*os*, *sid*)!
            new_os, new_sid = new_os_sid

            new_s = sysconf.update(name, new_os, new_sid)
            new_candidate = Candidate(
                agent=self.name,
                idx=new_s.idx,
                cs=new_s.cs,
                sids=new_s.sids, perf=None).update(
                name, new_os, new_sid,
                self.wm.objective_function
            )

            if new_candidate.perf > candidate.perf:
                # We found a new candidate
                candidate = new_candidate
                best_os = new_os
                best_sid = new_sid

        if current_sid != best_sid:
            # We need a new counter value if
            # - we create a new, better candidate
            # - the updated candidate contains a different schedule then we
            #   stored in our current sysconf.
            #
            # -> We need a new count if the os in the candidate is different
            #    from the os in the sysconf.
            sysconf = sysconf.update(name, best_os, best_sid)

        return sysconf, candidate

    def _update_obs_agent(self, msg_sent):
        """
        Updates the observer agent about the carrunt status of the unitAgent

        Called by all unit agents during negotiation 
        after having processed their inbox.

        :param msg_sent: Must be True if the agent has sent new messages.
        """
        wm = self.wm
        return self.agent.obs_agent.update_stats(
            agent=self.agent.name,
            t=time.process_time(), # process time
            perf=wm.candidate.perf,
            n_os=len(wm.candidate.cs),  # Number of known op. scheds.
            msgs_in=wm.msgs_in, # total number of incoming messages
            msgs_out=wm.msgs_out, # total number of outgoing messages
            msg_sent=msg_sent) # did you send new messages?
        
@aiomas.codecs.serializable
class SystemConfig:
    """Immutable data structure that holds the system configuration."""
    Data = namedtuple('Data', 'os, sid, count')

    def __init__(self, idx, cs, sids, cnt):
        self._idx = idx
        self._cs = cs
        self._cs.setflags(write=False)  # Make the NumPy array read-only
        self._sids = tuple(sids)
        self._cnt = tuple(cnt)

    def __eq__(self, other):
        return (
            self._idx == other._idx and
            self._sids == other._sids and
            self._cnt == other._cnt and
            np.array_equal(self._cs, other._cs)
        )

    @property
    def idx(self):
        """Mapping from agent names to indices of the corresponding agents
        within the remaining attributes."""
        return self._idx

    @property
    def cs(self):
        """Cluster schedule; list of operational schedules as 2D NumPy array.
        """
        return self._cs

    @property
    def sids(self):
        """List of schedule IDs for each OS in the cluster schedule."""
        return self._sids

    @property
    def cnt(self):
        """Counter values for each OS selection in the cluster schedule."""
        return self._cnt

    @classmethod
    def merge(cls, sysconf_i, sysconf_j):
        """Merge *sysconf_i* and *sysconf_j* and return the result.

        If *sysconf_j* does not lead to modifications to *sysconf_i*, return
        the original instance of *sysconf_i* (unchanged).

        """
        modified = False
        keyset_i = set(sysconf_i.idx)
        keyset_j = set(sysconf_j.idx)

        idx_map = {}    # map with indices for each agent
        cs = []         # clustered schedule (list of *os)
        sids = []       # list of schedule ids
        cnt = []        # list of counter values

        # Keep agents sorted to that all agents build the same index map
        for i, a in enumerate(sorted(keyset_i | keyset_j)):
            os = None
            count = -1

            # An a might be in keyset_i, keyset_j or in both!
            if a in keyset_i:
                # Use data of this a if it exists
                os, sid, count = sysconf_i.data(a)
            if a in keyset_j:
                # Use data of other a if it exists ...
                data_j = sysconf_j.data(a)
                if data_j.count > count:
                    # ... and if it is newer:
                    modified = True
                    os, sid, count = data_j

            idx_map[a] = i
            cs.append(os)
            sids.append(sid)
            cnt.append(count)

        # return new instance if sysconf_i has been modified
        if modified:
            sysconf = cls(idx=idx_map, cs=np.array(cs), sids=sids, cnt=cnt)

        # return original instance, if it remains unchanged
        else:
            sysconf = sysconf_i

        # If "sysconf" and "sysconf_i" are equal,
        # they must also have the same identity
        assert (sysconf == sysconf_i) == (sysconf is sysconf_i)

        return sysconf

    def data(self, agent):
        """Return a tuple *(os, sid, count)* for *agent*."""
        idx = self._idx[agent]
        os = self._cs[idx]
        sid = self._sids[idx]
        count = self._cnt[idx]
        return self.Data(os, sid, count)

    def update(self, agent, os, sid):
        """Clone the current instance with an updated operation schedule *os*
        (with ID *sid*) for *agent*.  Also increase the corresponding counter
        value."""
        idx = self._idx.copy()
        i = idx[agent]
        cs = self._cs.copy()
        cs[i] = os
        sids = list(self._sids)
        sids[i] = sid
        cnt = list(self._cnt)
        cnt[i] += 1
        return self.__class__(idx=idx, cs=cs, sids=sids, cnt=cnt)


@aiomas.codecs.serializable
class Candidate:
    """
    Data structure that holds an agent's proposal of a solution for the
    optimization problem.
    """
    Data = namedtuple('Data', 'os, sid')

    def __init__(self, agent, idx, cs, sids, perf):
        self._agent = agent
        self._idx = idx
        self._cs = cs
        self._cs.setflags(write=False)
        self._sids = tuple(sids)
        self._perf = perf

    def __eq__(self, other):
        return (
            self._agent == other._agent and
            self._idx == other._idx and
            self._sids == other._sids and
            self._perf == other._perf and
            np.array_equal(self._cs, other._cs)
        )

    @property
    def agent(self):
        """Name of the agent that created this candidate."""
        return self._agent

    @property
    def idx(self):
        """Mapping from agent names to indices of the corresponding agents
        within the remaining attributes."""
        return self._idx

    @property
    def cs(self):
        """Cluster schedule; list of operational schedules as 2D NumPy array.
        """
        return self._cs

    @property
    def sids(self):
        """List of schedule IDs for each OS in the cluster schedule."""
        return self._sids

    @property
    def perf(self):
        """Performance of this candidate."""
        return self._perf

    @classmethod
    def merge(cls, candidate_i, candidate_j, agent, perf_func):
        """Return a new candidate for *agent* based on the agent's
        *candidate_i* or the new *candidate_j*.

        If *candidate_j* does *not* lead to modifications in *candidate_i*,
        return the original *candidate_i* instance (unchanged).

        """
        keyset_i = set(candidate_i.idx)
        keyset_j = set(candidate_j.idx)
        candidate = candidate_i  # Default candidate is *i*

        if keyset_i < keyset_j:
            # Use *j* if *K_i* is a true subset of *K_j*
            candidate = candidate_j
        elif keyset_i == keyset_j:
            # Compare the performance if the keysets are equal
            if candidate_j.perf > candidate_i.perf:
                # Choose *j* if it performs better
                candidate = candidate_j
            elif candidate_j.perf == candidate_i.perf:
                # If both perform equally well, order them by name
                if candidate_j.agent < candidate_i.agent:
                    candidate = candidate_j

        # Keysets are not equal and keyset_i is NOT a true subset of keyset_j
        elif keyset_j - keyset_i:
            # If there are elements in keyset_j but not in keyset_i,
            # update *candidate_i*
            idx_map = {}
            cs_buf = []
            sids = []
            # Index should be sorted by agent name (because determinism)
            for i, a in enumerate(sorted(keyset_i | keyset_j)):
                idx_map[a] = i
                if a in keyset_i:
                    data = candidate_i.data(a)
                else:
                    data = candidate_j.data(a)
                cs_buf.append(data.os)
                sids.append(data.sid)

            cs = np.array(cs_buf)
            perf = perf_func(cs)
            candidate = Candidate(agent, idx_map, cs, sids, perf)

        # If "candidate" and "candidate_i" are equal,
        # they must also have the same identity
        assert (candidate == candidate_i) == (candidate is candidate_i)

        return candidate

    def data(self, agent):
        """Return a tuple *(os, sid)* for *agent*."""
        idx = self._idx[agent]
        os = self._cs[idx]
        sid = self._sids[idx]
        return self.Data(os, sid)

    def update(self, agent, os, sid, perf_func):
        """Clone the current instance with an updated operation schedule *os*
        (with ID *sid*) for *agent*.  Also evaluate the performance of the
        new candidate using *perf_func*."""
        agent = agent
        idx = dict(self._idx)
        cs = self._cs.copy()
        sids = list(self._sids)
        i = idx[agent]
        cs[i] = os
        sids[i] = sid
        perf = perf_func(cs)
        return self.__class__(agent=agent, idx=idx, cs=cs, sids=sids,
                              perf=perf)


class WorkingMemory:
    """Stores all negotiation related state."""
    def __init__(self, neighbors, start, res, intervals, ts, weights, ps,
                 sysconf, candidate, msgs_in=0, msgs_out=0):
        self.neighbors = neighbors  # agent's neighbors
        self.start = start          # startdate
        self.res = res              # resolution of intervals (e.g. 15 minutes)
        self.intervals = intervals  # number of intervals per day
        self.ts = ts                # target schedule
        self.weights = weights      # weights
        self.ps = ps                # possible schedules

        self.sysconf = sysconf      # current systemconfiguration
        self.candidate = candidate  # current best candidate
        self.msgs_in = msgs_in      # number of incoming messages
        self.msgs_out = msgs_out    # number of outgoing messages

    def __eq__(self, other):
        ret = (
            self.neighbors == other.neighbors and
            self.start == other.start and
            self.res == other.res and
            self.intervals == other.intervals and
            np.array_equal(self.ts, other.ts) and
            np.array_equal(self.weights, other.weights) and
            self.sysconf == other.sysconf and
            self.candidate == other.candidate and
            self.msgs_in == other.msgs_in and
            self.msgs_out == other.msgs_out
        )
        # The list of possible schedules is an ugly beast
        ret = ret and (len(self.ps) == len(other.ps))
        for ps_i, ps_j in zip(self.ps, other.ps):
            ret = ret and (ps_i[:2] == ps_j[:2])
            ret = ret and np.array_equal(ps_i[2], ps_j[2])

        return ret

    def objective_function(self, cluster_schedule):
        # Return the negative(!) sum of all deviations, because bigger scores
        # mean better plans (e.g., -1 is better then -10).
        # print('objective_function: ')
        sum_cs = cluster_schedule.sum(axis=0)  # sum for each interval
        diff = np.abs(self.ts - sum_cs)  # deviation to the target schedeule
        w_diff = diff * self.weights  # multiply with weight vector
        result = -np.sum(w_diff)
        return result
