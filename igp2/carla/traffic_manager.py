import random
import logging
from typing import Callable, Optional, List

import carla
import numpy as np
from carla import Vector3D

from igp2.agents.agent import Agent
from igp2.agents.agentstate import AgentState
from igp2.carla.agents.navigation.behavior_agent import BehaviorAgent

logger = logging.getLogger(__name__)


class TrafficManager:
    """ Class that manages non-ego CARLA agents in a synchronous way. The traffic manager manages its own list of
    agents that it synchronises with the CarlaSim object. """

    def __init__(self, n_agents: int = 5, ego: Agent = None):
        """ Initialise a new traffic manager.

        Note:
            This class manages its own list of agents that are then updated through the CarlaSim.take_action()

        Args:
            n_agents: Number of agents to manage
            ego: Optional ego vehicle in the simulation used to determine the spawn area of vehicles.
                If not specified then vehicles may be spawned across the whole map.
         """
        self.__n_agents = n_agents
        self.__ego = ego
        self.__spawn_radius = None
        self.__speed_lims = (2.0, 15.0)
        self.__agents = {}
        self.__enabled = False
        self.__spawns = []

    def update(self, simulation):
        """ This method updates the list of managed agents based on their state.
        All vehicles outside the spawn radius are de-spawned."""
        agents_existing = len([agent for agent in self.__agents.values() if agent is not None])
        if agents_existing < self.__n_agents:
            for i in range(self.__n_agents - agents_existing + 1):
                self.__spawn_agent(simulation)

    def take_actions(self, simulation):
        commands = []
        for agent_id, agent in self.__agents.items():
            if agent is None:
                continue

            if self.__ego is not None:
                ego_position = self.__ego.state.position
                distance_to_ego = np.linalg.norm(agent.state.position - ego_position)
                if distance_to_ego > self.__spawn_radius:
                    self.__remove_agent(agent, simulation)
                    continue

            if agent.done(None):
                agent.set_destination(random.choice(self.spawns).location)

            control = agent.run_step()
            command = carla.command.ApplyVehicleControl(agent.vehicle, control)
            commands.append(command)
        simulation.client.apply_batch_sync(commands)

    def destroy(self, simulation):
        for agent_id, agent in self.__agents.keys():
            if agent is not None:
                self.__remove_agent(agent_id)
        self.__agents = {}

    def __spawn_agent(self, simulation) -> BehaviorAgent:
        """Spawn new agents acting as traffic through the given callback function. """
        used_ids = simulation.used_ids + list(self.__agents.keys())
        agent_id = max(used_ids) if len(used_ids) > 0 else 0
        while agent_id in used_ids:
            agent_id += 1

        spawn_points = np.array(self.spawns)
        spawn_locations = np.array([[p.location.x, p.location.y] for p in spawn_points])

        blueprint_library = simulation.world.get_blueprint_library()
        blueprint = random.choice(blueprint_library.filter('vehicle.*.*'))

        # Calculate valid spawn points based on spawn radius
        valid_spawns = spawn_points
        if self.__ego is not None:
            ego_position = self.__ego.state.position
            distances = np.linalg.norm(spawn_locations - ego_position, axis=1)
            valid_spawns = spawn_points[(self.__ego.view_radius <= distances) & (distances <= self.__spawn_radius)]

        # Sample spawn state and spawn agent
        try_count = 0
        speed = random.uniform(self.__speed_lims[0], self.__speed_lims[1])
        while True:
            if try_count > 10:
                logger.debug("Couldn't spawn vehicle!")
                return

            spawn = random.choice(valid_spawns)
            spawn.location.z = 0.1
            heading = np.deg2rad(spawn.rotation.yaw)
            try:
                vehicle = simulation.world.spawn_actor(blueprint, spawn)
                velocity = Vector3D(speed * np.cos(heading), speed * np.sin(heading), 0.0)
                vehicle.set_target_velocity(velocity)
                break
            except:
                try_count += 1

        initial_state = AgentState(time=simulation.timestep,
                                   position=np.array([spawn.location.x, spawn.location.y]),
                                   velocity=np.array([velocity.x, velocity.y]),
                                   acceleration=np.array([0.0, 0.0]),
                                   heading=heading)
        agent = BehaviorAgent(agent_id, initial_state, vehicle)
        agent.ignore_traffic_lights(True)
        agent.set_destination(random.choice(self.spawns).location, spawn.location)
        self.__agents[agent.agent_id] = agent

    def __remove_agent(self, agent: Agent, simulation):
        self.__agents[agent.agent_id] = None
        agent.vehicle.destroy()

    def set_agents_count(self, value: int):
        """ Set the number of agents to spawn as traffic. """
        assert value >= 0, f"Number of agents cannot was negative."
        self.__n_agents = value

    def set_ego_agent(self, agent: Agent):
        """ Set an ego agent used for spawn radius calculations in vehicle
        spawning based on the agent's view radius """
        assert hasattr(agent, "view_radius"), f"No view radius given for the ego agent."
        assert agent.view_radius is not None, f"View radius of the given ego agent was None."

        self.__ego = agent
        self.__spawn_radius = 2 * agent.view_radius

    def set_spawn_speed(self, low: float, high: float):
        """ Set the initial spawn speed interval of vehicles."""
        assert low >= 0.0, f"Lower speed bound cannot be negative."
        assert high > low, f"Higher speed limit must be larger than lower speed limit."

        self.__speed_lims = (low, high)

    def set_agent_behaviour(self, value: str = "normal"):
        """ Set the behaviour of all agents as given by the behaviour types.
        If set to random, then each vehicle will be randomly assigned a behaviour type. """
        pass

    @property
    def ego(self) -> Agent:
        """ The ID of the ego vehicle in the simulation. """
        return self.__ego

    @property
    def n_agents(self) -> int:
        """ Number of agents to maintain as traffic in the simulation """
        return self.__n_agents

    @property
    def spawns(self) -> List[carla.Transform]:
        """ List of all possible spawn points"""
        return self.__spawns

    @spawns.setter
    def spawns(self, value: List[carla.Transform]):
        self.__spawns = value

    @property
    def enabled(self) -> bool:
        """Whether the traffic manager is turned on. """
        return self.__enabled

    @enabled.setter
    def enabled(self, value: bool):
        assert isinstance(value, bool)
        self.__enabled = value