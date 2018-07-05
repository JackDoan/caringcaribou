from __future__ import print_function
from lib import iso14229_1, iso15765_2
from lib.can_actions import int_from_byte_list
import can
import time


class MockEcu:
    """Mock ECU base class, used for running tests over a virtual CAN bus"""

    DELAY_BEFORE_RESPONSE = 0.01

    def __init__(self, bus=None):
        if bus is None:
            self.bus = can.interface.Bus("test", bustype="virtual")
        else:
            self.bus = bus
        self.notifier = can.Notifier(self.bus, listeners=[])

    def __enter__(self):
        return self

    def add_listener(self, listener):
        self.notifier.listeners.append(listener)

    def clear_listeners(self):
        self.notifier.listeners = []

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.clear_listeners()
        # Prevent threading errors during shutdown
        self.notifier.running.clear()
        time.sleep(0.1)
        self.bus.shutdown()


class MockEcuIsoTp(MockEcu):
    """ISO-15765-2 (ISO-TP) mock ECU handler"""

    MOCK_SINGLE_FRAME_REQUEST = [0x01, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF]
    MOCK_SINGLE_FRAME_RESPONSE = list(range(0, 0x07))

    MOCK_MULTI_FRAME_TWO_MESSAGES_REQUEST = [0xC0, 0xFF, 0xEE, 0x00, 0x02, 0x00, 0x00]
    MOCK_MULTI_FRAME_TWO_MESSAGES_RESPONSE = list(range(0, 0x0D))

    MOCK_MULTI_FRAME_LONG_MESSAGE_REQUEST = [0x02, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F]
    MOCK_MULTI_FRAME_LONG_MESSAGE_RESPONSE = list(range(0, 34))

    def __init__(self, arb_id_request, arb_id_response, bus=None):
        MockEcu.__init__(self, bus)
        self.ARBITRATION_ID_REQUEST = arb_id_request
        self.ARBITRATION_ID_RESPONSE = arb_id_response
        self.iso_tp = iso15765_2.IsoTp(arb_id_request=self.ARBITRATION_ID_REQUEST,
                                       arb_id_response=self.ARBITRATION_ID_RESPONSE,
                                       bus=bus)

    def message_handler(self, message):
        """
        Logic for responding to incoming messages

        :param message: Incoming can.Message
        :return: None
        """
        assert isinstance(message, can.Message)
        if message.arbitration_id == self.ARBITRATION_ID_REQUEST:
            # Hack to decode data without running full indication
            _, data = self.iso_tp.decode_sf(message.data)
            # Simulate a small delay before responding
            time.sleep(self.DELAY_BEFORE_RESPONSE)
            if data == self.MOCK_SINGLE_FRAME_REQUEST:
                self.iso_tp.send_response(self.MOCK_SINGLE_FRAME_RESPONSE)
            elif data == self.MOCK_MULTI_FRAME_TWO_MESSAGES_REQUEST:
                self.iso_tp.send_response(self.MOCK_MULTI_FRAME_TWO_MESSAGES_RESPONSE)
            elif data == self.MOCK_MULTI_FRAME_LONG_MESSAGE_REQUEST:
                self.iso_tp.send_response(self.MOCK_MULTI_FRAME_LONG_MESSAGE_RESPONSE)
            else:
                print("Unmapped message in {0}.message_handler:\n  {1}".format(self.__class__.__name__, message))


