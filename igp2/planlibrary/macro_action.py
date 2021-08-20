import abc
import logging
from typing import Dict, List, Optional, Type, Tuple
from copy import copy
import numpy as np
from shapely.geometry import Point, LineString

from igp2.agentstate import AgentState
from igp2.opendrive.elements.road_lanes import Lane
from igp2.opendrive.map import Map
from igp2.planlibrary.maneuver import Maneuver, FollowLane, ManeuverConfig, SwitchLaneLeft, \
    SwitchLaneRight, SwitchLane, Turn, GiveWay
from igp2.trajectory import VelocityTrajectory
from igp2.util import all_subclasses
from igp2.vehicle import Action

logger = logging.getLogger(__name__)


class MacroAction(abc.ABC):
    """ Base class for all MacroActions. """

    def __init__(self, agent_id: int, frame: Dict[int, AgentState], scenario_map: Map, open_loop: bool = True,
                 **kwargs):
        """ Initialise a new MacroAction (MA)

        Args:
            agent_id: The ID of the agent, this MA is made for
            frame: The start state of the environment
            scenario_map: The road layout of the scenario
            open_loop: If True then use open loop control, else use closed loop control
        """
        self.open_loop = open_loop
        self.agent_id = agent_id
        self.start_frame = frame
        self.final_frame = None
        self.scenario_map = scenario_map

        self._maneuvers = self.get_maneuvers()  # TODO: Implement support for closed loop maneuvers
        self._current_maneuver = None

        # if not self.open_loop:
        #     self._current_maneuver = self._maneuvers[0]
        #     self._maneuvers = self._maneuvers[1:]

    def __repr__(self):
        return self.__class__.__name__

    @staticmethod
    def play_forward_macro_action(agent_id: int, scenario_map: Map,
                                  frame: Dict[int, AgentState], macro_action: "MacroAction"):
        """ Play forward current frame with the given macro action for the current agent.
        Assumes constant velocity lane follow behaviour for other agents.

        Args:
            agent_id: ID of the ego agent
            scenario_map: The road layout of the current scenario
            frame: The current frame of the environment
            macro_action: The macro action to play forward

        Returns:
            A new frame describing the future state of the environment
        """

        def _lane_at_distance(lane: Lane, ds: float) -> Tuple[Lane, float]:
            current_lane = lane
            total_length = 0.0
            while True:
                if total_length <= ds < total_length + current_lane.length:
                    return current_lane, ds - total_length
                total_length += current_lane.length
                successor = current_lane.link.successor
                if successor is None:
                    break
                current_lane = successor[0]
            logger.debug(f"No Lane found at distance {ds} for Agent ID{aid}!")
            return current_lane, current_lane.length

        if not macro_action:
            return frame

        trajectory = macro_action.get_trajectory()
        new_frame = {agent_id: trajectory.final_agent_state}
        duration = trajectory.duration
        for aid, agent in frame.items():
            if aid != agent_id:
                state = copy(agent)
                agent_lane = scenario_map.best_lane_at(agent.position, agent.heading)
                if agent_lane is None:
                    continue
                agent_distance = agent_lane.distance_at(agent.position) + duration * agent.speed
                final_lane, distance_in_lane = _lane_at_distance(agent_lane, agent_distance)
                state.position = final_lane.point_at(distance_in_lane)
                state.heading = final_lane.get_heading_at(distance_in_lane)
                new_frame[aid] = state
        return new_frame

    def get_maneuvers(self) -> List[Maneuver]:
        """ Calculate the sequence of maneuvers for this MacroAction. """
        raise NotImplementedError

    @staticmethod
    def applicable(state: AgentState, scenario_map: Map) -> bool:
        """ Return True if the macro action is applicable in the given state of the environment. """
        raise NotImplementedError

    def done(self, frame: Dict[int, AgentState], scenario_map: Map) -> bool:
        """ Returns True if the execution of the macro action has completed. """
        return len(self._maneuvers) == 0 and self._current_maneuver.done(frame, scenario_map)

    def next_action(self, frame: Dict[int, AgentState], scenario_map: Map) -> Action:
        """ Return the next action of a closed-loop macro action given by its current maneuver. If the current
        maneuver is done, then advance to the next maneuver. """
        if self.current_maneuver.done(frame, scenario_map):
            self._current_maneuver = self._maneuvers[1:]
        return self.current_maneuver.next_action(frame, scenario_map)

    def get_trajectory(self) -> VelocityTrajectory:
        """ If open_loop is True then get the complete trajectory of the macro action.

        Returns:
            A VelocityTrajectory that describes the complete open loop trajectory of the macro action
        """
        if not self.open_loop:
            raise ValueError("Cannot get trajectory of closed-loop macro action!")
        if self._maneuvers is None:
            raise ValueError("Maneuver sequence of macro action was not initialised!")

        points = None
        velocity = None
        for maneuver in self._maneuvers:
            trajectory = maneuver.trajectory
            points = trajectory.path if points is None else np.append(points, trajectory.path[1:], axis=0)
            velocity = trajectory.velocity if velocity is None else np.append(velocity, trajectory.velocity[1:], axis=0)
        return VelocityTrajectory(points, velocity)

    @staticmethod
    def get_applicable_actions(agent_state: AgentState, scenario_map: Map) -> List[Type['MacroAction']]:
        """ Return all applicable macro actions.

        Args:
            agent_state: Current state of the examined agent
            scenario_map: The road layout of the scenario

        Returns:
            A list of applicable macro action types
        """
        actions = []
        for macro_action in all_subclasses(MacroAction):
            try:
                if macro_action.applicable(agent_state, scenario_map):
                    actions.append(macro_action)
            except NotImplementedError:
                continue
        return actions

    @staticmethod
    def get_possible_args(state: AgentState, scenario_map: Map, goal_point: np.ndarray = None) -> List[Dict]:
        """ Return a list of keyword arguments used to initialise all possible variations of a macro action.
        Currently, only Exit returns more than one option, giving the Exits to all possible leaving points.

        Args:
            state: Current state of the agent
            scenario_map: The road layout of the scenario
            goal_point: Optional goal point to use during AStar planning

        Returns:
            A list of possible initialisations in the current state
        """
        return [{}]

    @property
    def maneuvers(self):
        """ The complete maneuver sequence of the macro action. """
        return self._maneuvers

    @property
    def current_maneuver(self) -> Maneuver:
        """ The current maneuver being executed during closed loop control. """
        return self._current_maneuver


