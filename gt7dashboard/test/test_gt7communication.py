import os
import struct
import time
import unittest

from Crypto.Cipher import Salsa20

from gt7dashboard import gt7communication
from gt7dashboard.gt7lap import Lap

PLAYSTATION_IP = os.environ.get("GT7_PLAYSTATION_IP", "ps5wifi")
RUN_INTEGRATION_TESTS = os.environ.get(
    "GT7_RUN_INTEGRATION_TESTS", ""
).lower() in {"1", "true", "yes"}


class RecordingSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, address):
        self.sent.append((data, address))


def encrypt_packet(plaintext, xor_key, iv1=0x12345678):
    """Create a GT7-compatible encrypted packet for decoder tests."""
    nonce = struct.pack('<II', iv1 ^ xor_key, iv1)
    cipher = Salsa20.new(b'Simulator Interface Packet GT7 ver 0.0'[:32], nonce)
    encrypted = bytearray(cipher.encrypt(plaintext))
    # GT7 exposes this nonce seed in the UDP packet so that clients can decrypt it.
    encrypted[0x40:0x44] = struct.pack('<I', iv1)
    return bytes(encrypted)


def packet_for_format(packet_format, magic=gt7communication.PACKET_MAGIC):
    packet_size, xor_key = gt7communication.PACKET_FORMATS[packet_format]
    plaintext = bytearray(packet_size)
    struct.pack_into('<I', plaintext, 0x00, magic)
    struct.pack_into('<I', plaintext, 0x70, 42)
    return encrypt_packet(plaintext, xor_key)


