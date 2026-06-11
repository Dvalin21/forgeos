"""Tests for the app-store port allocator — pure, no real sockets."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_ports as fp  # noqa: E402

RANGE = (20000, 20010)


def test_pick_lowest_free():
    assert fp.pick_free_port(set(), port_range=RANGE) == 20000


def test_pick_skips_used():
    used = {20000, 20001, 20002}
    assert fp.pick_free_port(used, port_range=RANGE) == 20003


def test_preferred_honored_when_free():
    assert fp.pick_free_port(set(), preferred=20005, port_range=RANGE) == 20005


def test_preferred_skipped_when_taken():
    used = {20005}
    assert fp.pick_free_port(used, preferred=20005, port_range=RANGE) == 20000


def test_preferred_out_of_range_ignored():
    assert fp.pick_free_port(set(), preferred=99999, port_range=RANGE) == 20000


def test_no_free_port_raises():
    used = set(range(20000, 20011))
    with pytest.raises(fp.NoFreePortError):
        fp.pick_free_port(used, port_range=RANGE)


def test_allocate_avoids_live_bound_ports():
    # 20000 + 20001 "in use" on the live system; allocator must skip to 20002
    live = {20000, 20001}
    port = fp.allocate_port(set(), probe=lambda p: p in live, port_range=RANGE)
    assert port == 20002


def test_allocate_combines_db_and_live():
    used_by_apps = {20002}          # recorded in config DB
    live = {20000, 20001}           # bound on the system, not in our records
    port = fp.allocate_port(used_by_apps, probe=lambda p: p in live, port_range=RANGE)
    assert port == 20003


def test_allocate_preferred_when_free_everywhere():
    port = fp.allocate_port(set(), preferred=20007, probe=lambda p: False, port_range=RANGE)
    assert port == 20007


def test_allocate_raises_when_exhausted():
    # everything either recorded or live
    with pytest.raises(fp.NoFreePortError):
        fp.allocate_port(set(range(20000, 20011)), probe=lambda p: False, port_range=RANGE)