class Continue(MacroAction):
    """ Follow the current lane until the given point or to the end of the lane. """

    def __init__(self, agent_id: int, frame: Dict[int, AgentState], scenario_map: Map, open_loop: bool = True,
                 termination_point: Point = None):
        """ Initialise a new Continue MA.

        Args:
            termination_point: The optional point of termination
        """
        self.termination_point = termination_point
        super().__init__(agent_id, frame, scenario_map, open_loop)

    def get_maneuvers(self) -> List[Maneuver]:
        state = self.start_frame[self.agent_id]
        maneuvers = []
        if self.open_loop:
            current_lane = self.scenario_map.best_lane_at(state.position, state.heading)
            endpoint = self.termination_point
            if endpoint is None:
                endpoint = current_lane.midline.interpolate(1, normalized=True)
            config_dict = {
                "type": "follow-lane",
                "termination_point": np.array(endpoint.coords[0])
            }
            config = ManeuverConfig(config_dict)
            maneuvers = [FollowLane(config, self.agent_id, self.start_frame, self.scenario_map)]
            self.final_frame = Maneuver.play_forward_maneuver(self.agent_id, self.scenario_map,
                                                              self.start_frame, maneuvers[-1])
        return maneuvers

    @staticmethod
    def applicable(state: AgentState, scenario_map: Map) -> bool:
        """ True if vehicle on a lane, and not approaching junction or not in junction"""
        in_junction = scenario_map.best_lane_at(state.position, state.heading).parent_road.junction is not None
        return (FollowLane.applicable(state, scenario_map) and not in_junction and
                not GiveWay.applicable(state, scenario_map))

    @staticmethod
    def get_possible_args(state: AgentState, scenario_map: Map, goal_point: np.ndarray = None) -> List[Dict]:
        """ Return empty dictionary if no goal point is provided, otherwise check if goal point in lane and
        return center of goal point as termination point. """
        if goal_point is not None:
            current_lane = scenario_map.best_lane_at(state.position, state.heading)
            goal_lanes = scenario_map.lanes_at(goal_point, max_distance=0.5)
            if current_lane in goal_lanes:
                return [{"termination_point": Point(goal_point)}]
        return [{}]


