"""Which session key files this server will use (AVR-253; rule in core/party_protocol.py, vendored).

Nobody but the file's owner and this process may be able to read a key, and nobody but its owner
may change it. A file with no group or other bits passes on its mode. A systemd `LoadCredential=`
file passes on its ACL: systemd may leave it owned by root with a POSIX ACL granting this service's
user read, and its mode then reads 0440 because the group bits of a file with an ACL show the ACL
mask. A plainly group-readable key is still refused.
"""
from __future__ import annotations

import os
import struct

import pytest

from core import party_protocol as proto
from core import party_session

OWNER, USER, GROUP_OBJ, GROUP, MASK, OTHER = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20
NO_ID = 0xFFFFFFFF
ME, ROOT, SOMEONE = 993, 0, 1000
KEY = bytes(range(32))


def acl(*entries):
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *e) for e in entries)


def credential(reader=ME, owner=4, group=0, mask=4, other=0, extra=()):
    return acl((OWNER, owner, NO_ID), (USER, 4, reader), *extra, (GROUP_OBJ, group, NO_ID),
               (MASK, mask, NO_ID), (OTHER, other, NO_ID))


ACCEPTED = (
    ("private 0600, self-owned", 0o600, ME, None),
    ("private 0400, root-owned", 0o400, ROOT, None),
    ("private 0600, owned by another user", 0o600, SOMEONE, None),
    ("credential: root-owned, ACL for this user", 0o440, ROOT, credential()),
    ("credential: self-owned, ACL for this user", 0o440, ME, credential()),
)
REFUSED = (
    ("plain 0440, no ACL", 0o440, ROOT, None),
    ("plain 0640, no ACL", 0o640, ME, None),
    ("world-readable, even with a good ACL", 0o444, ROOT, credential()),
    ("world-writable bit", 0o442, ROOT, credential()),
    ("group write bit", 0o460, ROOT, credential()),
    ("group execute bit", 0o450, ROOT, credential()),
    ("ACL lets the owning group read", 0o440, ROOT, credential(group=4)),
    ("ACL names another user", 0o440, ROOT, credential(reader=SOMEONE)),
    ("ACL names a second user", 0o440, ROOT, credential(extra=((USER, 4, SOMEONE),))),
    ("ACL names a group", 0o440, ROOT, credential(extra=((GROUP, 4, 33),))),
    ("ACL lets the owner write", 0o440, ROOT, credential(owner=6)),
    ("ACL mask allows write", 0o440, ROOT, credential(mask=6)),
    ("ACL lets others read", 0o440, ROOT, credential(other=4)),
    ("ACL with no named user", 0o440, ROOT, acl((OWNER, 4, NO_ID), (GROUP_OBJ, 0, NO_ID),
                                               (MASK, 4, NO_ID), (OTHER, 0, NO_ID))),
    ("credential owned by a third user", 0o440, SOMEONE, credential()),
    ("truncated ACL", 0o440, ROOT, credential()[:-3]),
    ("unknown ACL version", 0o440, ROOT, struct.pack("<I", 1) + credential()[4:]),
    ("unknown ACL tag", 0o440, ROOT, acl((0x40, 4, NO_ID))),
    ("empty ACL", 0o440, ROOT, b""),
)


@pytest.mark.parametrize("name,mode,owner,acl_bytes", ACCEPTED, ids=[c[0] for c in ACCEPTED])
def test_accepted(name, mode, owner, acl_bytes):
    assert proto.key_file_problem(mode, owner, ME, acl_bytes) is None


@pytest.mark.parametrize("name,mode,owner,acl_bytes", REFUSED, ids=[c[0] for c in REFUSED])
def test_still_refused(name, mode, owner, acl_bytes):
    assert proto.key_file_problem(mode, owner, ME, acl_bytes)


@pytest.mark.skipif(os.name != "posix", reason="file modes are not enforced here")
def test_a_group_readable_key_still_turns_party_sessions_off(tmp_path, caplog):
    path = tmp_path / "bluff.key"
    proto.write_key(str(path), KEY)
    assert party_session.load_side("bluff", str(tmp_path)) is not None
    os.chmod(path, 0o640)
    assert party_session.load_side("bluff", str(tmp_path)) is None
    assert "unusable" in caplog.text and KEY.hex() not in caplog.text


@pytest.mark.skipif(not hasattr(os, "setxattr"), reason="POSIX ACLs need Linux")
def test_a_real_credential_shaped_file_gives_a_party_side(tmp_path):
    """read_key on a file whose ACL the kernel holds, through the path this server uses."""
    path = tmp_path / "bluff.key"
    proto.write_key(str(path), KEY)
    me = os.geteuid()
    try:
        os.setxattr(path, proto.ACL_XATTR, credential(reader=me))
    except OSError:
        pytest.skip("this filesystem does not store POSIX ACLs")
    assert os.stat(path).st_mode & 0o777 == 0o440            # the mask shows as the group bits
    side = party_session.load_side("bluff", str(tmp_path))
    assert side is not None and side.key == KEY
    os.setxattr(path, proto.ACL_XATTR, credential(reader=me, group=4))
    assert party_session.load_side("bluff", str(tmp_path)) is None      # the group really can read
    os.removexattr(path, proto.ACL_XATTR)
    os.chmod(path, 0o440)
    assert party_session.load_side("bluff", str(tmp_path)) is None      # plain 0440