class PacketDecoderTest(unittest.TestCase):
    def record_extension_packet(self, packet_format):
        packet_size, xor_key = gt7communication.PACKET_FORMATS[packet_format]
        plaintext = bytearray(packet_size)
        struct.pack_into('<I', plaintext, 0x00, gt7communication.PACKET_MAGIC)
        struct.pack_into('<I', plaintext, 0x70, 42)
        struct.pack_into('<fffff', plaintext, 0x128, 1.25, 2.5, -3.75, 4.0, 5.5)

        if packet_format in ('~', 'C'):
            plaintext[0x13C:0x13E] = bytes((128, 64))
            struct.pack_into('<ffff', plaintext, 0x140, 1.0, -2.0, 3.0, -4.0)
            struct.pack_into('<f', plaintext, 0x150, 0.75)

        if packet_format == 'C':
            plaintext[0x158:0x15C] = b'TCGS'
            struct.pack_into('<I', plaintext, 0x15C, 91234)
            struct.pack_into('<ff', plaintext, 0x160, -0.25, 0.5)
            struct.pack_into('<f', plaintext, 0x168, 2.65)
            plaintext[0x16C:0x170] = b'GR3\0'

        data = gt7communication.GTData(
            gt7communication.salsa20_dec(encrypt_packet(plaintext, xor_key))
        )
        data.in_race = True
        communication = gt7communication.GT7Communication('192.0.2.1')
        communication._log_data(data)
        return communication.current_lap

    def test_decodes_each_known_packet_format(self):
        for packet_format in gt7communication.PACKET_FORMATS:
            with self.subTest(packet_format=packet_format):
                decoded = gt7communication.salsa20_dec(packet_for_format(packet_format))
                self.assertIsNotNone(decoded)
                self.assertEqual(gt7communication.PACKET_MAGIC,
                                 struct.unpack('<I', decoded[0:4])[0])
                self.assertEqual(
                    packet_format,
                    gt7communication.PACKET_FORMATS_BY_SIZE[len(decoded)][0],
                )

    def test_rejects_unknown_size_and_invalid_magic(self):
        self.assertIsNone(gt7communication.salsa20_dec(b'not a GT7 packet'))
        self.assertIsNone(gt7communication.salsa20_dec(packet_for_format('C', 0)))

    def test_decodes_packet_c_fields(self):
        packet_size, xor_key = gt7communication.PACKET_FORMATS['C']
        plaintext = bytearray(packet_size)
        struct.pack_into('<I', plaintext, 0x00, gt7communication.PACKET_MAGIC)
        struct.pack_into('<I', plaintext, 0x70, 42)
        struct.pack_into('<fffff', plaintext, 0x128, 1.25, 2.5, -3.75, 4.0, 5.5)
        plaintext[0x13C:0x13E] = bytes((128, 64))
        struct.pack_into('<ffff', plaintext, 0x140, 1.0, -2.0, 3.0, -4.0)
        struct.pack_into('<f', plaintext, 0x150, 0.75)
        plaintext[0x158:0x15C] = b'TCGS'
        struct.pack_into('<I', plaintext, 0x15C, 91234)
        struct.pack_into('<ff', plaintext, 0x160, -0.25, 0.5)
        struct.pack_into('<f', plaintext, 0x168, 2.65)
        plaintext[0x16C:0x170] = b'GR3\0'

        decoded = gt7communication.salsa20_dec(encrypt_packet(plaintext, xor_key))
        data = gt7communication.GTData(decoded)

        self.assertEqual('C', data.packet_format)
        self.assertEqual(('T', 'C', 'G', 'S'), data.surface_type)
        self.assertEqual(91234, data.current_lap_time_ms)
        self.assertAlmostEqual(-0.25, data.front_wheel_steering_angle_rad[0])
        self.assertAlmostEqual(0.5, data.front_wheel_steering_angle_rad[1])
        self.assertAlmostEqual(2.65, data.wheel_base_m, places=6)
        self.assertEqual('GR3', data.car_category)
        self.assertAlmostEqual(1.25, data.wheel_rotation_rad)
        self.assertAlmostEqual(2.5, data.steering_angular_velocity_rad_s)
        self.assertAlmostEqual(-3.75, data.sway_acceleration)
        self.assertAlmostEqual(4.0, data.heave_acceleration)
        self.assertAlmostEqual(5.5, data.surge_acceleration)
        self.assertAlmostEqual(128 / 2.55, data.throttle_filtered_percent)
        self.assertAlmostEqual(64 / 2.55, data.brake_filtered_percent)
        self.assertEqual((1.0, -2.0, 3.0, -4.0), data.torque_vectors)
        self.assertAlmostEqual(0.75, data.energy_recovery)

    def test_decodes_packet_b_fields(self):
        packet_size, xor_key = gt7communication.PACKET_FORMATS['B']
        plaintext = bytearray(packet_size)
        struct.pack_into('<I', plaintext, 0x00, gt7communication.PACKET_MAGIC)
        struct.pack_into('<I', plaintext, 0x70, 42)
        struct.pack_into('<fffff', plaintext, 0x128, 1.25, 2.5, -3.75, 4.0, 5.5)

        data = gt7communication.GTData(
            gt7communication.salsa20_dec(encrypt_packet(plaintext, xor_key))
        )

        self.assertEqual('B', data.packet_format)
        self.assertAlmostEqual(1.25, data.wheel_rotation_rad)
        self.assertAlmostEqual(2.5, data.steering_angular_velocity_rad_s)
        self.assertAlmostEqual(-3.75, data.sway_acceleration)
        self.assertAlmostEqual(4.0, data.heave_acceleration)
        self.assertAlmostEqual(5.5, data.surge_acceleration)
        self.assertIsNone(data.throttle_filtered_percent)

    def test_decodes_packet_tilde_fields(self):
        packet_size, xor_key = gt7communication.PACKET_FORMATS['~']
        plaintext = bytearray(packet_size)
        struct.pack_into('<I', plaintext, 0x00, gt7communication.PACKET_MAGIC)
        struct.pack_into('<I', plaintext, 0x70, 42)
        plaintext[0x13C:0x13E] = bytes((128, 64))
        struct.pack_into('<ffff', plaintext, 0x140, 1.0, -2.0, 3.0, -4.0)
        struct.pack_into('<f', plaintext, 0x150, 0.75)

        data = gt7communication.GTData(
            gt7communication.salsa20_dec(encrypt_packet(plaintext, xor_key))
        )

        self.assertEqual('~', data.packet_format)
        self.assertAlmostEqual(128 / 2.55, data.throttle_filtered_percent)
        self.assertAlmostEqual(64 / 2.55, data.brake_filtered_percent)
        self.assertEqual((1.0, -2.0, 3.0, -4.0), data.torque_vectors)
        self.assertAlmostEqual(0.75, data.energy_recovery)
        self.assertIsNone(data.surface_type)

    def test_a_packet_keeps_c_fields_empty(self):
        data = gt7communication.GTData(gt7communication.salsa20_dec(packet_for_format('A')))
        self.assertEqual('A', data.packet_format)
        self.assertIsNone(data.wheel_rotation_rad)
        self.assertIsNone(data.throttle_filtered_percent)
        self.assertIsNone(data.surface_type)
        self.assertIsNone(data.current_lap_time_ms)

    def test_records_packet_b_extension_fields_in_lap(self):
        lap = self.record_extension_packet('B')

        self.assertEqual('B', lap.telemetry_packet_format)
        self.assertEqual([1.25], lap.data_wheel_rotation_rad)
        self.assertEqual([2.5], lap.data_steering_angular_velocity_rad_s)
        self.assertEqual([-3.75], lap.data_sway_acceleration)
        self.assertEqual([4.0], lap.data_heave_acceleration)
        self.assertEqual([5.5], lap.data_surge_acceleration)
        self.assertEqual([None], lap.data_throttle_filtered_percent)
        self.assertEqual([None], lap.data_surface_type_fl)

    def test_records_packet_tilde_extension_fields_in_lap(self):
        lap = self.record_extension_packet('~')

        self.assertEqual('~', lap.telemetry_packet_format)
        self.assertEqual([1.25], lap.data_wheel_rotation_rad)
        self.assertEqual([128 / 2.55], lap.data_throttle_filtered_percent)
        self.assertEqual([64 / 2.55], lap.data_brake_filtered_percent)
        self.assertEqual([1.0], lap.data_torque_vector_fl)
        self.assertEqual([-2.0], lap.data_torque_vector_fr)
        self.assertEqual([3.0], lap.data_torque_vector_rl)
        self.assertEqual([-4.0], lap.data_torque_vector_rr)
        self.assertEqual([0.75], lap.data_energy_recovery)
        self.assertEqual([None], lap.data_surface_type_fl)

    def test_records_packet_c_extension_fields_in_lap(self):
        lap = self.record_extension_packet('C')

        self.assertEqual('C', lap.telemetry_packet_format)
        self.assertEqual([1.25], lap.data_wheel_rotation_rad)
        self.assertEqual([128 / 2.55], lap.data_throttle_filtered_percent)
        self.assertEqual([1.0], lap.data_torque_vector_fl)
        self.assertEqual(['T'], lap.data_surface_type_fl)
        self.assertEqual(['C'], lap.data_surface_type_fr)
        self.assertEqual(['G'], lap.data_surface_type_rl)
        self.assertEqual(['S'], lap.data_surface_type_rr)
        self.assertEqual([91234], lap.data_current_lap_time_ms)
        self.assertEqual([-0.25], lap.data_front_left_steering_angle_rad)
        self.assertEqual([0.5], lap.data_front_right_steering_angle_rad)
        self.assertAlmostEqual(2.65, lap.wheel_base_m, places=6)
        self.assertEqual('GR3', lap.car_category)

    def test_packet_format_selects_heartbeat(self):
        socket = RecordingSocket()
        communication = gt7communication.GT7Communication('192.0.2.1', 'C')
        communication._send_hb(socket)
        self.assertEqual([(b'C', ('192.0.2.1', 33739))], socket.sent)

    def test_packet_format_validation(self):
        self.assertEqual('C', gt7communication.normalise_packet_format(' c '))
        with self.assertRaises(ValueError):
            gt7communication.GT7Communication('192.0.2.1', 'D')

    def test_mixed_packet_formats_keep_extension_series_aligned(self):
        communication = gt7communication.GT7Communication('192.0.2.1')
        for packet_format in ('B', 'C'):
            packet_size, xor_key = gt7communication.PACKET_FORMATS[packet_format]
            plaintext = bytearray(packet_size)
            struct.pack_into('<I', plaintext, 0x00, gt7communication.PACKET_MAGIC)
            struct.pack_into('<I', plaintext, 0x70, 42)
            struct.pack_into('<fffff', plaintext, 0x128, 1.25, 2.5, 3.75, 4.0, 5.5)
            if packet_format == 'C':
                plaintext[0x158:0x15C] = b'TCGS'
            data = gt7communication.GTData(
                gt7communication.salsa20_dec(encrypt_packet(plaintext, xor_key))
            )
            data.in_race = True
            communication._log_data(data)

        lap = communication.current_lap
        self.assertEqual('mixed', lap.telemetry_packet_format)
        self.assertEqual(len(lap.data_time), len(lap.data_wheel_rotation_rad))
        self.assertEqual(len(lap.data_time), len(lap.data_surface_type_fl))
        self.assertEqual([None, 'T'], lap.data_surface_type_fl)

    def test_discards_extension_series_that_are_entirely_unavailable(self):
        lap = self.record_extension_packet('B')
        self.assertEqual([None], lap.data_surface_type_fl)
        lap.discard_unavailable_extension_data()
        self.assertEqual([], lap.data_surface_type_fl)
        self.assertEqual([1.25], lap.data_wheel_rotation_rad)