class ContinueNextExit(MacroAction):
    """ Continue in the non-outer lane of a roundabout until after the next junction. """

    def get_maneuvers(self) -> List[Maneuver]:
        state = self.start_frame[self.agent_id]
        maneuvers = []
        if self.open_loop:

            # First go till end of current lane
            frame = self.start_frame
            current_lane = self.scenario_map.best_lane_at(state.position, state.heading)
            endpoint = current_lane.midline.interpolate(1, normalized=True)
            config_dict = {
                "type": "follow-lane",
                "termination_point": np.array(endpoint.coords[0])
            }
            config = ManeuverConfig(config_dict)
            man = FollowLane(config, self.agent_id, frame, self.scenario_map)
            maneuvers.append(man)
            frame = Maneuver.play_forward_maneuver(self.agent_id, self.scenario_map, frame, maneuvers[-1])

            # Then go straight through the roundabout junction
            turn_lane = current_lane.link.successor[0]
            endpoint = turn_lane.midline.interpolate(1, normalized=True)
            config_dict = {
                "type": "turn",
                "termination_point": np.array(endpoint.coords[0]),
                "junction_lane_id": turn_lane.id,
                "junction_road_id": turn_lane.parent_road.id
            }
            config = ManeuverConfig(config_dict)
            man = Turn(config, self.agent_id, frame, self.scenario_map)
            maneuvers.append(man)
            self.final_frame = Maneuver.play_forward_maneuver(self.agent_id, self.scenario_map, frame, maneuvers[-1])
        return maneuvers

    @staticmethod
    def applicable(state: AgentState, scenario_map: Map) -> bool:
        """ True if in non-outer lane of roundabout and not in junction """
        current_lane = scenario_map.best_lane_at(state.position, state.heading)
        all_lane_ids = [lane.id for lane in current_lane.lane_section.all_lanes if lane != current_lane]
        return (scenario_map.in_roundabout(state.position, state.heading) and
                current_lane.parent_road.junction is None and  # TODO: Assume cannot continue to next exit while going through junction
                not all([np.abs(current_lane.id) > np.abs(lid) for lid in all_lane_ids]) and  # Not in outer lane
                FollowLane.applicable(state, scenario_map))


