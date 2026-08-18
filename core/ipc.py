"""
QLocalServer / QLocalSocket IPC for Smart Instance Management (Feature 7).

Ensures single-instance running while allowing new launches to forward a message
to the primary running instance without dialog boxes.
"""

import logging
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

SERVER_NAME = "ECHO_IPC_SINGLE_INSTANCE"


def send_wake_to_running_instance() -> bool:
    """Attempt to connect to an already running ECHO instance via QLocalSocket.
    Returns True if an existing instance responded, False otherwise.
    """
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if socket.waitForConnected(500):
        logger.info("Existing ECHO instance detected. Sending wake signal...")
        socket.write(b"WAKE")
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return True
    return False


class IPCServer(QObject):
    """Local IPC server running on the main instance to listen for launch attempts."""

    wake_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)

        # Cleanup old instances of the pipe if left over after a crash
        QLocalServer.removeServer(SERVER_NAME)

        if not self.server.listen(SERVER_NAME):
            logger.error("Failed to start IPC local server '%s': %s", SERVER_NAME, self.server.errorString())
        else:
            logger.info("IPC local server listening on '%s'", SERVER_NAME)
            self.server.newConnection.connect(self._handle_connection)

    def _handle_connection(self):
        client = self.server.nextPendingConnection()
        if client:
            client.waitForReadyRead(500)
            data = client.readAll().data()
            logger.info("Received IPC message: %s", data)
            if b"WAKE" in data or data == b"":
                self.wake_requested.emit()
            client.disconnectFromServer()
