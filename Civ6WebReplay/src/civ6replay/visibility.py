"""Per-player visibility parsing (port of ``ParseVisibility``)."""
from __future__ import annotations

from ._port_helpers import (
    VISIBILITY_BEGIN, _check, _range, _rarray, _rmap, _seek, peek_u32,
)
from .binary import read_int


def parse_visibility(data, players):
    it = _seek(data, VISIBILITY_BEGIN)
    it.advance(-(4))
    _rmap(it)
    _rmap(it)
    it.advance(4)
    playerCount = read_int(it)
    for iPlayer in _range(playerCount, it):
        p = players[iPlayer]
        it.advance(16)
        it.advance(1)
        p.visible = _rarray(it, 1, 0)
        # Only the visibility mask is published. Walk the remaining arrays to
        # reach the next player without retaining unused per-tile copies.
        it.advance(12)
        _check(peek_u32(it) == len(p.visible), it)
        it.advance(8)
        _rarray(it, 2, 0)
        it.advance(8)
        _check(peek_u32(it) == len(p.visible), it)
        it.advance(8)
        _rarray(it, 2, 0)
        it.advance(8)
        _check(peek_u32(it) == len(p.visible), it)
        it.advance(8)
        _rarray(it, 2, 0)
        it.advance(8)
        _check(peek_u32(it) == len(p.visible), it)
        it.advance(8)
        _rarray(it, 2, 0)
        it.advance(8)
        _check(peek_u32(it) == len(p.visible), it)
        it.advance(8)
        _rarray(it, 2, 0)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