@unittest.skipUnless(
    RUN_INTEGRATION_TESTS,
    "Set GT7_RUN_INTEGRATION_TESTS=true to run tests against a live Playstation",
)
class GT7CommunicationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        packet_format = os.environ.get("GT7_PACKET_FORMAT", "A")
        cls.gt7comm = gt7communication.GT7Communication(
            PLAYSTATION_IP, packet_format
        )
        cls.gt7comm.start()
        deadline = time.monotonic() + float(
            os.environ.get("GT7_INTEGRATION_TIMEOUT_SECONDS", "15")
        )
        while not cls.gt7comm.is_connected() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not cls.gt7comm.is_connected():
            cls.gt7comm.stop()
            raise TimeoutError(
                f"No GT7 telemetry received from {PLAYSTATION_IP} "
                f"in packet format {packet_format} before the timeout"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.gt7comm.stop()

    def test_get_water_temp(self):
        car_data = self.gt7comm.get_last_data()
        self.assertTrue(self.gt7comm.is_connected())
        # is always 85
        self.assertEqual(85, car_data.water_temp)

    # def test_run_add_debug(self):
    #     while self.gt7comm.is_connected():
    #         car_data = self.gt7comm.get_last_data()
    #         # print(car_data.rpm, car_data.in_race)

    def test_load_laps(self):
        self.gt7comm.laps = [Lap()]
        self.gt7comm.laps[0].number = 0

        laps = [Lap(), Lap()]
        laps[0].number = 1
        laps[1].number = 2

        self.gt7comm.load_laps(laps, to_last_position=True)
        self.assertEqual(3, len(self.gt7comm.laps))
        self.assertEqual(1, self.gt7comm.laps[1].number)

        self.gt7comm.load_laps(laps, to_first_position=True)
        self.assertEqual(5, len(self.gt7comm.laps))
        self.assertEqual(1, self.gt7comm.laps[3].number)

        self.gt7comm.load_laps(laps, replace_other_laps=True)
        self.assertEqual(2, len(self.gt7comm.laps))
        self.assertEqual(1, self.gt7comm.laps[0].number)
