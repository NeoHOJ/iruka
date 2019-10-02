import enum
from iruka.protos import common_pb2


class Verdict(enum.IntEnum):
    # Each verdict defined in the protobuf enum should
    # have its name in this enum in order to determine
    # its priority
    UNDEF = 0
    AC = 1
    WA = 2
    PE = 3
    MLE = 4
    TLE = 5
    OLE = 6
    RE = 7
    CE = 8
    OTHER = 9
    RF = 10
    SERR = 11
    SKIPPED = 12
    PENDING = 13

    @classmethod
    def from_proto(cls, v):
        try:
            return getattr(cls, common_pb2.Verdict.Name(v))
        except ValueError:
            return cls.UNDEF

    @classmethod
    def from_proto_greater(cls, x, y):
        p = cls.from_proto(x)
        q = cls.from_proto(y)
        return p > q
