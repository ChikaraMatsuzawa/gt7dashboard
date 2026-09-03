from datetime import datetime
from gt7dashboard import gt7helper


class Lap:
    EXTENSION_DATA_ATTRIBUTES = (
        "data_wheel_rotation_rad",
        "data_steering_angular_velocity_rad_s",
        "data_sway_acceleration",
        "data_heave_acceleration",
        "data_surge_acceleration",
        "data_throttle_filtered_percent",
        "data_brake_filtered_percent",
        "data_torque_vector_fl",
        "data_torque_vector_fr",
        "data_torque_vector_rl",
        "data_torque_vector_rr",
        "data_energy_recovery",
        "data_surface_type_fl",
        "data_surface_type_fr",
        "data_surface_type_rl",
        "data_surface_type_rr",
        "data_current_lap_time_ms",
        "data_front_left_steering_angle_rad",
        "data_front_right_steering_angle_rad",
    )

    def __init__(self):
        # Nice title for lap
        self.title = ""
        # Number of all lap ticks
        self.lap_ticks = 1
        # Lap time after crossing the finish line
        self.lap_finish_time = 0
        # Live time during a live lap
        self.lap_live_time = 0
        # Total number of laps
        self.total_laps = 0
        # Number of current lap
        self.number = 0
        # Aggregated number of instances where condition is true
        self.throttle_and_brake_ticks = 0
        self.no_throttle_and_no_brake_ticks = 0
        self.full_brake_ticks = 0
        self.full_throttle_ticks = 0
        self.tires_overheated_ticks = 0
        self.tires_spinning_ticks = 0
        # Data points with value for every tick
        self.data_throttle = []
        self.data_braking = []
        self.data_coasting = []
        self.data_speed = []
        self.data_time = []
        self.data_rpm = []
        self.data_gear = []
        self.data_tires = []
        # Positions on x,y,z
        self.data_position_x = []
        self.data_position_y = []
        self.data_position_z = []
        # Fuel
        self.fuel_at_start = 0
        self.fuel_at_end = -1
        self.fuel_consumed = -1
        # Boost
        self.data_boost = []
        # Yaw Rate
        self.data_rotation_yaw = []
        self.data_absolute_yaw_rate_per_second = []

        # Packet B motion telemetry (one value per recorded packet)
        self.data_wheel_rotation_rad = []
        self.data_steering_angular_velocity_rad_s = []
        self.data_sway_acceleration = []
        self.data_heave_acceleration = []
        self.data_surge_acceleration = []

        # Packet ~ filtered-input and torque telemetry (one value per packet)
        self.data_throttle_filtered_percent = []
        self.data_brake_filtered_percent = []
        self.data_torque_vector_fl = []
        self.data_torque_vector_fr = []
        self.data_torque_vector_rl = []
        self.data_torque_vector_rr = []
        self.data_energy_recovery = []

        # Packet C telemetry (one value per recorded packet)
        self.data_surface_type_fl = []
        self.data_surface_type_fr = []
        self.data_surface_type_rl = []
        self.data_surface_type_rr = []
        self.data_current_lap_time_ms = []
        self.data_front_left_steering_angle_rad = []
        self.data_front_right_steering_angle_rad = []

        # Packet C car metadata and the format used to record this lap
        self.wheel_base_m = None
        self.car_category = None
        self.telemetry_packet_format = None

        # Car
        self.car_id = 0

        # Always record was set when recording the lap, likely a replay
        self.is_replay = False
        self.is_manual = False

        self.lap_start_timestamp = datetime.now()
        self.lap_end_timestamp = -1

    def discard_unavailable_extension_data(self):
        """Keep unsupported packet extensions compact in persisted lap JSON."""
        for attribute in self.EXTENSION_DATA_ATTRIBUTES:
            values = getattr(self, attribute)
            if values and all(value is None for value in values):
                setattr(self, attribute, [])

    def __str__(self):
        return "\n %s, %2d, %1.f, %4d, %4d, %4d" % (
            self.title,
            self.number,
            self.fuel_at_end,
            self.full_throttle_ticks,
            self.full_brake_ticks,
            self.no_throttle_and_no_brake_ticks,
        )

    def format(self):
        return "Lap %2d, %s (%d Ticks)" % (
            self.number,
            self.title,
            len(self.data_speed),
        )

    def get_speed_peaks_and_valleys(self):
        (
            peak_speed_data_x,
            peak_speed_data_y,
            valley_speed_data_x,
            valley_speed_data_y,
        ) = gt7helper.get_speed_peaks_and_valleys(self)

        return (
            peak_speed_data_x,
            peak_speed_data_y,
            valley_speed_data_x,
            valley_speed_data_y,
        )

    def car_name(self) -> str:
        # FIXME Breaking change. Not all log files up to this point have this attribute, remove this later
        if (not hasattr(self, "car_id")):
            return "Car not logged"
        return gt7helper.get_car_name_for_car_id(self.car_id)

    def get_data_dict(self, distance_mode=True) -> dict[str, list]:

        raceline_y_throttle, raceline_x_throttle, raceline_z_throttle = gt7helper.get_race_line_coordinates_when_mode_is_active(self, mode=gt7helper.RACE_LINE_THROTTLE_MODE)
        raceline_y_braking, raceline_x_braking, raceline_z_braking = gt7helper.get_race_line_coordinates_when_mode_is_active(self, mode=gt7helper.RACE_LINE_BRAKING_MODE)
        raceline_y_coasting, raceline_x_coasting, raceline_z_coasting = gt7helper.get_race_line_coordinates_when_mode_is_active(self, mode=gt7helper.RACE_LINE_COASTING_MODE)

        data = {
            "throttle": self.data_throttle,
            "brake": self.data_braking,
            "speed": self.data_speed,
            "time": self.data_time,
            "tires": self.data_tires,
            "rpm": self.data_rpm,
            "boost": self.data_boost,
            "yaw_rate": self.data_absolute_yaw_rate_per_second,
            "gear": self.data_gear,
            "ticks": list(range(len(self.data_speed))),
            "coast": self.data_coasting,
            "raceline_y": self.data_position_y,
            "raceline_x": self.data_position_x,
            "raceline_z": self.data_position_z,
            # For a raceline when throttle is engaged
            "raceline_y_throttle": raceline_y_throttle,
            "raceline_x_throttle": raceline_x_throttle,
            "raceline_z_throttle": raceline_z_throttle,
            # For a raceline when braking is engaged
            "raceline_y_braking": raceline_y_braking,
            "raceline_x_braking": raceline_x_braking,
            "raceline_z_braking": raceline_z_braking,
            # For a raceline when neither throttle nor brake is engaged
            "raceline_y_coasting": raceline_y_coasting,
            "raceline_x_coasting": raceline_x_coasting,
            "raceline_z_coasting": raceline_z_coasting,

            "distance": gt7helper.get_x_axis_depending_on_mode(self, distance_mode),
        }

        return data