class MockEcuIso14229(MockEcuIsoTp, MockEcu):
    """ISO-14229-1 (Unified Diagnostic Services) mock ECU handler"""

    IDENTIFIER_REQUEST_POSITIVE = 0x01
    IDENTIFIER_REQUEST_POSITIVE_RESPONSE = 0x72
    IDENTIFIER_REQUEST_NEGATIVE = 0x02

    REQUEST_IDENTIFIER_VALID = 0xA001
    REQUEST_IDENTIFIER_INVALID = 0xA002
    REQUEST_VALUE = [0xC0, 0xFF, 0xEE]

    REQUEST_ADDRESS_LENGTH_AND_FORMAT = 0x22
    REQUEST_ADDRESS = 0x0001
    REQUEST_DATA_SIZE = 0x10
    DATA = list(range(0x14))

    def __init__(self, arb_id_request, arb_id_response, bus=None):
        MockEcu.__init__(self, bus)
        self.ARBITRATION_ID_ISO_14229_REQUEST = arb_id_request
        self.ARBITRATION_ID_ISO_14229_RESPONSE = arb_id_response
        self.iso_tp = iso15765_2.IsoTp(arb_id_request=self.ARBITRATION_ID_ISO_14229_REQUEST,
                                       arb_id_response=self.ARBITRATION_ID_ISO_14229_RESPONSE,
                                       bus=bus)
        self.diagnostics = iso14229_1.Iso14229_1(tp=self.iso_tp)

    @staticmethod
    def create_positive_response(request_service_id, response_data=None):
        """
        Returns data for a positive response of 'request_service_id' with an optional 'response_data' payload

        :param request_service_id: Service ID (SIDRQ) of the incoming request
        :param response_data: List of data bytes to transmit in the response
        :return: List of bytes to be sent as data payload in the response
        """
        # Positive response uses a response service ID (SIDPR) based on the request service ID (SIDRQ)
        service_response_id = iso14229_1.Iso14229_1.get_service_response_id(request_service_id)
        response = [service_response_id]
        # Append payload
        if response_data is not None:
            response += response_data
        return response

    @staticmethod
    def create_negative_response(request_service_id, nrc):
        """
        Returns data for a negative response of 'request_service_id' with negative response code 'nrc'

        :param request_service_id: Service ID (SIDRQ) of the incoming request
        :param nrc: Negative response code (NRC_)
        :return: List of bytes to be sent as data payload in the response
        """
        response = [iso14229_1.Iso14229_1_id.NEGATIVE_RESPONSE,
                    request_service_id,
                    nrc]
        return response

    def message_handler(self, message):
        """
        Logic for responding to incoming messages

        :param message: Incoming can.Message
        :return: None
        """
        assert isinstance(message, can.Message)
        if message.arbitration_id == self.ARBITRATION_ID_ISO_14229_REQUEST:
            # Hack to decode data without running full indication
            _, data = self.iso_tp.decode_sf(message.data)
            iso14229_service = data[0]
            # Simulate a small delay before responding
            time.sleep(self.DELAY_BEFORE_RESPONSE)
            # Handle different services
            response_data = None
            if iso14229_service == iso14229_1.Iso14229_1_id.READ_DATA_BY_IDENTIFIER:
                # Read data by identifier
                response_data = self.handle_read_data_by_identifier(data)
            elif iso14229_service == iso14229_1.Iso14229_1_id.WRITE_DATA_BY_IDENTIFIER:
                # Write data by identifier
                response_data = self.handle_write_data_by_identifier(data)
            elif iso14229_service == iso14229_1.Iso14229_1_id.READ_MEMORY_BY_ADDRESS:
                # Read memory by address
                response_data = self.handle_read_memory_by_address(data)
            if response_data:
                self.diagnostics.send_response(response_data)
            else:
                print("Unmapped message in {0}.message_handler:\n  {1}".format(self.__class__.__name__, message))

    def handle_read_data_by_identifier(self, data):
        """
        Evaluates a read data by identifier request and returns the appropriate response

        :param data: Data from incoming request
        :return: Response to be sent
        """
        service_id = data[0]
        request = data[2]

        if request == self.IDENTIFIER_REQUEST_POSITIVE:
            # Request for positive response
            # TODO Actually read a parameter from memory
            payload = [self.IDENTIFIER_REQUEST_POSITIVE_RESPONSE]
            response_data = self.create_positive_response(service_id, payload)
        elif request == self.IDENTIFIER_REQUEST_NEGATIVE:
            # Request for negative response - use Conditions Not Correct
            nrc = iso14229_1.Iso14229_1_nrc.CONDITIONS_NOT_CORRECT
            response_data = self.create_negative_response(service_id, nrc)
        else:
            # Unmatched request - use a general reject response
            nrc = iso14229_1.Iso14229_1_nrc.GENERAL_REJECT
            response_data = self.create_negative_response(service_id, nrc)
        return response_data

    def handle_write_data_by_identifier(self, data):
        """
        Evaluates a write data by identifier request and returns the appropriate response

        :param data: Data from incoming request
        :return: Response to be sent
        """
        service_id = data[0]

        identifier_start_position = 1
        identifier_length = 2
        identifier = int_from_byte_list(data,
                                        identifier_start_position,
                                        identifier_length)
        request_data = data[3:]
        # TODO Actually write data to memory
        if identifier == self.REQUEST_IDENTIFIER_VALID:
            # Request for positive response
            # Standard specifies the response payload to be an echo of the data identifier from the request
            payload = data[identifier_start_position:identifier_start_position+identifier_length]
            response_data = self.create_positive_response(service_id, payload)
        elif identifier == self.REQUEST_IDENTIFIER_INVALID:
            # Request for negative response - use Conditions Not Correct
            nrc = iso14229_1.Iso14229_1_nrc.CONDITIONS_NOT_CORRECT
            response_data = self.create_negative_response(service_id, nrc)
        else:
            # Unmatched request - use a general reject response
            nrc = iso14229_1.Iso14229_1_nrc.GENERAL_REJECT
            response_data = self.create_negative_response(service_id, nrc)
        return response_data

    def handle_read_memory_by_address(self, data):
        """
        Evaluates a read memory by address request and returns the appropriate response

        :param data: Data from incoming request
        :return: Response to be sent
        """
        service_id = data[0]
        address_field_size = (data[1] >> 4) & 0xF
        data_length_field_size = (data[1] & 0xF)
        address_start_position = 2
        data_length_start_position = 4

        start_address = int_from_byte_list(data, address_start_position, address_field_size)
        data_length = int_from_byte_list(data, data_length_start_position, data_length_field_size)
        end_address = start_address + data_length
        if 0 <= start_address <= end_address <= len(self.DATA):
            memory_data = self.DATA[start_address:end_address]
            response_data = self.create_positive_response(service_id, memory_data)
        else:
            nrc = iso14229_1.Iso14229_1_nrc.REQUEST_OUT_OF_RANGE
            response_data = self.create_negative_response(service_id, nrc)
        return response_data