class ChangeLane(MacroAction):
    CHECK_ONCOMING = False

    def __init__(self, left: bool, agent_id: int, frame: Dict[int, AgentState],
                 scenario_map: Map, open_loop: bool = True):
        self.left = left
        super(ChangeLane, self).__init__(agent_id, frame, scenario_map, open_loop)

    def get_maneuvers(self) -> List[Maneuver]:
        maneuvers = []
        state = self.start_frame[self.agent_id]
        current_lane = self.scenario_map.best_lane_at(state.position, state.heading)
        current_distance = current_lane.distance_at(state.position)
        target_lane_sequence = self._get_lane_sequence(state, current_lane, SwitchLane.TARGET_SWITCH_LENGTH)
        target_midline = self._get_lane_sequence_midline(target_lane_sequence)

        if self.open_loop:
            frame = self.start_frame
            d_change = SwitchLane.TARGET_SWITCH_LENGTH
            lane_follow_end_point = state.position

            # Check for oncoming vehicles and free sections in target lane if flag is set
            if ChangeLane.CHECK_ONCOMING:
                oncoming_intervals = self._get_oncoming_vehicle_intervals(target_lane_sequence, target_midline)
                t_lane_end = (target_midline.length - target_midline.project(Point(state.position))) / state.speed

                # Get first time when lane change is possible
                while d_change >= SwitchLane.MIN_SWITCH_LENGTH:
                    t_change = d_change / state.speed
                    t_start = 0.0  # Count from time of start_frame
                    for iv_start, iv_end, d_distance in oncoming_intervals:
                        if np.abs(d_distance) < d_change and t_start < iv_end and iv_start < t_start + t_change:
                            t_start = iv_end

                    if t_start + t_change >= t_lane_end:
                        d_change -= 5  # Try lane change with shorter length
                    else:
                        break
                else:
                    assert False, "Cannot finish lane change until end of current lane!"

                # Follow lane until target lane is clear
                distance_until_change = t_start * state.speed  # Maneuver.MAX_SPEED
                lane_follow_end_distance = current_distance + distance_until_change
                if t_start > 0.0:
                    lane_follow_end_point = current_lane.point_at(lane_follow_end_distance)
                    config_dict = {
                        "type": "follow-lane",
                        "termination_point": lane_follow_end_point
                    }
                    config = ManeuverConfig(config_dict)
                    man = FollowLane(config, self.agent_id, frame, self.scenario_map)
                    maneuvers.append(man)
                    frame = Maneuver.play_forward_maneuver(self.agent_id, self.scenario_map, frame, man)

            # Create switch lane maneuver
            config_dict = {
                "type": "switch-" + "left" if self.left else "right",
                "termination_point": target_midline.interpolate(
                    target_midline.project(Point(lane_follow_end_point)) + d_change)
            }
            config = ManeuverConfig(config_dict)
            if self.left:
                maneuvers.append(SwitchLaneLeft(config, self.agent_id, frame, self.scenario_map))
            else:
                maneuvers.append(SwitchLaneRight(config, self.agent_id, frame, self.scenario_map))
            self.final_frame = Maneuver.play_forward_maneuver(self.agent_id, self.scenario_map, frame, maneuvers[-1])
        return maneuvers

    def _get_oncoming_vehicle_intervals(self, target_lane_sequence: List[Lane], target_midline: LineString):
        oncoming_intervals = []
        state = self.start_frame[self.agent_id]
        for aid, agent in self.start_frame.items():
            if self.agent_id == aid:
                continue

            agent_lanes = self.scenario_map.lanes_at(agent.position)
            if any([l in target_lane_sequence for l in agent_lanes]):
                d_speed = state.speed - agent.speed
                d_distance = target_midline.project(Point(agent.position)) - \
                             target_midline.project(Point(state.position))

                # If heading in same direction and with same speed, then check if the distance allows for a lone change
                if np.isclose(d_speed, 0.0):
                    if np.abs(d_distance) < SwitchLane.MIN_SWITCH_LENGTH:
                        raise RuntimeError("Lane change is blocked by vehicle with same velocity in neighbouring lane.")
                    continue

                time_until_pass = d_distance / d_speed
                pass_time = np.abs(SwitchLane.MIN_SWITCH_LENGTH / d_speed)
                interval_end_time = time_until_pass + pass_time

                if interval_end_time > 0:
                    interval_start_time = max(0, time_until_pass - pass_time)
                    oncoming_intervals.append((interval_start_time, interval_end_time, d_distance))

        oncoming_intervals = sorted(oncoming_intervals, key=lambda period: period[0])
        return oncoming_intervals

    def _get_target_lane(self, current_lane: Lane) -> Lane:
        # Get target lane based on direction, lane change side and current lane ID
        tid = current_lane.id + (1 if np.sign(current_lane.id) > 0 else -1) * (-1 if self.left else 1)
        return current_lane.lane_section.get_lane(tid)

    def _get_lane_sequence(self, state: AgentState, current_lane: Lane, threshold: float) -> List[Lane]:
        # Allows lane changes through multiple lane sections.
        ls = []
        distance = -current_lane.distance_at(state.position)
        while current_lane is not None and distance <= threshold:
            distance += current_lane.length

            target_lane = self._get_target_lane(current_lane)
            if target_lane is None or target_lane.id == 0:
                break
            ls.append(target_lane)

            # Find successor lane to continue iteration
            successors = current_lane.link.successor
            if successors is None:
                current_lane = None
            elif len(successors) == 1:
                current_lane = current_lane.link.successor[0]

            # If more than one successor exists, select the appropriate one
            elif len(successors) > 1:
                # Find all lanes with more than one neighbour
                possible_lanes = [s for s in successors if len(self.scenario_map.get_adjacent_lanes(s, True, True)) > 0]
                if len(possible_lanes) == 0:
                    current_lane = None
                elif len(possible_lanes) == 1:
                    current_lane = possible_lanes[0]

                # Allow possible lane change through roundabout junctions only
                elif len(possible_lanes) > 1 and self.scenario_map.road_in_roundabout(current_lane.parent_road):
                    for lane in possible_lanes:
                        if self.scenario_map.road_in_roundabout(lane.parent_road):
                            current_lane = lane
                            break
                    else:
                        current_lane = None
        return ls

    def _get_lane_sequence_midline(self, lane_sequence: List[Lane]) -> LineString:
        final_point = lane_sequence[-1].midline.coords[-1]
        midline_points = [p for l in lane_sequence for p in l.midline.coords[:-1]] + [final_point]
        lane_ls = LineString(midline_points)
        return lane_ls

    @staticmethod
    def check_change_validity(state: AgentState, scenario_map: Map) -> bool:
        """ True if current lane not in junction, or at appropriate distance from a junction """
        in_junction = scenario_map.junction_at(state.position) is not None
        if in_junction:
            return False

        # Disallow lane changes if close to junction as could enter junction boundary by the end of the lane change.
        # Unless currently in a non-junction roundabout lane where we can pass directly through junction
        current_lane = scenario_map.best_lane_at(state.position, state.heading)
        successor = current_lane.link.successor
        if successor is not None:
            successor_distances = [(s.boundary.distance(Point(state.position)), s) for s in successor]
            distance_to_successor, nearest_successor = min(successor_distances, key=lambda x: x[0])

            # All connecting roads are single laned then check if at least minimum change length available
            if all([len(lane.lane_section.all_lanes) <= 2 for lane in successor]):
                return distance_to_successor > SwitchLane.MIN_SWITCH_LENGTH
            elif nearest_successor.parent_road.junction is not None:
                return distance_to_successor > SwitchLane.TARGET_SWITCH_LENGTH or \
                       scenario_map.road_in_roundabout(current_lane.parent_road)
        else:
            return True


