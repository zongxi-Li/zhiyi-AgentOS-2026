"""受控低熵通信部件的公共入口。"""

from .algorithms import low_entropy_choice, select_fields
from .assembler import ContextAssembler
from .broker import CommunicationAccessError, CommunicationBroker, EntropyBudgetExceededError
from .contracts import ContextPack
from .manifest import CommunicationManifest, CommunicationRule
from .reader import CommunicationReader
from .provenance import ProvenanceLedger
from .service import CommunicatorService
from .reliable import (
    BlackboardConflictError, CommunicationBackpressureError, DebateCoordinator,
    DebateSpec, ReliableMessage, SQLiteReliableCommunicationStore,
)

__all__ = ["CommunicationAccessError", "CommunicationBroker", "CommunicationManifest", "CommunicationReader", "CommunicationRule", "CommunicatorService", "ContextAssembler", "ContextPack", "EntropyBudgetExceededError", "ProvenanceLedger", "BlackboardConflictError", "CommunicationBackpressureError", "DebateCoordinator", "DebateSpec", "ReliableMessage", "SQLiteReliableCommunicationStore", "low_entropy_choice", "select_fields"]
"""通信部件的公共入口。"""

from .service import CommunicatorService

__all__ = ["CommunicatorService"]
