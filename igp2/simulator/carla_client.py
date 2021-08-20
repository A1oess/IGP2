import time
import numpy as np
import carla
import subprocess

from carla import Transform, Location, Rotation, Vector3D
from igp2.agent import AgentState, Agent, Observation
from igp2.data.scenario import ScenarioConfig
from igp2.opendrive.map import Map


class CarlaSim:
    """ An interface to the CARLA simulator """

    def __init__(self, fps=20, xodr=None, port=2000, carla_path='/opt/carla-simulator'):
        """ Launch the CARLA simulator and define a CarlaSim object

        Args:
            fps: number of frames simulated per second
            xodr: path to a .xodr OpenDrive file defining the road layout
            port: port to use for communication with the CARLA simulator
            carla_path: path to the root directory of the CARLA simulator
        """
        self.__scenario_map = Map.parse_from_opendrive(xodr)
        args = [f'{carla_path}/CarlaUE4.sh', '-quality-level=Low', f'-carla-rpc-port={port}']
        self.__carla_process = subprocess.Popen(args)
        time.sleep(10)
        self.__client = carla.Client('localhost', port)
        self.__client.set_timeout(10.0)  # seconds
        if xodr is not None:
            self.load_opendrive_world(xodr)
        self.__fps = fps
        self.__timestep = 0
        self.__world = self.__client.get_world()
        settings = self.__world.get_settings()
        settings.fixed_delta_seconds = 1 / fps
        settings.synchronous_mode = True
        self.__world.apply_settings(settings)
        self.__agents = {}
        self.__actor_ids = {}

    def __del__(self):
        self.__carla_process.kill()

    def load_opendrive_world(self, xodr):
        with open(xodr, 'r') as f:
            opendrive = f.read()
        self.__client.generate_opendrive_world(opendrive)

    def step(self):
        """ Advance the simulation by one time step"""
        self.__world.tick()
        self.__timestep += 1
        frame = self.__get_current_frame()
        observation = Observation(self.__scenario_map, frame)
        self.__take_actions(observation)

    def add_agent(self, agent: Agent, state: AgentState):
        """ Add a vehicle to the simulation

        Args:
            agent: agent to add
            state: initial state of the agent
        """
        blueprint_library = self.__world.get_blueprint_library()
        blueprint = blueprint_library.find('vehicle.audi.a2')
        yaw = np.rad2deg(state.heading)
        transform = Transform(Location(x=state.position[0], y=-state.position[1], z=0.1), Rotation(yaw=yaw))
        actor = self.__world.spawn_actor(blueprint, transform)
        actor.set_target_velocity(Vector3D(state.velocity[0], -state.velocity[1], 0.))
        self.__actor_ids[agent.agent_id] = actor.id
        self.__agents[agent.agent_id] = agent

    def __get_current_frame(self):
        actor_list = self.__world.get_actors()
        frame = {}
        for agent_id in self.__agents:
            actor = actor_list.find(self.__actor_ids[agent_id])
            transform = actor.get_transform()
            heading = np.deg2rad(-transform.rotation.yaw)
            velocity = actor.get_velocity()
            acceleration = actor.get_acceleration()
            state = AgentState(time=self.__timestep,
                               position=np.array([transform.location.x, -transform.location.y]),
                               velocity=np.array([velocity.x, -velocity.y]),
                               acceleration=np.array([acceleration.x, -acceleration.x]),
                               heading=heading)
            frame[agent_id] = state
        return frame

    def __take_actions(self, observation: Observation):
        actor_list = self.__world.get_actors()

        for agent_id, agent in self.__agents.items():
            action = agent.next_action(observation)
            control = carla.VehicleControl()
            if action.acceleration >= 0:
                control.throttle = min(1., action.acceleration)
                control.brake = 0.
            else:
                control.throttle = 0.
                control.brake = min(-action.acceleration, 1.)
            control.steer = action.steer_angle
            control.hand_brake = False
            control.manual_gear_shift = False

            actor = actor_list.find(self.__actor_ids[agent_id])
            actor.apply_control(control)

    def run(self, steps=200):
        """ Run the simulation for a number of time steps """
        for i in range(steps):
            self.step()