class ChangeLaneLeft(ChangeLane):
    def __init__(self, agent_id: int, frame: Dict[int, AgentState], scenario_map: Map, open_loop: bool = True):
        super(ChangeLaneLeft, self).__init__(True, agent_id, frame, scenario_map, open_loop)

    @staticmethod
    def applicable(state: AgentState, scenario_map: Map) -> bool:
        """ True if valid target lane on the left and lane change is valid. """
        return SwitchLaneLeft.applicable(state, scenario_map) and \
               ChangeLane.check_change_validity(state, scenario_map)


class ChangeLaneRight(ChangeLane):
    def __init__(self, agent_id: int, frame: Dict[int, AgentState], scenario_map: Map, open_loop: bool = True):
        super(ChangeLaneRight, self).__init__(False, agent_id, frame, scenario_map, open_loop)

    @staticmethod
    def applicable(state: AgentState, scenario_map: Map) -> bool:
        """ True if valid target lane on the right and lane change is valid. """
        return SwitchLaneRight.applicable(state, scenario_map) and \
               ChangeLane.check_change_validity(state, scenario_map)


class Exit(MacroAction):
    GIVE_WAY_DISTANCE = 10  # Begin give-way if closer than this value to the junction
    LANE_ANGLE_THRESHOLD = np.pi / 9  # The maximum angular distance between the current heading the heading of a lane
    TURN_TARGET_THRESHOLD = 1  # Threshold for checking if turn target is within distance of another point

    def __init__(self, turn_target: np.ndarray, agent_id: int, frame: Dict[int, AgentState],
                 scenario_map: Map, open_loop: bool = True):
        self.turn_target = turn_target
        super(Exit, self).__init__(agent_id, frame, scenario_map, open_loop)

    def get_maneuvers(self) -> List[Maneuver]:
        maneuvers = []
        state = self.start_frame[self.agent_id]
        in_junction = self.scenario_map.junction_at(state.position) is not None
        current_lane = self._find_current_lane(state, in_junction)
        current_distance = current_lane.distance_at(state.position)

        if self.open_loop:
            frame = self.start_frame

            connecting_lane = current_lane
            if not in_junction:
                # Follow lane until start of turn if outside of give-way distance
                if current_lane.length - current_distance > self.GIVE_WAY_DISTANCE + Maneuver.POINT_SPACING:
                    distance_of_termination = current_lane.length - self.GIVE_WAY_DISTANCE
                    lane_follow_termination = current_lane.point_at(distance_of_termination)
                    config_dict = {
                        "type": "follow-lane",
                        "termination_point": lane_follow_termination
                    }
                    config = ManeuverConfig(config_dict)
                    man = FollowLane(config, self.agent_id, frame, self.scenario_map)
                    maneuvers.append(man)
                    frame = Maneuver.play_forward_maneuver(self.agent_id, self.scenario_map, frame, man)

                connecting_lane = self._find_connecting_lane(current_lane)

                # Add give-way maneuver
                config_dict = {
                    "type": "give-way",
                    "termination_point": current_lane.midline.coords[-1],
                    "junction_road_id": connecting_lane.parent_road.id,
                    "junction_lane_id": connecting_lane.id
                }
                config = ManeuverConfig(config_dict)
                man = GiveWay(config, self.agent_id, frame, self.scenario_map)
                maneuvers.append(man)
                frame = Maneuver.play_forward_maneuver(self.agent_id, self.scenario_map, frame, man)

            # Add turn
            config_dict = {
                "type": "turn",
                "termination_point": self.turn_target,
                "junction_road_id": connecting_lane.parent_road.id,
                "junction_lane_id": connecting_lane.id
            }
            config = ManeuverConfig(config_dict)
            maneuvers.append(Turn(config, self.agent_id, frame, self.scenario_map))
            self.final_frame = Maneuver.play_forward_maneuver(self.agent_id, self.scenario_map, frame, maneuvers[-1])

        return maneuvers

    def _nearest_lane_to_goal(self, lane_list: List[Lane]) -> Lane:
        best_lane = None
        best_distance = np.inf
        for connecting_lane in lane_list:
            distance = np.linalg.norm(self.turn_target - np.array(connecting_lane.midline.coords[-1]))
            if distance < self.TURN_TARGET_THRESHOLD and distance < best_distance:
                best_lane = connecting_lane
                best_distance = distance
        return best_lane

    def _find_current_lane(self, state: AgentState, in_junction: bool) -> Lane:
        if not in_junction:
            return self.scenario_map.best_lane_at(state.position, state.heading)
        all_lanes = self.scenario_map.lanes_at(state.position, max_distance=0.5)
        return self._nearest_lane_to_goal(all_lanes)

    def _find_connecting_lane(self, current_lane: Lane) -> Optional[Lane]:
        return self._nearest_lane_to_goal(current_lane.link.successor)

    @staticmethod
    def applicable(state: AgentState, scenario_map: Map) -> bool:
        """ True if either Turn (in junction) or GiveWay is applicable (ahead of junction) """
        in_junction = scenario_map.junction_at(state.position) is not None
        # Uncomment the following to disallow turns from inner lanes of a roundabout
        # if ContinueNextExit.applicable(state, scenario_map):
        #     return False
        if in_junction:
            return Turn.applicable(state, scenario_map)
        else:
            return GiveWay.applicable(state, scenario_map)

    @staticmethod
    def get_possible_args(state: AgentState, scenario_map: Map, goal_point: np.ndarray = None) -> List[Dict]:
        """ Return turn endpoint if approaching junction; if in junction
        return all possible turns within angle threshold"""
        targets = []
        in_junction = scenario_map.junction_at(state.position) is not None

        if in_junction:
            lanes = scenario_map.lanes_within_angle(state.position, state.heading,
                                                    Exit.LANE_ANGLE_THRESHOLD, max_distance=0.5)
            if not lanes:
                lanes = [scenario_map.best_lane_at(state.position, state.heading, drivable_only=True)]
            for lane in lanes:
                target = np.array(lane.midline.coords[-1])
                if not any([np.allclose(p, target, atol=0.25) for p in targets]):
                    targets.append(target)
        else:
            current_lane = scenario_map.best_lane_at(state.position, state.heading)
            for connecting_lane in current_lane.link.successor:
                if not scenario_map.road_in_roundabout(connecting_lane.parent_road):
                    targets.append(np.array(connecting_lane.midline.coords[-1]))

        return [{"turn_target": t} for t in targets]
